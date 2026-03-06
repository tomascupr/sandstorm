"""File upload, skills loading, and file extraction for E2B sandboxes."""

import base64
import contextlib
import json
import logging
import posixpath
import shlex
from pathlib import Path

from e2b import AsyncSandbox

from .config import _SKILL_NAME_PATTERN
from .telemetry import get_tracer

logger = logging.getLogger(__name__)

_MAX_EXTRACT_FILES = 10  # Max files to extract from sandbox after agent run
_MAX_EXTRACT_FILE_SIZE = 25 * 1024 * 1024  # 25 MB per file (Slack upload limit)
# Note: Vercel serverless has a 4.5 MB response limit — base64-encoded files
# larger than ~3 MB will exceed this. Self-hosted and Slack deployments are unaffected.
_MAX_EXTRACT_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB total extraction budget
_SANDBOX_HOME = "/home/user"


async def _upload_files(sbx: AsyncSandbox, files: dict[str, str], request_id: str) -> None:
    """Upload user files to the sandbox, creating parent directories as needed."""
    total_size = sum(len(c.encode()) for c in files.values())
    with get_tracer().start_as_current_span(
        "sandbox.upload_files",
        attributes={
            "sandstorm.file_count": len(files),
            "sandstorm.total_size_bytes": total_size,
        },
    ):
        logger.info("[%s] Uploading %d files", request_id, len(files))
        # Collect parent dirs that need creation (deduplicate, skip top-level files)
        dirs_to_create: set[str] = set()
        for path in files:
            if ".." in path.split("/"):
                raise ValueError(f"Invalid file path: {path!r}")
            parent = posixpath.dirname(path)
            if parent:  # non-empty means nested path like "src/main.py"
                dirs_to_create.add(f"/home/user/{parent}")

        if dirs_to_create:
            mkdir_cmd = " && ".join(f"mkdir -p {shlex.quote(d)}" for d in sorted(dirs_to_create))
            await sbx.commands.run(mkdir_cmd, timeout=10)

        try:
            await sbx.files.write_files(
                [
                    {"path": f"/home/user/{path}", "data": content}
                    for path, content in files.items()
                ]
            )
        except Exception as exc:
            paths = ", ".join(files.keys())
            raise RuntimeError(
                f"Failed to upload {len(files)} files ({paths}) to sandbox: {exc}"
            ) from exc


def _normalize_relative_path(path: str) -> str:
    """Normalize a sandbox-relative path to a stable, slash-separated form."""
    normalized = posixpath.normpath(path).lstrip("/")
    return "" if normalized == "." else normalized


def _has_hidden_segment(relative_path: str) -> bool:
    """Return True if any path segment is hidden (starts with a dot)."""
    return any(part.startswith(".") for part in relative_path.split("/") if part)


def _load_skills_dir(skills_dir: str) -> dict[str, dict[str, str]]:
    """Read all files from each skill subdirectory into {name: {relative_path: content}}.

    Each subdirectory must contain a SKILL.md to be recognized as a valid skill.
    .DS_Store files are skipped.
    """
    base = Path.cwd() / skills_dir
    skills: dict[str, dict[str, str]] = {}
    if not base.is_dir():
        return skills
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        if not _SKILL_NAME_PATTERN.match(entry.name):
            logger.warning("skills_dir: skipping %r (invalid name)", entry.name)
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        skill_files: dict[str, str] = {}
        for file_path in entry.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.name == ".DS_Store":
                continue
            relative = file_path.relative_to(entry)
            try:
                skill_files[str(relative)] = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning(
                    "skills_dir: skipping non-UTF-8 file %r in skill %r",
                    str(relative),
                    entry.name,
                )
        if "SKILL.md" not in skill_files:
            logger.warning(
                "skills_dir: skipping %r (SKILL.md is not readable as UTF-8)",
                entry.name,
            )
            continue
        skills[entry.name] = skill_files
    return skills


async def _create_extraction_marker(sbx: AsyncSandbox, request_id: str) -> str:
    """Create a per-run marker file used to find outputs touched during this turn."""
    marker_path = f"/tmp/sandstorm-extract-{request_id}.marker"
    await sbx.commands.run(f"touch {shlex.quote(marker_path)}", timeout=10)
    return marker_path


async def _upload_skills(
    sbx: AsyncSandbox, skills: dict[str, dict[str, str]], request_id: str
) -> None:
    """Upload all skill files to /home/user/.claude/skills/<name>/ in the sandbox."""
    with get_tracer().start_as_current_span(
        "sandbox.upload_skills",
        attributes={"sandstorm.skill_count": len(skills)},
    ):
        logger.info("[%s] Uploading %d skills", request_id, len(skills))
        # Collect all directories that need creation (skill roots + subdirs)
        dirs: set[str] = set()
        for name, skill_files in skills.items():
            dirs.add(f"/home/user/.claude/skills/{name}")
            for rel_path in skill_files:
                parent = posixpath.dirname(rel_path)
                if parent:
                    dirs.add(f"/home/user/.claude/skills/{name}/{parent}")
        mkdir_cmd = " && ".join(f"mkdir -p {shlex.quote(d)}" for d in sorted(dirs))
        await sbx.commands.run(mkdir_cmd, timeout=10)
        # Batch write all skill files
        write_list = []
        for name, skill_files in skills.items():
            for rel_path, content in skill_files.items():
                write_list.append(
                    {
                        "path": f"/home/user/.claude/skills/{name}/{rel_path}",
                        "data": content,
                    }
                )
        try:
            await sbx.files.write_files(write_list)
        except Exception as exc:
            names = ", ".join(skills.keys())
            raise RuntimeError(
                f"Failed to upload {len(skills)} skills ({names}) to sandbox: {exc}"
            ) from exc


async def _extract_generated_files(
    sbx: AsyncSandbox,
    input_file_names: set[str],
    request_id: str,
    marker_path: str,
) -> list[str]:
    """Extract new files created by the agent in /home/user/.

    Uses a per-run marker file to find files touched during this turn, filters out
    input files / dotfiles, reads each new file as bytes, and returns a list of
    JSON-encoded file events.
    """
    input_paths = {_normalize_relative_path(path) for path in input_file_names}
    candidate_limit = _MAX_EXTRACT_FILES + 1
    excluded_inputs = "".join(
        f" ! -path {shlex.quote(posixpath.join(_SANDBOX_HOME, path))}"
        for path in sorted(input_paths)
        if path
    )
    find_cmd = (
        f"find {shlex.quote(_SANDBOX_HOME)} "
        f"-path '*/.*' -prune -o -type f -cnewer {shlex.quote(marker_path)} "
        f"! -size +{_MAX_EXTRACT_FILE_SIZE}c"
        f"{excluded_inputs} "
        f"-printf '%P\\t%s\\n' | head -n {candidate_limit}"
    )

    try:
        result = await sbx.commands.run(find_cmd, timeout=10)
        candidates: list[tuple[str, int]] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                relative_path, size_text = line.rsplit("\t", 1)
                size = int(size_text)
            except ValueError:
                logger.warning("[%s] Skipping malformed extraction entry: %r", request_id, line)
                continue

            relative_path = _normalize_relative_path(relative_path)
            if not relative_path or _has_hidden_segment(relative_path):
                continue
            if relative_path in input_paths:
                continue
            if size > _MAX_EXTRACT_FILE_SIZE:
                logger.info(
                    "[%s] Skipping oversized file: %s (%d bytes)",
                    request_id,
                    relative_path,
                    size,
                )
                continue
            candidates.append((relative_path, size))

        if not candidates:
            logger.debug("[%s] No new files to extract", request_id)
            return []

        if len(candidates) > _MAX_EXTRACT_FILES:
            logger.info(
                "[%s] Capping file extraction at %d (found at least %d)",
                request_id,
                _MAX_EXTRACT_FILES,
                len(candidates),
            )
            candidates = candidates[:_MAX_EXTRACT_FILES]

        events: list[str] = []
        total_size = 0
        for relative_path, _reported_size in candidates:
            path = posixpath.join(_SANDBOX_HOME, relative_path)
            try:
                data = await sbx.files.read(path, format="bytes")
                raw = data if isinstance(data, bytes) else bytes(data)
                size = len(raw)

                if total_size + size > _MAX_EXTRACT_TOTAL_SIZE:
                    logger.info("[%s] Total extraction size limit reached", request_id)
                    break

                total_size += size
                encoded = base64.b64encode(raw).decode("ascii")
                events.append(
                    json.dumps(
                        {
                            "type": "file",
                            "name": posixpath.basename(relative_path),
                            "relative_path": relative_path,
                            "path": path,
                            "size": size,
                            "data": encoded,
                        }
                    )
                )
                logger.info("[%s] Extracted file: %s (%d bytes)", request_id, relative_path, size)
            except Exception:
                logger.warning("[%s] Failed to read %s", request_id, relative_path, exc_info=True)

        return events
    finally:
        with contextlib.suppress(Exception):
            await sbx.commands.run(f"rm -f {shlex.quote(marker_path)}", timeout=5)

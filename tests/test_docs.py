import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOC_ROOTS = (
    ROOT / "docs",
    ROOT / "examples",
    ROOT / "deploy",
)
DOC_FILES = (
    ROOT / "README.md",
    ROOT / "clients" / "typescript" / "README.md",
)

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _iter_doc_files() -> list[Path]:
    files = set(DOC_FILES)
    for root in DOC_ROOTS:
        files.update(root.rglob("*.md"))
    return sorted(files)


def _slugify(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = heading.replace("`", "")
    heading = re.sub(r"[^\w\s-]", "", heading.lower())
    return re.sub(r"[\s-]+", "-", heading).strip("-")


def _anchors(markdown_path: Path) -> set[str]:
    text = markdown_path.read_text(encoding="utf-8")
    text = _FENCED_CODE_RE.sub("", text)
    return {_slugify(match.group(2).strip()) for match in _HEADING_RE.finditer(text)}


def _local_link_target(source: Path, raw_target: str) -> tuple[Path, str] | None:
    target = raw_target.strip()
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    if target.startswith("#"):
        return source, parsed.fragment
    if not parsed.path:
        return None
    return (source.parent / unquote(parsed.path)).resolve(), parsed.fragment


def test_local_markdown_links_resolve():
    failures: list[str] = []

    for source in _iter_doc_files():
        text = source.read_text(encoding="utf-8")
        text = _FENCED_CODE_RE.sub("", text)
        for match in _MARKDOWN_LINK_RE.finditer(text):
            target = _local_link_target(source, match.group(1))
            if target is None:
                continue

            linked_path, fragment = target
            if not linked_path.exists():
                failures.append(f"{source.relative_to(ROOT)} -> {match.group(1)}")
                continue

            if fragment and linked_path.suffix == ".md":
                anchors = _anchors(linked_path)
                if fragment not in anchors:
                    failures.append(
                        f"{source.relative_to(ROOT)} -> {match.group(1)} missing anchor"
                    )

    assert failures == []


def test_typescript_client_is_not_documented_as_npm_package():
    text = "\n".join(path.read_text(encoding="utf-8") for path in _iter_doc_files())

    assert "npm install @duvo/sandstorm-client" not in text
    assert "pnpm add @duvo/sandstorm-client" not in text


def test_typescript_client_package_is_private():
    package_json = json.loads(
        (ROOT / "clients" / "typescript" / "package.json").read_text(encoding="utf-8")
    )

    assert package_json["private"] is True


def test_private_typescript_client_is_not_published_by_release_workflow():
    package_json = json.loads(
        (ROOT / "clients" / "typescript" / "package.json").read_text(encoding="utf-8")
    )
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    assert package_json["private"] is True
    assert "npm publish" not in workflow

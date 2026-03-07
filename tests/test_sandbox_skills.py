import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import sandstorm.config as config_mod
from sandstorm.config import (
    _PROVIDER_ENV_KEYS,
    _build_agent_config,
    _validate_sandstorm_config,
    load_sandstorm_config,
)
from sandstorm.files import (
    _MAX_EXTRACT_FILE_SIZE,
    _MAX_EXTRACT_FILES,
    _MAX_EXTRACT_TOTAL_SIZE,
    _extract_generated_files,
    _load_skills_dir,
)
from sandstorm.models import QueryRequest


class TestValidateSandstormConfigSkills:
    def test_provider_env_keys_keep_linear_api_key(self):
        assert "LINEAR_API_KEY" in _PROVIDER_ENV_KEYS

    def test_allowed_tools_valid(self):
        config = _validate_sandstorm_config({"allowed_tools": ["Skill", "Read", "Bash"]})
        assert config["allowed_tools"] == ["Skill", "Read", "Bash"]

    def test_allowed_tools_non_string_entries_dropped(self):
        config = _validate_sandstorm_config({"allowed_tools": ["Skill", 42]})
        assert "allowed_tools" not in config

    def test_allowed_tools_wrong_type_dropped(self):
        config = _validate_sandstorm_config({"allowed_tools": "not a list"})
        assert "allowed_tools" not in config

    def test_webhook_url_valid(self):
        config = _validate_sandstorm_config({"webhook_url": "https://example.com/webhooks/e2b"})
        assert config["webhook_url"] == "https://example.com/webhooks/e2b"

    def test_webhook_url_wrong_type_dropped(self):
        config = _validate_sandstorm_config({"webhook_url": 123})
        assert "webhook_url" not in config

    def test_skills_dir_nonexistent_dropped(self):
        config = _validate_sandstorm_config({"skills_dir": "/nonexistent/path/to/skills"})
        assert "skills_dir" not in config

    def test_template_skills_valid(self):
        config = _validate_sandstorm_config({"template_skills": True})
        assert config["template_skills"] is True

    def test_template_skills_false_valid(self):
        config = _validate_sandstorm_config({"template_skills": False})
        assert config["template_skills"] is False

    def test_template_skills_wrong_type_dropped(self):
        config = _validate_sandstorm_config({"template_skills": "yes"})
        assert "template_skills" not in config

    def test_template_skills_int_dropped(self):
        config = _validate_sandstorm_config({"template_skills": 1})
        assert "template_skills" not in config

    def test_max_turns_must_be_positive(self):
        config = _validate_sandstorm_config({"max_turns": 0})
        assert "max_turns" not in config

    def test_timeout_must_be_within_bounds(self):
        config = _validate_sandstorm_config({"timeout": 3601})
        assert "timeout" not in config

    def test_empty_model_dropped(self):
        config = _validate_sandstorm_config({"model": ""})
        assert "model" not in config

    def test_whitespace_model_dropped(self):
        config = _validate_sandstorm_config({"model": "   "})
        assert "model" not in config

    def test_load_sandstorm_config_reads_utf8(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "sandstorm.json").write_text('{"model":"sonnet"}', encoding="utf-8")
        monkeypatch.setattr(config_mod, "_config_cache", None)
        monkeypatch.setattr(config_mod, "_config_mtime", 0.0)

        original_read_text = Path.read_text
        seen: dict[str, str | None] = {}

        def _read_text(self, *args, **kwargs):
            seen["encoding"] = kwargs.get("encoding")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _read_text)

        assert load_sandstorm_config() == {"model": "sonnet"}
        assert seen["encoding"] == "utf-8"


class TestLoadSkillsDir:
    def test_loads_skill_md_from_subdirs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skill_a = skills_dir / "skill-a"
        skill_a.mkdir(parents=True)
        (skill_a / "SKILL.md").write_text("Skill A content")

        result = _load_skills_dir("skills")
        assert result == {"skill-a": {"SKILL.md": "Skill A content"}}

    def test_loads_all_files_in_skill(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skill = skills_dir / "pdf"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("PDF skill")
        (skill / "reference.md").write_text("Reference docs")
        scripts = skill / "scripts"
        scripts.mkdir()
        (scripts / "convert.py").write_text("print('convert')")

        result = _load_skills_dir("skills")
        assert result == {
            "pdf": {
                "SKILL.md": "PDF skill",
                "reference.md": "Reference docs",
                "scripts/convert.py": "print('convert')",
            }
        }

    def test_skips_ds_store(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skill = skills_dir / "test-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("content")
        (skill / ".DS_Store").write_text("junk")

        result = _load_skills_dir("skills")
        assert result == {"test-skill": {"SKILL.md": "content"}}

    def test_skips_non_utf8_files(self, tmp_path, monkeypatch, caplog):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skill = skills_dir / "test-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("content")
        (skill / "binary.dat").write_bytes(b"\xff\xfe\xfd")

        with caplog.at_level(logging.WARNING, logger="sandstorm.files"):
            result = _load_skills_dir("skills")

        assert result == {"test-skill": {"SKILL.md": "content"}}
        assert "skipping non-UTF-8 file 'binary.dat' in skill 'test-skill'" in caplog.text

    def test_skips_skill_when_skill_md_is_non_utf8(self, tmp_path, monkeypatch, caplog):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skill = skills_dir / "broken-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_bytes(b"\xff\xfe\xfd")

        with caplog.at_level(logging.WARNING, logger="sandstorm.files"):
            result = _load_skills_dir("skills")

        assert result == {}
        assert "skipping 'broken-skill' (SKILL.md is not readable as UTF-8)" in caplog.text

    def test_ignores_non_directories(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "not-a-dir.txt").write_text("ignored")

        result = _load_skills_dir("skills")
        assert result == {}

    def test_ignores_dirs_without_skill_md(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        (skills_dir / "empty-skill").mkdir(parents=True)

        result = _load_skills_dir("skills")
        assert result == {}

    def test_invalid_dir_names_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        # Valid skill
        valid = skills_dir / "good-skill"
        valid.mkdir(parents=True)
        (valid / "SKILL.md").write_text("valid")
        # Invalid names that should be skipped
        for bad_name in ["has space", "path..traversal", ".hidden"]:
            bad = skills_dir / bad_name
            bad.mkdir(parents=True)
            (bad / "SKILL.md").write_text("should be skipped")

        result = _load_skills_dir("skills")
        assert result == {"good-skill": {"SKILL.md": "valid"}}

    def test_nonexistent_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _load_skills_dir("nonexistent")
        assert result == {}

    def test_multiple_skills(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        for name in ["alpha", "beta"]:
            d = skills_dir / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"{name} content")

        result = _load_skills_dir("skills")
        assert result == {
            "alpha": {"SKILL.md": "alpha content"},
            "beta": {"SKILL.md": "beta content"},
        }


@pytest.fixture()
def _api_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")


@pytest.fixture(autouse=True)
def _reset_loaded_dotenv_values(monkeypatch):
    monkeypatch.setattr(config_mod, "_LOADED_DOTENV_VALUES", {})


def _req(**kwargs) -> QueryRequest:
    kwargs.setdefault("prompt", "test")
    return QueryRequest(**kwargs)


# Shorthand: disk skills use multi-file format {name: {path: content}}
def _disk(*names):
    return {n: {"SKILL.md": n.upper()} for n in names}


@pytest.mark.usefixtures("_api_keys")
class TestBuildAgentConfigSkillsWhitelist:
    def test_none_uses_all_disk_skills(self):
        config, skills = _build_agent_config(_req(), {}, _disk("a", "b"))
        assert skills == _disk("a", "b")
        assert config["has_skills"] is True

    def test_empty_list_uses_none(self):
        config, skills = _build_agent_config(_req(allowed_skills=[]), {}, _disk("a", "b"))
        assert skills == {}
        assert config["has_skills"] is False

    def test_whitelist_filters_to_subset(self):
        _, skills = _build_agent_config(_req(allowed_skills=["a"]), {}, _disk("a", "b"))
        assert skills == _disk("a")

    def test_missing_names_silently_ignored(self):
        _, skills = _build_agent_config(_req(allowed_skills=["a", "nonexistent"]), {}, _disk("a"))
        assert skills == _disk("a")

    def test_extra_skills_merged(self):
        _, skills = _build_agent_config(_req(extra_skills={"new": "NEW"}), {}, _disk("a"))
        assert skills == {**_disk("a"), "new": {"SKILL.md": "NEW"}}

    def test_extra_skills_override_same_name(self):
        _, skills = _build_agent_config(_req(extra_skills={"a": "REPLACED"}), {}, _disk("a"))
        assert skills == {"a": {"SKILL.md": "REPLACED"}}

    def test_whitelist_applied_after_merge(self):
        """Whitelist filters the merged result of disk + extra skills."""
        _, skills = _build_agent_config(
            _req(allowed_skills=["a", "new"], extra_skills={"new": "NEW"}),
            {},
            _disk("a", "b"),
        )
        assert skills == {**_disk("a"), "new": {"SKILL.md": "NEW"}}

    def test_whitelist_rejects_unlisted_extra_skills(self):
        """Extra skills not in skills whitelist are filtered out."""
        _, skills = _build_agent_config(
            _req(allowed_skills=["a"], extra_skills={"new": "NEW"}),
            {},
            _disk("a", "b"),
        )
        assert skills == _disk("a")

    def test_extra_skills_alone_without_disk(self):
        config, skills = _build_agent_config(_req(extra_skills={"inline": "content"}), {}, {})
        assert skills == {"inline": {"SKILL.md": "content"}}
        assert config["has_skills"] is True

    def test_extra_skills_alone_with_whitelist(self):
        """Extra skills without disk skills are still subject to whitelist."""
        _, skills = _build_agent_config(
            _req(allowed_skills=["inline"], extra_skills={"inline": "content", "other": "X"}),
            {},
            {},
        )
        assert skills == {"inline": {"SKILL.md": "content"}}

    def test_extra_skill_overrides_disk_before_whitelist(self):
        """Extra skills override same-name disk skills, then whitelist applies."""
        _, skills = _build_agent_config(
            _req(allowed_skills=["a"], extra_skills={"a": "REPLACED"}),
            {},
            _disk("a", "b"),
        )
        assert skills == {"a": {"SKILL.md": "REPLACED"}}

    def test_empty_whitelist_rejects_extra_skills(self):
        """Empty whitelist rejects all skills including extras."""
        config, skills = _build_agent_config(
            _req(allowed_skills=[], extra_skills={"new": "NEW"}),
            {},
            _disk("a"),
        )
        assert skills == {}
        assert config["has_skills"] is False

    def test_extra_wraps_as_skill_md(self):
        """Extra skills are wrapped as {SKILL.md: content}."""
        disk = {"pdf": {"SKILL.md": "PDF skill", "ref.md": "reference"}}
        _, skills = _build_agent_config(_req(extra_skills={"inline": "just markdown"}), {}, disk)
        assert skills["pdf"] == {"SKILL.md": "PDF skill", "ref.md": "reference"}
        assert skills["inline"] == {"SKILL.md": "just markdown"}

    def test_template_skills_sets_has_skills(self):
        """template_skills=True sets has_skills even with no disk/extra skills."""
        config, skills = _build_agent_config(_req(), {"template_skills": True}, {})
        assert skills == {}
        assert config["has_skills"] is True

    def test_empty_whitelist_with_template_skills(self):
        """template_skills=True keeps has_skills even when whitelist empties skills."""
        config, skills = _build_agent_config(
            _req(allowed_skills=[]), {"template_skills": True}, _disk("a")
        )
        assert skills == {}
        assert config["has_skills"] is True

    def test_template_skills_with_extras_and_whitelist(self):
        """Extras survive if whitelisted, has_skills is True."""
        config, skills = _build_agent_config(
            _req(allowed_skills=["new"], extra_skills={"new": "NEW", "rejected": "X"}),
            {"template_skills": True},
            _disk("a", "b"),
        )
        # Only the whitelisted extra survives; disk skills filtered out
        assert skills == {"new": {"SKILL.md": "NEW"}}
        assert config["has_skills"] is True


@pytest.mark.usefixtures("_api_keys")
class TestBuildAgentConfigMcpWhitelist:
    def test_none_uses_all(self):
        cfg = {"mcp_servers": {"s1": {"cmd": "a"}, "s2": {"cmd": "b"}}}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["mcp_servers"] == {"s1": {"cmd": "a"}, "s2": {"cmd": "b"}}

    def test_empty_list_uses_none(self):
        cfg = {"mcp_servers": {"s1": {"cmd": "a"}}}
        config, _ = _build_agent_config(_req(allowed_mcp_servers=[]), cfg, {})
        assert config["mcp_servers"] == {}

    def test_whitelist_filters(self):
        cfg = {"mcp_servers": {"s1": {"cmd": "a"}, "s2": {"cmd": "b"}}}
        config, _ = _build_agent_config(_req(allowed_mcp_servers=["s1"]), cfg, {})
        assert config["mcp_servers"] == {"s1": {"cmd": "a"}}

    def test_no_config_mcp_servers(self):
        config, _ = _build_agent_config(_req(allowed_mcp_servers=["s1"]), {}, {})
        assert config["mcp_servers"] is None

    def test_resolves_required_env_placeholders(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "lin-key")
        cfg = {
            "mcp_servers": {
                "linear": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-linear"],
                    "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
                }
            }
        }

        config, _ = _build_agent_config(_req(), cfg, {})

        assert config["mcp_servers"] == {
            "linear": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-linear"],
                "env": {"LINEAR_API_KEY": "lin-key"},
            }
        }

    def test_resolves_default_placeholders(self, monkeypatch):
        monkeypatch.delenv("MCP_BASE_URL", raising=False)
        cfg = {"mcp_servers": {"svc": {"url": "${MCP_BASE_URL:-https://example.com/mcp}"}}}

        config, _ = _build_agent_config(_req(), cfg, {})

        assert config["mcp_servers"] == {"svc": {"url": "https://example.com/mcp"}}

    def test_resolves_nested_placeholders(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "token-123")
        monkeypatch.setenv("MCP_BASE_URL", "https://mcp.example.com")
        cfg = {
            "mcp_servers": {
                "svc": {
                    "url": "${MCP_BASE_URL}/server",
                    "headers": {"Authorization": "Bearer ${API_TOKEN}"},
                    "args": ["--token=${API_TOKEN}"],
                }
            }
        }

        config, _ = _build_agent_config(_req(), cfg, {})

        assert config["mcp_servers"] == {
            "svc": {
                "url": "https://mcp.example.com/server",
                "headers": {"Authorization": "Bearer token-123"},
                "args": ["--token=token-123"],
            }
        }

    def test_resolves_empty_env_var_as_empty_string(self, monkeypatch):
        monkeypatch.setenv("LINEAR_API_KEY", "")
        cfg = {"mcp_servers": {"linear": {"env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"}}}}

        config, _ = _build_agent_config(_req(), cfg, {})

        assert config["mcp_servers"] == {"linear": {"env": {"LINEAR_API_KEY": ""}}}

    def test_reloads_project_dotenv_between_agent_runs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        cfg = {"mcp_servers": {"linear": {"env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"}}}}
        env_path = tmp_path / ".env"

        env_path.write_text("LINEAR_API_KEY=old-key\n", encoding="utf-8")
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["mcp_servers"] == {"linear": {"env": {"LINEAR_API_KEY": "old-key"}}}

        env_path.write_text("LINEAR_API_KEY=new-key\n", encoding="utf-8")
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["mcp_servers"] == {"linear": {"env": {"LINEAR_API_KEY": "new-key"}}}

    def test_reloads_values_loaded_from_dotenv_at_process_startup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        cfg = {"mcp_servers": {"linear": {"env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"}}}}
        env_path = tmp_path / ".env"

        env_path.write_text("LINEAR_API_KEY=old-key\n", encoding="utf-8")
        config_mod.load_project_dotenv()

        env_path.write_text("LINEAR_API_KEY=new-key\n", encoding="utf-8")
        config, _ = _build_agent_config(_req(), cfg, {})

        assert config["mcp_servers"] == {"linear": {"env": {"LINEAR_API_KEY": "new-key"}}}

    def test_preserves_explicit_process_env_when_dotenv_rotates(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LINEAR_API_KEY", "shell-key")
        cfg = {"mcp_servers": {"linear": {"env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"}}}}
        env_path = tmp_path / ".env"

        env_path.write_text("LINEAR_API_KEY=old-key\n", encoding="utf-8")
        config_mod.load_project_dotenv()

        env_path.write_text("LINEAR_API_KEY=new-key\n", encoding="utf-8")
        config, _ = _build_agent_config(_req(), cfg, {})

        assert config["mcp_servers"] == {"linear": {"env": {"LINEAR_API_KEY": "shell-key"}}}

    def test_preserves_matching_shell_env_when_key_is_removed_from_dotenv(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LINEAR_API_KEY", "shared-key")
        env_path = tmp_path / ".env"

        env_path.write_text("LINEAR_API_KEY=shared-key\n", encoding="utf-8")
        config_mod.load_project_dotenv()
        assert config_mod._LOADED_DOTENV_VALUES == {}

        env_path.unlink()
        config_mod._refresh_project_dotenv()

        assert config_mod._LOADED_DOTENV_VALUES == {}
        assert os.environ["LINEAR_API_KEY"] == "shared-key"

    def test_missing_required_placeholder_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        cfg = {"mcp_servers": {"linear": {"env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"}}}}

        with pytest.raises(ValueError, match="mcp_servers.linear requires environment variable"):
            _build_agent_config(_req(), cfg, {})

    def test_filters_before_resolving_placeholders(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        cfg = {
            "mcp_servers": {
                "blocked": {"env": {"TOKEN": "${MISSING_KEY}"}},
                "allowed": {"command": "ok"},
            }
        }

        config, _ = _build_agent_config(_req(allowed_mcp_servers=["allowed"]), cfg, {})

        assert config["mcp_servers"] == {"allowed": {"command": "ok"}}


@pytest.mark.usefixtures("_api_keys")
class TestBuildAgentConfigAgentsWhitelist:
    def test_none_uses_all(self):
        cfg = {"agents": {"r": {"model": "haiku"}, "w": {"model": "sonnet"}}}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["agents"] == {"r": {"model": "haiku"}, "w": {"model": "sonnet"}}

    def test_empty_list_uses_none(self):
        cfg = {"agents": {"r": {"model": "haiku"}, "w": {"model": "sonnet"}}}
        config, _ = _build_agent_config(_req(allowed_agents=[]), cfg, {})
        assert config["agents"] == {}

    def test_whitelist_filters(self):
        cfg = {"agents": {"r": {"model": "haiku"}, "w": {"model": "sonnet"}}}
        config, _ = _build_agent_config(_req(allowed_agents=["r"]), cfg, {})
        assert config["agents"] == {"r": {"model": "haiku"}}

    def test_list_agents_passed_through(self):
        """Agents as a list (not dict) are passed through without filtering."""
        cfg = {"agents": [{"name": "r"}, {"name": "w"}]}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["agents"] == [{"name": "r"}, {"name": "w"}]

    def test_extra_agents_merged(self):
        cfg = {"agents": {"r": {"model": "haiku"}}}
        config, _ = _build_agent_config(_req(extra_agents={"new": {"model": "opus"}}), cfg, {})
        assert config["agents"] == {
            "r": {"model": "haiku"},
            "new": {"model": "opus"},
        }

    def test_extra_agents_override_same_name(self):
        cfg = {"agents": {"r": {"model": "haiku"}}}
        config, _ = _build_agent_config(_req(extra_agents={"r": {"model": "opus"}}), cfg, {})
        assert config["agents"] == {"r": {"model": "opus"}}

    def test_extra_agents_without_config(self):
        config, _ = _build_agent_config(_req(extra_agents={"new": {"model": "opus"}}), {}, {})
        assert config["agents"] == {"new": {"model": "opus"}}

    def test_whitelist_applied_after_merge(self):
        """Whitelist filters the merged result of config + extra agents."""
        cfg = {"agents": {"r": {"model": "haiku"}, "w": {"model": "sonnet"}}}
        config, _ = _build_agent_config(
            _req(allowed_agents=["r", "new"], extra_agents={"new": {"model": "opus"}}), cfg, {}
        )
        assert config["agents"] == {
            "r": {"model": "haiku"},
            "new": {"model": "opus"},
        }

    def test_whitelist_rejects_unlisted_extra_agents(self):
        """extra_agents not in agents whitelist are filtered out."""
        cfg = {"agents": {"r": {"model": "haiku"}}}
        config, _ = _build_agent_config(
            _req(allowed_agents=["r"], extra_agents={"unlisted": {"model": "opus"}}), cfg, {}
        )
        assert config["agents"] == {"r": {"model": "haiku"}}

    def test_extra_agent_overrides_config_before_whitelist(self):
        """Extra agents override same-name config agents, then whitelist applies."""
        cfg = {"agents": {"r": {"model": "haiku"}, "w": {"model": "sonnet"}}}
        config, _ = _build_agent_config(
            _req(allowed_agents=["r"], extra_agents={"r": {"model": "opus"}}), cfg, {}
        )
        assert config["agents"] == {"r": {"model": "opus"}}

    def test_empty_whitelist_rejects_extra_agents(self):
        """Empty whitelist rejects all agents including extras."""
        cfg = {"agents": {"r": {"model": "haiku"}}}
        config, _ = _build_agent_config(
            _req(allowed_agents=[], extra_agents={"new": {"model": "opus"}}), cfg, {}
        )
        assert config["agents"] == {}

    def test_extra_agents_rejected_for_list_agents(self):
        """extra_agents raise ValueError when config agents is a list."""
        cfg = {"agents": [{"name": "r"}]}
        with pytest.raises(ValueError, match="require agents to be a dict"):
            _build_agent_config(_req(extra_agents={"new": {"model": "opus"}}), cfg, {})

    def test_allowed_agents_rejected_for_list_agents(self):
        """allowed_agents raise ValueError when config agents is a list."""
        cfg = {"agents": [{"name": "r"}]}
        with pytest.raises(ValueError, match="require agents to be a dict"):
            _build_agent_config(_req(allowed_agents=["r"]), cfg, {})


@pytest.mark.usefixtures("_api_keys")
class TestBuildAgentConfigAllowedTools:
    def test_none_uses_config(self):
        cfg = {"allowed_tools": ["Bash", "Read"]}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["allowed_tools"] == ["Bash", "Read"]

    def test_request_overrides_config(self):
        cfg = {"allowed_tools": ["Bash", "Read"]}
        config, _ = _build_agent_config(_req(allowed_tools=["Write"]), cfg, {})
        assert config["allowed_tools"] == ["Write"]

    def test_empty_list_overrides_config(self):
        cfg = {"allowed_tools": ["Bash", "Read"]}
        config, _ = _build_agent_config(_req(allowed_tools=[]), cfg, {})
        assert config["allowed_tools"] == []

    def test_skill_auto_added_for_config_sourced(self):
        """Skill is auto-added when allowed_tools comes from sandstorm.json config."""
        cfg = {"allowed_tools": ["Bash"]}
        config, _ = _build_agent_config(_req(), cfg, _disk("s"))
        assert "Skill" in config["allowed_tools"]

    def test_skill_not_auto_added_for_request_sourced(self):
        """Skill is NOT auto-added when allowed_tools comes from the request."""
        config, _ = _build_agent_config(_req(allowed_tools=["Bash"]), {}, _disk("s"))
        assert config["allowed_tools"] == ["Bash"]

    def test_skill_not_duplicated_in_config(self):
        cfg = {"allowed_tools": ["Bash", "Skill"]}
        config, _ = _build_agent_config(_req(), cfg, _disk("s"))
        assert config["allowed_tools"].count("Skill") == 1


@pytest.mark.usefixtures("_api_keys")
class TestTimeoutResolution:
    def test_request_timeout_overrides_config(self):
        config, _ = _build_agent_config(_req(timeout=600), {"timeout": 120}, {})
        assert config["timeout"] == 600

    def test_config_timeout_used_when_request_is_none(self):
        config, _ = _build_agent_config(_req(), {"timeout": 120}, {})
        assert config["timeout"] == 120

    def test_falls_back_to_300_when_neither_set(self):
        config, _ = _build_agent_config(_req(), {}, {})
        assert config["timeout"] == 300


@pytest.mark.usefixtures("_api_keys")
class TestMaxTurnsResolution:
    def test_request_max_turns_overrides_config(self):
        config, _ = _build_agent_config(_req(max_turns=1), {"max_turns": 5}, {})
        assert config["max_turns"] == 1

    def test_config_max_turns_used_when_request_is_none(self):
        config, _ = _build_agent_config(_req(), {"max_turns": 5}, {})
        assert config["max_turns"] == 5


@pytest.mark.usefixtures("_api_keys")
class TestBuildAgentConfigOutputFormat:
    _FMT_A = {"type": "json_schema", "schema": {"type": "object"}}
    _FMT_B = {"type": "json_schema", "schema": {"type": "array"}}

    def test_none_uses_config(self):
        cfg = {"output_format": self._FMT_A}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["output_format"] == self._FMT_A

    def test_request_overrides_config(self):
        cfg = {"output_format": self._FMT_A}
        config, _ = _build_agent_config(_req(output_format=self._FMT_B), cfg, {})
        assert config["output_format"] == self._FMT_B

    def test_request_without_config(self):
        config, _ = _build_agent_config(_req(output_format=self._FMT_A), {}, {})
        assert config["output_format"] == self._FMT_A

    def test_none_without_config(self):
        config, _ = _build_agent_config(_req(), {}, {})
        assert config["output_format"] is None

    def test_empty_dict_disables_output_format(self):
        """Explicit empty dict disables structured output (e.g. Slack mode)."""
        cfg = {"output_format": self._FMT_A}
        config, _ = _build_agent_config(_req(output_format={}), cfg, {})
        assert config["output_format"] is None


@pytest.mark.usefixtures("_api_keys")
class TestBuildAgentConfigSystemPromptAppend:
    def test_append_with_string_system_prompt(self):
        cfg = {"system_prompt": "You are helpful", "system_prompt_append": "extra instructions"}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["system_prompt"] == "You are helpful\n\nextra instructions"

    def test_append_with_dict_append_system_prompt(self):
        cfg = {
            "system_prompt": {"prepend": "pre", "append": "existing"},
            "system_prompt_append": "extra",
        }
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["system_prompt"] == {"prepend": "pre", "append": "existing\n\nextra"}

    def test_append_with_dict_prepend_only(self):
        cfg = {"system_prompt": {"prepend": "You are X"}, "system_prompt_append": "added"}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["system_prompt"] == {"prepend": "You are X", "append": "added"}

    def test_append_without_system_prompt(self):
        cfg = {"system_prompt_append": "standalone"}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["system_prompt"] == "standalone"

    def test_no_append(self):
        cfg = {"system_prompt": "unchanged"}
        config, _ = _build_agent_config(_req(), cfg, {})
        assert config["system_prompt"] == "unchanged"


# ---------------------------------------------------------------------------
# _extract_generated_files tests
# ---------------------------------------------------------------------------


def _cmd_result(stdout=""):
    """Create a mock command result."""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = ""
    result.exit_code = 0
    result.error = None
    return result


class TestExtractGeneratedFiles:
    _MARKER = "/tmp/sandstorm.marker"

    def _sbx(self, stdout=""):
        sbx = AsyncMock()
        sbx.files.read = AsyncMock(return_value=b"data")
        sbx.commands.run = AsyncMock(side_effect=[_cmd_result(stdout), _cmd_result("")])
        return sbx

    def test_returns_empty_when_no_recent_files(self):
        sbx = self._sbx()
        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        assert result == []
        sbx.files.read.assert_not_called()

    def test_skips_dotfiles(self):
        sbx = self._sbx(".bashrc\t5\n")
        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        assert result == []

    def test_skips_input_files(self):
        sbx = self._sbx("input.csv\t5\n")
        result = asyncio.run(_extract_generated_files(sbx, {"input.csv"}, "req1", self._MARKER))
        assert result == []

    def test_skips_oversized_files(self):
        sbx = self._sbx(f"huge.bin\t{_MAX_EXTRACT_FILE_SIZE + 1}\n")
        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        assert result == []

    def test_caps_at_max_files(self):
        stdout = "".join(f"file{i}.txt\t10\n" for i in range(15))
        sbx = self._sbx(stdout)
        sbx.files.read.return_value = b"x"

        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        assert len(result) == _MAX_EXTRACT_FILES

    def test_total_size_budget(self):
        sbx = self._sbx("a.bin\t100\nb.bin\t100\n")
        # Reported entry.size stays small here on purpose; the test verifies that the
        # extraction budget still uses the actual bytes returned by sbx.files.read().
        # Each returned payload is half the total budget + 1 byte, so only 1 fits.
        half_plus = _MAX_EXTRACT_TOTAL_SIZE // 2 + 1
        sbx.files.read.return_value = b"x" * half_plus

        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        assert len(result) == 1

    def test_returns_json_encoded_file_events(self):
        sbx = self._sbx("output.txt\t11\n")
        raw = b"hello world"
        sbx.files.read.return_value = raw

        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        assert len(result) == 1

        event = json.loads(result[0])
        assert event["type"] == "file"
        assert event["name"] == "output.txt"
        assert event["relative_path"] == "output.txt"
        assert event["path"] == "/home/user/output.txt"
        assert event["size"] == len(raw)
        assert base64.b64decode(event["data"]) == raw

    def test_extracts_nested_files_touched_this_turn(self):
        sbx = self._sbx("reports/summary.json\t6\ntop.txt\t3\n")

        async def _read(path, format="bytes"):
            if path.endswith("summary.json"):
                return b"nested"
            return b"top"

        sbx.files.read.side_effect = _read

        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        assert len(result) == 2

        nested_event = json.loads(result[0])
        top_event = json.loads(result[1])
        assert nested_event["relative_path"] == "reports/summary.json"
        assert nested_event["path"] == "/home/user/reports/summary.json"
        assert top_event["relative_path"] == "top.txt"

    def test_skips_nested_input_files_by_relative_path(self):
        sbx = self._sbx("reports/input.csv\t10\n")
        result = asyncio.run(
            _extract_generated_files(sbx, {"reports/input.csv"}, "req1", self._MARKER)
        )
        assert result == []

    def test_handles_read_failure(self):
        sbx = self._sbx("good.txt\t10\nbad.txt\t10\n")

        async def _read(path, format="bytes"):
            if path.endswith("bad.txt"):
                raise Exception("read error")
            return b"ok"

        sbx.files.read.side_effect = _read

        result = asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))
        # Only the successfully read file is returned
        assert len(result) == 1
        event = json.loads(result[0])
        assert event["name"] == "good.txt"

    def test_recent_scan_is_marker_scoped_and_bounded(self):
        sbx = self._sbx()

        asyncio.run(_extract_generated_files(sbx, set(), "req1", self._MARKER))

        scan_cmd = sbx.commands.run.await_args_list[0].args[0]
        assert f"-cnewer {self._MARKER}" in scan_cmd
        assert f"head -n {_MAX_EXTRACT_FILES + 1}" in scan_cmd
        sbx.files.list.assert_not_called()

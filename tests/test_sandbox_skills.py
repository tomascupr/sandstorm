import pytest

from sandstorm.models import QueryRequest
from sandstorm.sandbox import _build_agent_config, _load_skills_dir, _validate_sandstorm_config


class TestValidateSandstormConfigSkills:
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

    def test_empty_dict_overrides_config(self):
        """Explicit empty dict overrides config (is not None check, not falsy)."""
        cfg = {"output_format": self._FMT_A}
        config, _ = _build_agent_config(_req(output_format={}), cfg, {})
        assert config["output_format"] == {}

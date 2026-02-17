from sandstorm.sandbox import _load_skills_dir, _validate_sandstorm_config


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


class TestLoadSkillsDir:
    def test_loads_skill_md_from_subdirs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skill_a = skills_dir / "skill-a"
        skill_a.mkdir(parents=True)
        (skill_a / "SKILL.md").write_text("Skill A content")

        result = _load_skills_dir("skills")
        assert result == {"skill-a": "Skill A content"}

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
        assert result == {"good-skill": "valid"}

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
        assert result == {"alpha": "alpha content", "beta": "beta content"}

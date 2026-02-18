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

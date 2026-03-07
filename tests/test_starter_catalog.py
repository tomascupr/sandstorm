import json
from pathlib import Path

import pytest

from sandstorm.starter_catalog import (
    _apply_focus_sentence,
    _iter_text_files,
    list_starters,
    resolve_starter,
    scaffold_files,
)


def test_starter_catalog_contains_expected_slugs():
    assert [starter.slug for starter in list_starters()] == [
        "general-assistant",
        "research-brief",
        "document-analyst",
        "support-triage",
        "api-extractor",
        "security-audit",
    ]


def test_resolve_starter_supports_aliases():
    starter = resolve_starter("docs-to-openapi")

    assert starter.slug == "api-extractor"


def test_scaffold_files_adds_focus_sentence():
    starter = resolve_starter("research-brief")
    files = scaffold_files(starter, "Focus on B2B support automation")
    config = json.loads(files["sandstorm.json"])

    assert config["system_prompt_append"] == "Focus on B2B support automation"
    assert ".env.example" in files


def test_scaffold_files_maps_security_skill_path():
    starter = resolve_starter("security-audit")
    files = scaffold_files(starter)

    assert ".claude/skills/owasp-top-10/SKILL.md" in files


def test_iter_text_files_raises_helpful_error_for_non_utf8(tmp_path):
    bad_file = tmp_path / "bad.bin"
    bad_file.write_bytes(b"\xff\xfe")

    with pytest.raises(ValueError, match="bad.bin is not valid UTF-8"):
        list(_iter_text_files(tmp_path, Path()))


def test_apply_focus_sentence_reports_invalid_json():
    with pytest.raises(ValueError, match="general-assistant"):
        _apply_focus_sentence("general-assistant", "{not json", "focus")


def test_apply_focus_sentence_appends_to_existing_system_prompt_append():
    sandstorm_json = json.dumps(
        {
            "system_prompt": "Base prompt",
            "system_prompt_append": "Existing starter guidance.",
        }
    )

    updated = _apply_focus_sentence("general-assistant", sandstorm_json, "Company-specific focus")
    config = json.loads(updated)

    assert config["system_prompt_append"] == "Existing starter guidance.\n\nCompany-specific focus"

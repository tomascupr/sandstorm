"""Tests for the shared platform core (platform.py)."""

from sandstorm.platform import (
    build_query_request,
    gather_thread_context,
    unique_filename,
)
import pytest


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")


class TestBuildQueryRequest:
    def test_uses_env_defaults(self):
        request = build_query_request("hello world")
        assert request.prompt == "hello world"
        assert request.timeout is None
        assert request.model is None
        assert request.output_format == {}

    def test_attaches_files(self):
        files = {"data.csv": "a,b\n1,2"}
        request = build_query_request("analyze this", files)
        assert request.files == {"data.csv": "a,b\n1,2"}

    def test_scoped_memory_fields_passthrough(self):
        request = build_query_request(
            "hi", team_id="T1", user_id="U1", model="claude-haiku-4-5-20251001"
        )
        assert request.team_id == "T1"
        assert request.user_id == "U1"
        assert request.model == "claude-haiku-4-5-20251001"


class TestGatherThreadContext:
    def test_formats_thread_messages(self):
        messages = [
            {"user": "U001", "text": "Hey there"},
            {"user": "BBOT", "text": "Working on it..."},
        ]
        result = gather_thread_context(messages, "BBOT")
        assert "[U001] Hey there" in result
        assert "[Sandstorm] Working on it..." in result

    def test_includes_file_attachments(self):
        messages = [
            {
                "user": "U001",
                "text": "",
                "files": [{"name": "data.csv", "mimetype": "text/csv", "size": 15360}],
            },
        ]
        result = gather_thread_context(messages, "BBOT")
        assert "[attached: data.csv (text/csv, 15KB)]" in result

    def test_empty_messages(self):
        result = gather_thread_context([], "BBOT")
        assert result == ""

    def test_uses_display_names_when_provided(self):
        messages = [{"user": "U001", "text": "Hey there"}]
        user_names = {"U001": "Alice"}
        result = gather_thread_context(messages, "BBOT", user_names=user_names)
        assert "[Alice] Hey there" in result


class TestUniqueFilename:
    def test_first_use_unchanged(self):
        seen: set[str] = set()
        assert unique_filename("file.txt", seen) == "file.txt"

    def test_duplicate_gets_suffix(self):
        seen: set[str] = set()
        unique_filename("file.txt", seen)
        assert unique_filename("file.txt", seen) == "file_1.txt"

    def test_no_extension(self):
        seen: set[str] = set()
        unique_filename("README", seen)
        assert unique_filename("README", seen) == "README_1"

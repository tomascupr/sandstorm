import pytest
from pydantic import ValidationError

from sandstorm.models import QueryRequest


@pytest.fixture(autouse=True)
def _set_required_env_vars(monkeypatch):
    """Provide default API keys so the model validator passes."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")


class TestPromptValidation:
    def test_valid_prompt(self):
        req = QueryRequest(prompt="Hello world")
        assert req.prompt == "Hello world"

    def test_empty_prompt_rejected(self):
        with pytest.raises(ValidationError, match="prompt"):
            QueryRequest(prompt="")


class TestApiKeyResolution:
    def test_falls_back_to_env_vars(self):
        req = QueryRequest(prompt="test")
        assert req.anthropic_api_key == "sk-test-key"
        assert req.e2b_api_key == "e2b-test-key"

    def test_request_body_overrides_env(self):
        req = QueryRequest(
            prompt="test",
            anthropic_api_key="sk-override",
            e2b_api_key="e2b-override",
        )
        assert req.anthropic_api_key == "sk-override"
        assert req.e2b_api_key == "e2b-override"

    def test_missing_anthropic_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        with pytest.raises(ValidationError, match="anthropic_api_key is required"):
            QueryRequest(prompt="test")

    def test_missing_e2b_key_raises(self, monkeypatch):
        monkeypatch.delenv("E2B_API_KEY")
        with pytest.raises(ValidationError, match="e2b_api_key is required"):
            QueryRequest(prompt="test")

    def test_anthropic_key_not_required_with_alternate_provider(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
        req = QueryRequest(prompt="test")
        assert req.anthropic_api_key is None

    def test_openrouter_key_resolved_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
        req = QueryRequest(prompt="test")
        assert req.openrouter_api_key == "or-test-key"


class TestFileValidation:
    def test_path_traversal_rejected(self):
        with pytest.raises(ValidationError, match="Path traversal not allowed"):
            QueryRequest(prompt="test", files={"../etc/passwd": "evil"})

    def test_too_many_files_rejected(self):
        files = {f"file{i}.txt": "content" for i in range(21)}
        with pytest.raises(ValidationError, match="Too many files"):
            QueryRequest(prompt="test", files=files)

    def test_total_size_limit_exceeded(self):
        # Single file just over 10MB
        big_content = "x" * 10_000_001
        with pytest.raises(ValidationError, match="exceeds 10MB limit"):
            QueryRequest(prompt="test", files={"big.txt": big_content})

    def test_valid_files_accepted(self):
        req = QueryRequest(
            prompt="test",
            files={"hello.py": "print('hi')", "sub/dir/file.txt": "content"},
        )
        assert "hello.py" in req.files
        assert "sub/dir/file.txt" in req.files


class TestSkillsValidation:
    def test_valid_skills_accepted(self):
        req = QueryRequest(
            prompt="test",
            skills={"code-review": "---\nname: code-review\n---\nReview instructions"},
        )
        assert "code-review" in req.skills

    def test_skills_none_by_default(self):
        req = QueryRequest(prompt="test")
        assert req.skills is None

    def test_too_many_skills_rejected(self):
        skills = {f"skill-{i}": "content" for i in range(51)}
        with pytest.raises(ValidationError, match="Too many skills"):
            QueryRequest(prompt="test", skills=skills)

    def test_skills_total_size_limit(self):
        big_content = "x" * 5_000_001
        with pytest.raises(ValidationError, match="exceeds 5MB limit"):
            QueryRequest(prompt="test", skills={"big": big_content})

    def test_invalid_skill_name_rejected(self):
        for name in ["has space", "path/slash", "..", ""]:
            with pytest.raises(ValidationError):
                QueryRequest(prompt="test", skills={name: "content"})

    def test_skill_name_too_long_rejected(self):
        with pytest.raises(ValidationError, match="too long"):
            QueryRequest(prompt="test", skills={"a" * 101: "content"})

    def test_valid_skill_names(self):
        skills = {
            "my-skill": "content",
            "my_skill": "content",
            "MySkill123": "content",
        }
        req = QueryRequest(prompt="test", skills=skills)
        assert len(req.skills) == 3


class TestTimeoutBounds:
    def test_default_timeout(self):
        req = QueryRequest(prompt="test")
        assert req.timeout == 300

    def test_timeout_too_low(self):
        with pytest.raises(ValidationError, match="timeout"):
            QueryRequest(prompt="test", timeout=4)

    def test_timeout_too_high(self):
        with pytest.raises(ValidationError, match="timeout"):
            QueryRequest(prompt="test", timeout=3601)

    def test_valid_timeout(self):
        req = QueryRequest(prompt="test", timeout=60)
        assert req.timeout == 60

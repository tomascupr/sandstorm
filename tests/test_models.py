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


class TestWhitelistFields:
    def test_defaults_to_none(self):
        req = QueryRequest(prompt="test")
        assert req.allowed_mcp_servers is None
        assert req.allowed_skills is None
        assert req.allowed_tools is None
        assert req.allowed_agents is None
        assert req.extra_agents is None
        assert req.extra_skills is None

    def test_accepts_valid_string_lists(self):
        req = QueryRequest(
            prompt="test",
            allowed_mcp_servers=["server-a", "server-b"],
            allowed_skills=["my-skill"],
            allowed_tools=["Bash", "Read"],
            allowed_agents=["researcher"],
        )
        assert req.allowed_mcp_servers == ["server-a", "server-b"]
        assert req.allowed_skills == ["my-skill"]
        assert req.allowed_tools == ["Bash", "Read"]
        assert req.allowed_agents == ["researcher"]

    def test_empty_lists_accepted(self):
        req = QueryRequest(
            prompt="test",
            allowed_mcp_servers=[],
            allowed_skills=[],
            allowed_tools=[],
            allowed_agents=[],
        )
        assert req.allowed_mcp_servers == []
        assert req.allowed_skills == []
        assert req.allowed_tools == []
        assert req.allowed_agents == []

    def test_extra_skills_accepts_valid_names(self):
        req = QueryRequest(
            prompt="test",
            extra_skills={"my-skill": "# Skill content", "skill_2": "content"},
        )
        assert req.extra_skills == {"my-skill": "# Skill content", "skill_2": "content"}

    def test_extra_skills_rejects_invalid_names(self):
        with pytest.raises(ValidationError, match="Invalid skill name"):
            QueryRequest(prompt="test", extra_skills={"bad name!": "content"})

    def test_extra_skills_rejects_dotted_names(self):
        with pytest.raises(ValidationError, match="Invalid skill name"):
            QueryRequest(prompt="test", extra_skills={"path..traversal": "content"})

    def test_extra_agents_accepts_valid_names(self):
        req = QueryRequest(
            prompt="test",
            extra_agents={"helper": {"model": "haiku"}, "my-agent_2": {"model": "sonnet"}},
        )
        assert "helper" in req.extra_agents
        assert "my-agent_2" in req.extra_agents

    def test_extra_agents_rejects_invalid_names(self):
        with pytest.raises(ValidationError, match="Invalid agent name"):
            QueryRequest(prompt="test", extra_agents={"bad name!": {"model": "haiku"}})


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

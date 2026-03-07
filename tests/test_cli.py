import json
from pathlib import Path

from click.testing import CliRunner

import sandstorm.cli as cli_module
from sandstorm.cli import cli


def _make_fake_run_agent_in_sandbox(seen=None):
    async def _run(request, request_id):
        if seen is not None:
            seen["request_id"] = request_id
            seen["prompt"] = request.prompt
        yield json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": f"handled: {request.prompt}"}]},
            }
        )
        yield json.dumps({"type": "result", "subtype": "success", "num_turns": 1, "cost_usd": 0.0})

    return _run


def _disable_dotenv(monkeypatch):
    monkeypatch.setattr("sandstorm.cli.load_dotenv", lambda: None)


class TestCli:
    def test_bare_prompt_defaults_to_query(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
        seen = {}

        import sandstorm.sandbox as sandbox

        monkeypatch.setattr(sandbox, "run_agent_in_sandbox", _make_fake_run_agent_in_sandbox(seen))

        runner = CliRunner()
        result = runner.invoke(cli, ["hello from cli"])

        assert result.exit_code == 0
        assert "handled: hello from cli" in result.output
        assert seen["request_id"] == "cli"

    def test_query_rejects_binary_uploads(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")

        binary_file = tmp_path / "image.bin"
        binary_file.write_bytes(b"\xff\x00\xfe")

        runner = CliRunner()
        result = runner.invoke(cli, ["query", "inspect file", "-f", str(binary_file)])

        assert result.exit_code == 1
        assert "image.bin is not a text file" in result.output

    def test_query_uses_relative_paths_for_uploaded_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")

        nested_dir = tmp_path / "src"
        nested_dir.mkdir()
        text_file = nested_dir / "main.py"
        text_file.write_text("print('hi')")

        seen = {}

        async def _capture_request(request, request_id):
            seen["files"] = request.files
            async for line in _make_fake_run_agent_in_sandbox(seen)(request, request_id):
                yield line

        import sandstorm.sandbox as sandbox

        monkeypatch.setattr(sandbox, "run_agent_in_sandbox", _capture_request)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["query", "inspect", "-f", str(text_file)])

        assert result.exit_code == 0
        assert seen["files"] == {"src/main.py": "print('hi')"}

    def test_query_reports_missing_mcp_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        (tmp_path / "sandstorm.json").write_text(
            json.dumps(
                {
                    "mcp_servers": {
                        "linear": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-linear"],
                            "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["query", "inspect ticket"])

        assert result.exit_code == 1
        assert "mcp_servers.linear requires environment variable LINEAR_API_KEY" in result.output

    def test_init_list_shows_catalog(self, monkeypatch):
        _disable_dotenv(monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--list"])

        assert result.exit_code == 0
        assert "general-assistant" in result.output
        assert "research-brief" in result.output
        assert "competitive-analysis" in result.output

    def test_init_scaffolds_default_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "general-assistant"])

        starter_dir = tmp_path / "general-assistant"
        assert result.exit_code == 0
        assert starter_dir.is_dir()
        assert (starter_dir / "sandstorm.json").exists()
        assert (starter_dir / "README.md").exists()
        assert (starter_dir / ".env.example").exists()
        assert "Initialized general-assistant" in result.output

    def test_init_alias_uses_canonical_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "issue-triage"])

        assert result.exit_code == 0
        assert (tmp_path / "support-triage").is_dir()
        assert not (tmp_path / "issue-triage").exists()
        assert "Initialized support-triage" in result.output

    def test_init_interactive_writes_focus_sentence_and_env_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input=(
                "document-analyst\n"
                "Help customer success review onboarding calls\n"
                "sk-test-key\n"
                "e2b-test-key\n"
            ),
        )

        starter_dir = tmp_path / "document-analyst"
        config = json.loads((starter_dir / "sandstorm.json").read_text(encoding="utf-8"))

        assert result.exit_code == 0
        assert config["system_prompt_append"] == "Help customer success review onboarding calls"
        assert (starter_dir / ".env").read_text(encoding="utf-8").splitlines() == [
            "ANTHROPIC_API_KEY=sk-test-key",
            "E2B_API_KEY=e2b-test-key",
        ]
        assert (starter_dir / ".env").stat().st_mode & 0o777 == 0o600

    def test_init_interactive_uses_openrouter_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://openrouter.ai/api")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input=("general-assistant\nUse this for vendor research\nsk-or-test-key\n"),
        )

        starter_dir = tmp_path / "general-assistant"
        env_lines = (starter_dir / ".env").read_text(encoding="utf-8").splitlines()

        assert result.exit_code == 0
        assert "OPENROUTER_API_KEY" in result.output
        assert "ANTHROPIC_API_KEY" not in result.output
        assert env_lines == [
            "E2B_API_KEY=e2b-test-key",
            "ANTHROPIC_BASE_URL=https://openrouter.ai/api",
            "OPENROUTER_API_KEY=sk-or-test-key",
        ]

    def test_init_interactive_reports_default_openrouter_base_url(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("E2B_API_KEY", raising=False)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input=("general-assistant\nUse this for vendor research\ne2b-test-key\n"),
        )

        starter_dir = tmp_path / "general-assistant"
        env_lines = (starter_dir / ".env").read_text(encoding="utf-8").splitlines()

        assert result.exit_code == 0
        assert "Using default OpenRouter base URL: https://openrouter.ai/api" in result.output
        assert env_lines == [
            "ANTHROPIC_BASE_URL=https://openrouter.ai/api",
            "OPENROUTER_API_KEY=sk-or-test-key",
            "E2B_API_KEY=e2b-test-key",
        ]

    def test_init_explicit_directory_scaffolds_without_prompting(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        target_dir = Path("my-audit")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "security-audit", str(target_dir)])

        assert result.exit_code == 0
        skill_path = tmp_path / "my-audit" / ".claude" / "skills" / "owasp-top-10" / "SKILL.md"
        assert skill_path.exists()
        assert (tmp_path / "my-audit" / ".env").exists() is False

    def test_init_fails_on_existing_non_empty_directory_without_force(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        starter_dir = tmp_path / "general-assistant"
        starter_dir.mkdir()
        (starter_dir / "notes.txt").write_text("keep", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "general-assistant"])

        assert result.exit_code == 1
        assert "already exists and is not empty" in result.output

    def test_init_force_overwrites_managed_files_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        starter_dir = tmp_path / "support-triage"
        starter_dir.mkdir()
        (starter_dir / "sandstorm.json").write_text('{"system_prompt":"old"}', encoding="utf-8")
        (starter_dir / "keep.txt").write_text("leave me", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "support-triage", "--force"])

        config = json.loads((starter_dir / "sandstorm.json").read_text(encoding="utf-8"))

        assert result.exit_code == 0
        assert config["model"] == "sonnet"
        assert (starter_dir / "keep.txt").read_text(encoding="utf-8") == "leave me"

    def test_init_rejects_unknown_starter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "unknown-starter"])

        assert result.exit_code == 2
        assert "Unknown starter" in result.output

    def test_init_prints_file_upload_next_step_for_document_analyst(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "document-analyst"])

        assert result.exit_code == 0
        assert "-f /path/to/transcript.txt" in result.output

    def test_init_rejects_scaffold_path_traversal(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setattr(
            "sandstorm.cli.scaffold_files",
            lambda *args, **kwargs: {"../../escape.txt": "nope"},
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["init", "general-assistant"])

        assert result.exit_code == 1
        assert "resolves outside" in result.output
        assert not (tmp_path.parent / "escape.txt").exists()

    def test_init_interactive_skips_env_write_when_required_values_left_blank(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setattr(
            "sandstorm.cli._resolve_init_env_values",
            lambda: ({}, ["ANTHROPIC_API_KEY", "E2B_API_KEY"]),
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input=("general-assistant\nKeep answers concise\n \n \n"),
        )

        starter_dir = tmp_path / "general-assistant"

        assert result.exit_code == 0
        assert not (starter_dir / ".env").exists()
        assert "left blank" in result.output
        assert "ANTHROPIC_API_KEY, E2B_API_KEY" in result.output

    def test_init_sanitizes_newlines_in_env_values(self, tmp_path, monkeypatch):
        answers = iter(["sk-test\nline2", "e2b-test-key"])
        starter_dir = tmp_path / "general-assistant"
        starter_dir.mkdir()
        monkeypatch.setattr(
            "sandstorm.cli._resolve_init_env_values",
            lambda: ({}, ["ANTHROPIC_API_KEY", "E2B_API_KEY"]),
        )
        monkeypatch.setattr("sandstorm.cli.click.prompt", lambda *args, **kwargs: next(answers))

        env_written, missing = cli_module._maybe_prompt_for_env_file(starter_dir)
        env_lines = (starter_dir / ".env").read_text(encoding="utf-8").splitlines()

        assert env_written is True
        assert missing == []
        assert env_lines == [
            "ANTHROPIC_API_KEY=sk-test line2",
            "E2B_API_KEY=e2b-test-key",
        ]

    def test_add_list_shows_toolpacks(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "--list"])

        assert result.exit_code == 0
        assert "linear" in result.output
        assert "LINEAR_API_KEY" in result.output
        assert "no project" in result.output

    def test_add_list_marks_installed_toolpack(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        (tmp_path / "sandstorm.json").write_text(
            json.dumps(
                {
                    "mcp_servers": {
                        "linear": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-linear"],
                            "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "--list"])

        assert result.exit_code == 0
        assert "installed" in result.output

    def test_add_list_marks_customized_toolpack(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        (tmp_path / "sandstorm.json").write_text(
            json.dumps({"mcp_servers": {"linear": {"command": "custom"}}}),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "--list"])

        assert result.exit_code == 0
        assert "customized (use --force)" in result.output

    def test_add_requires_project_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("LINEAR_API_KEY", "lin-api-key")

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear"])

        assert result.exit_code == 1
        assert "sandstorm.json not found" in result.output

    def test_add_installs_linear_and_updates_env_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        (tmp_path / "sandstorm.json").write_text(
            json.dumps({"model": "sonnet", "allowed_tools": ["Read"]}),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear"], input="lin-api-key\n")

        config = json.loads((tmp_path / "sandstorm.json").read_text(encoding="utf-8"))
        env_lines = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
        env_example_lines = (tmp_path / ".env.example").read_text(encoding="utf-8").splitlines()

        assert result.exit_code == 0
        assert config["mcp_servers"]["linear"] == {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-linear"],
            "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
        }
        assert config["allowed_tools"] == ["Read", "mcp__linear"]
        assert env_lines == ["LINEAR_API_KEY='lin-api-key'"]
        assert env_example_lines == ["LINEAR_API_KEY="]
        assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600

    def test_add_persists_existing_shell_env_without_prompt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("LINEAR_API_KEY", "lin-api-key")
        (tmp_path / "sandstorm.json").write_text('{"model":"sonnet"}', encoding="utf-8")
        prompted = False

        def _prompt(*args, **kwargs):
            nonlocal prompted
            prompted = True
            return "unexpected"

        monkeypatch.setattr("sandstorm.cli.click.prompt", _prompt)

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear"])

        assert result.exit_code == 0
        assert prompted is False
        assert "LINEAR_API_KEY='lin-api-key'" in (tmp_path / ".env").read_text(encoding="utf-8")

    def test_add_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("LINEAR_API_KEY", "lin-api-key")
        (tmp_path / "sandstorm.json").write_text(
            json.dumps(
                {
                    "mcp_servers": {
                        "linear": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-linear"],
                            "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
                        }
                    },
                    "allowed_tools": ["Read", "mcp__linear"],
                }
            ),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear"])

        assert result.exit_code == 0
        assert "already installed" in result.output

    def test_add_preserves_project_env_over_shell_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("LINEAR_API_KEY", "shell-key")
        (tmp_path / "sandstorm.json").write_text(
            json.dumps(
                {
                    "mcp_servers": {
                        "linear": {
                            "command": "npx",
                            "args": ["-y", "@modelcontextprotocol/server-linear"],
                            "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / ".env").write_text("LINEAR_API_KEY='project-key'\n", encoding="utf-8")
        prompted = False

        def _prompt(*args, **kwargs):
            nonlocal prompted
            prompted = True
            return "unexpected"

        monkeypatch.setattr("sandstorm.cli.click.prompt", _prompt)

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear"])

        assert result.exit_code == 0
        assert prompted is False
        assert (tmp_path / ".env").read_text(encoding="utf-8").splitlines() == [
            "LINEAR_API_KEY='project-key'"
        ]

    def test_add_rejects_conflicting_toolpack_without_force(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("LINEAR_API_KEY", "lin-api-key")
        (tmp_path / "sandstorm.json").write_text(
            json.dumps({"mcp_servers": {"linear": {"command": "custom"}}}),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear"])

        assert result.exit_code == 1
        assert "Use --force to overwrite it" in result.output

    def test_add_force_overwrites_only_toolpack_server(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("LINEAR_API_KEY", "lin-api-key")
        (tmp_path / "sandstorm.json").write_text(
            json.dumps(
                {
                    "mcp_servers": {
                        "linear": {"command": "custom"},
                        "github": {"command": "other"},
                    }
                }
            ),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear", "--force"])

        config = json.loads((tmp_path / "sandstorm.json").read_text(encoding="utf-8"))

        assert result.exit_code == 0
        assert config["mcp_servers"]["linear"]["command"] == "npx"
        assert config["mcp_servers"]["github"] == {"command": "other"}

    def test_add_rejects_invalid_allowed_tools_shape(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _disable_dotenv(monkeypatch)
        monkeypatch.setenv("LINEAR_API_KEY", "lin-api-key")
        (tmp_path / "sandstorm.json").write_text(
            json.dumps({"allowed_tools": "Read"}),
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["add", "linear"])

        assert result.exit_code == 1
        assert "allowed_tools" in result.output

    def test_webhook_register_rejects_non_http_url(self, monkeypatch):
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["webhook", "register", "file:///tmp/webhook"])

        assert result.exit_code == 1
        assert "URL must use http:// or https://" in result.output

    def test_webhook_test_rejects_non_http_url(self, monkeypatch):
        _disable_dotenv(monkeypatch)

        runner = CliRunner()
        result = runner.invoke(cli, ["webhook", "test", "file:///tmp/webhook"])

        assert result.exit_code == 1
        assert "URL must use http:// or https://" in result.output

import json

from click.testing import CliRunner

from sandstorm.cli import cli


async def _fake_run_agent_in_sandbox(request, request_id):
    assert request_id == "cli"
    yield json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": f"handled: {request.prompt}"}]},
        }
    )
    yield json.dumps({"type": "result", "subtype": "success", "num_turns": 1, "cost_usd": 0.0})


class TestCli:
    def test_bare_prompt_defaults_to_query(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")

        import sandstorm.sandbox as sandbox

        monkeypatch.setattr(sandbox, "run_agent_in_sandbox", _fake_run_agent_in_sandbox)

        runner = CliRunner()
        result = runner.invoke(cli, ["hello from cli"])

        assert result.exit_code == 0
        assert "handled: hello from cli" in result.output

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
            async for line in _fake_run_agent_in_sandbox(request, request_id):
                yield line

        import sandstorm.sandbox as sandbox

        monkeypatch.setattr(sandbox, "run_agent_in_sandbox", _capture_request)
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(cli, ["query", "inspect", "-f", str(text_file)])

        assert result.exit_code == 0
        assert seen["files"] == {"src/main.py": "print('hi')"}

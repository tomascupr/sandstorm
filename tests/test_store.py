"""Tests for the RunStore and dashboard/runs endpoints."""

import json
import os

from sandstorm.store import Run, RunStore


class TestRunCreation:
    def test_create_returns_run_with_running_status(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        run = store.create(id="r1", prompt="hello", model="claude-sonnet-4-20250514")
        assert run.id == "r1"
        assert run.status == "running"
        assert run.prompt == "hello"
        assert run.model == "claude-sonnet-4-20250514"

    def test_create_truncates_long_prompts(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        long_prompt = "x" * 200
        run = store.create(id="r1", prompt=long_prompt, model=None)
        assert len(run.prompt) == 100

    def test_create_sets_started_at(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        run = store.create(id="r1", prompt="test", model=None)
        assert run.started_at is not None
        assert "T" in run.started_at  # ISO format

    def test_create_tracks_files_count(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        run = store.create(id="r1", prompt="test", model=None, files_count=3)
        assert run.files_count == 3

    def test_created_run_appears_in_list(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.create(id="r1", prompt="hello", model=None)
        runs = store.list()
        assert len(runs) == 1
        assert runs[0]["id"] == "r1"
        assert runs[0]["status"] == "running"


class TestRunCompletion:
    def test_complete_updates_status(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.create(id="r1", prompt="test", model=None)
        store.complete(id="r1", cost_usd=0.05, num_turns=3, duration_secs=12.5)
        runs = store.list()
        assert runs[0]["status"] == "completed"
        assert runs[0]["cost_usd"] == 0.05
        assert runs[0]["num_turns"] == 3
        assert runs[0]["duration_secs"] == 12.5

    def test_complete_persists_to_jsonl(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        store = RunStore(path=path)
        store.create(id="r1", prompt="test", model=None)
        store.complete(id="r1", cost_usd=0.01)
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["status"] == "completed"
        assert data["cost_usd"] == 0.01

    def test_complete_unknown_id_is_noop(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.complete(id="nonexistent")  # should not raise


class TestRunFailure:
    def test_fail_updates_status_and_error(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.create(id="r1", prompt="test", model=None)
        store.fail(id="r1", error="sandbox timeout", duration_secs=300.0)
        runs = store.list()
        assert runs[0]["status"] == "error"
        assert runs[0]["error"] == "sandbox timeout"
        assert runs[0]["duration_secs"] == 300.0

    def test_fail_persists_to_jsonl(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        store = RunStore(path=path)
        store.create(id="r1", prompt="test", model=None)
        store.fail(id="r1", error="boom")
        data = json.loads(path.read_text().strip())
        assert data["status"] == "error"
        assert data["error"] == "boom"

    def test_fail_unknown_id_is_noop(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.fail(id="nonexistent", error="err")  # should not raise


class TestListOrdering:
    def test_list_returns_newest_first(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        store.create(id="r1", prompt="first", model=None)
        store.create(id="r2", prompt="second", model=None)
        store.create(id="r3", prompt="third", model=None)
        runs = store.list()
        assert [r["id"] for r in runs] == ["r3", "r2", "r1"]

    def test_list_respects_limit(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        for i in range(10):
            store.create(id=f"r{i}", prompt=f"run {i}", model=None)
        runs = store.list(limit=3)
        assert len(runs) == 3
        assert runs[0]["id"] == "r9"  # newest

    def test_list_default_limit(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl")
        for i in range(60):
            store.create(id=f"r{i}", prompt=f"run {i}", model=None)
        runs = store.list()
        assert len(runs) == 50  # default limit


class TestJsonlPersistence:
    def test_load_from_existing_file(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        # Create store and add runs, then complete them so they persist
        store1 = RunStore(path=path)
        store1.create(id="r1", prompt="first", model="claude-sonnet-4-20250514")
        store1.complete(id="r1", cost_usd=0.02, num_turns=2, duration_secs=5.0)
        store1.create(id="r2", prompt="second", model="claude-sonnet-4-20250514")
        store1.complete(id="r2", cost_usd=0.03, num_turns=4, duration_secs=10.0)

        # Create new store from same file
        store2 = RunStore(path=path)
        runs = store2.list()
        assert len(runs) == 2
        assert runs[0]["id"] == "r2"
        assert runs[0]["status"] == "completed"
        assert runs[1]["id"] == "r1"

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        valid_run = {
            "id": "r1",
            "prompt": "test",
            "model": None,
            "status": "completed",
            "started_at": "2025-01-01T00:00:00+00:00",
            "cost_usd": None,
            "num_turns": None,
            "duration_secs": None,
            "error": None,
            "files_count": 0,
        }
        path.write_text(
            json.dumps(valid_run)
            + "\n"
            + "not valid json\n"
            + '{"incomplete": true}\n'
            + "\n"  # blank line
        )
        store = RunStore(path=path)
        runs = store.list()
        assert len(runs) == 1
        assert runs[0]["id"] == "r1"

    def test_nonexistent_file_starts_empty(self, tmp_path):
        store = RunStore(path=tmp_path / "nonexistent" / "runs.jsonl")
        assert store.list() == []

    def test_empty_file_starts_empty(self, tmp_path):
        path = tmp_path / "runs.jsonl"
        path.write_text("")
        store = RunStore(path=path)
        assert store.list() == []


class TestFileWriteErrors:
    def test_write_to_readonly_path_does_not_crash(self, tmp_path):
        path = tmp_path / "readonly" / "runs.jsonl"
        store = RunStore(path=path)
        store.create(id="r1", prompt="test", model=None)
        # Make the parent directory read-only
        (tmp_path / "readonly").mkdir(exist_ok=True)
        os.chmod(tmp_path / "readonly", 0o444)
        try:
            # complete() tries to write — should not raise
            store.complete(id="r1", cost_usd=0.01)
        finally:
            os.chmod(tmp_path / "readonly", 0o755)


class TestDequeEviction:
    def test_maxlen_evicts_oldest(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl", maxlen=3)
        store.create(id="r1", prompt="first", model=None)
        store.create(id="r2", prompt="second", model=None)
        store.create(id="r3", prompt="third", model=None)
        store.create(id="r4", prompt="fourth", model=None)  # evicts r1
        runs = store.list()
        ids = [r["id"] for r in runs]
        assert "r1" not in ids
        assert len(runs) == 3
        assert ids == ["r4", "r3", "r2"]

    def test_evicted_run_removed_from_index(self, tmp_path):
        store = RunStore(path=tmp_path / "runs.jsonl", maxlen=2)
        store.create(id="r1", prompt="first", model=None)
        store.create(id="r2", prompt="second", model=None)
        store.create(id="r3", prompt="third", model=None)  # evicts r1
        # Completing evicted run should be a no-op
        store.complete(id="r1")
        runs = store.list()
        assert len(runs) == 2
        assert all(r["id"] != "r1" for r in runs)


class TestRunDataclass:
    def test_to_dict_returns_all_fields(self):
        run = Run(
            id="r1",
            prompt="test",
            model="claude-sonnet-4-20250514",
            status="running",
            started_at="2025-01-01T00:00:00+00:00",
        )
        d = run.to_dict()
        assert d["id"] == "r1"
        assert d["cost_usd"] is None
        assert d["files_count"] == 0


class TestDashboardEndpoint:
    def test_dashboard_returns_html(self):
        from fastapi.testclient import TestClient

        from sandstorm.main import app

        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestRunsEndpoint:
    def test_runs_returns_json_array(self):
        from fastapi.testclient import TestClient

        from sandstorm.main import app

        client = TestClient(app)
        response = client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_runs_returns_runs_after_creation(self, tmp_path):
        """Verify the /runs endpoint surfaces runs from the store."""
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from sandstorm.main import app
        from sandstorm.store import RunStore

        test_store = RunStore(path=tmp_path / "runs.jsonl")
        test_store.create(id="test-1", prompt="hello", model="claude-sonnet-4-20250514")
        test_store.create(id="test-2", prompt="world", model=None)
        test_store.complete(id="test-1", cost_usd=0.05, num_turns=2, duration_secs=8.0)

        with patch("sandstorm.main.run_store", test_store):
            client = TestClient(app)
            response = client.get("/runs")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            # Newest first
            assert data[0]["id"] == "test-2"
            assert data[0]["status"] == "running"
            assert data[1]["id"] == "test-1"
            assert data[1]["status"] == "completed"
            assert data[1]["cost_usd"] == 0.05

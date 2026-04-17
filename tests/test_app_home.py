"""Tests for the App Home view builder."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _isolate_stores(tmp_path, monkeypatch):
    """Point run_store and memory_store at temp files so tests don't share state."""
    from sandstorm.memory import MemoryStore
    from sandstorm.store import RunStore

    runs = RunStore(path=tmp_path / "runs.jsonl")
    mems = MemoryStore(path=tmp_path / "memories.jsonl")
    monkeypatch.setattr("sandstorm.store.run_store", runs)
    monkeypatch.setattr("sandstorm.app_home.run_store", runs)
    monkeypatch.setattr("sandstorm.memory.memory_store", mems)
    monkeypatch.setattr("sandstorm.app_home.memory_store", mems)
    monkeypatch.setattr("sandstorm.cancellation._active_runs", {})
    yield runs, mems


class TestBuildHomeView:
    def test_empty_state(self, _isolate_stores, monkeypatch):
        monkeypatch.setattr("sandstorm.app_home.load_sandstorm_config", lambda: None)
        from sandstorm.app_home import build_home_view

        view = build_home_view(team_id="T1", user_id="U1")
        assert view["type"] == "home"
        texts = [b.get("text", {}).get("text", "") for b in view["blocks"]]
        joined = "\n".join(t for t in texts if isinstance(t, str))
        assert "No Sandstorm runs yet" in joined
        assert "No personal memories yet" in joined

    def test_personal_memory_has_forget_button(self, _isolate_stores, monkeypatch):
        monkeypatch.setattr("sandstorm.app_home.load_sandstorm_config", lambda: None)
        _, memory_store = _isolate_stores
        memory_store.remember("T1", "U1", "likes oat milk")

        from sandstorm.app_home import build_home_view

        view = build_home_view(team_id="T1", user_id="U1")
        # Find the button
        buttons = []
        for block in view["blocks"]:
            if block.get("type") == "section":
                accessory = block.get("accessory")
                if accessory and accessory.get("type") == "button":
                    buttons.append(accessory)
        forget = [b for b in buttons if b.get("action_id") == "sandstorm_forget_memory"]
        assert len(forget) == 1
        assert forget[0]["value"]  # memory id

    def test_active_run_has_cancel_button(self, _isolate_stores, monkeypatch):
        monkeypatch.setattr("sandstorm.app_home.load_sandstorm_config", lambda: None)
        run_store, _ = _isolate_stores
        run_store.create(id="r1", prompt="long-running", model=None, team_id="T1", user_id="U1")
        # Register the run as active in the cancellation registry
        from sandstorm.cancellation import register_run

        register_run("r1")

        from sandstorm.app_home import build_home_view

        view = build_home_view(team_id="T1", user_id="U1")
        buttons = []
        for block in view["blocks"]:
            if block.get("type") == "section":
                accessory = block.get("accessory")
                if accessory and accessory.get("type") == "button":
                    buttons.append(accessory)
        cancel = [b for b in buttons if b.get("action_id") == "sandstorm_cancel_run"]
        assert len(cancel) == 1
        assert cancel[0]["value"] == "r1"

    def test_channel_defaults_render(self, _isolate_stores, monkeypatch):
        config = {"channels": {"C1": {"starter": "support-triage", "model": "sonnet"}}}
        monkeypatch.setattr("sandstorm.app_home.load_sandstorm_config", lambda: config)

        from sandstorm.app_home import build_home_view

        view = build_home_view(team_id="T1", user_id="U1")
        joined = "\n".join(
            b.get("text", {}).get("text", "")
            for b in view["blocks"]
            if isinstance(b.get("text", {}).get("text", ""), str)
        )
        assert "C1" in joined
        assert "support-triage" in joined

    def test_triggers_render(self, _isolate_stores, monkeypatch):
        config = {
            "triggers": [
                {
                    "name": "standup",
                    "type": "cron",
                    "schedule": "0 9 * * MON-FRI",
                    "prompt": "Post standup",
                }
            ]
        }
        monkeypatch.setattr("sandstorm.app_home.load_sandstorm_config", lambda: config)

        from sandstorm.app_home import build_home_view

        view = build_home_view(team_id="T1", user_id="U1")
        joined = "\n".join(
            b.get("text", {}).get("text", "")
            for b in view["blocks"]
            if isinstance(b.get("text", {}).get("text", ""), str)
        )
        assert "standup" in joined


class TestPublishHomeView:
    @pytest.mark.anyio
    async def test_publishes_via_client(self, _isolate_stores, monkeypatch):
        monkeypatch.setattr("sandstorm.app_home.load_sandstorm_config", lambda: None)
        from sandstorm.app_home import publish_home_view

        client = AsyncMock()
        client.views_publish = AsyncMock()
        await publish_home_view(client, user_id="U1", team_id="T1")
        client.views_publish.assert_awaited_once()
        call = client.views_publish.await_args
        assert call.kwargs["user_id"] == "U1"
        assert call.kwargs["view"]["type"] == "home"

    @pytest.mark.anyio
    async def test_swallows_exceptions(self, _isolate_stores, monkeypatch):
        monkeypatch.setattr("sandstorm.app_home.load_sandstorm_config", lambda: None)
        from sandstorm.app_home import publish_home_view

        client = AsyncMock()
        client.views_publish = AsyncMock(side_effect=RuntimeError("boom"))
        # Should not raise
        await publish_home_view(client, user_id="U1", team_id="T1")


@pytest.fixture
def anyio_backend():
    return "asyncio"

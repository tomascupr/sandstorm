import asyncio
import sys
import types

import pytest

from sandstorm.client import SandstormClient


class _FakeSseEvent:
    def __init__(self, data):
        self.data = data


class _FakeEventSource:
    def __init__(self, events):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def aiter_sse(self):
        for event in self._events:
            yield _FakeSseEvent(event)


async def _collect_events(client: SandstormClient, **kwargs):
    return [event async for event in client.query("test prompt", **kwargs)]


class TestSandstormClient:
    def test_health_requires_async_context(self):
        client = SandstormClient("https://example.com")
        with pytest.raises(RuntimeError, match="async with"):
            asyncio.run(client.health())

    def test_query_requires_async_context(self):
        client = SandstormClient("https://example.com")

        async def _consume():
            return [event async for event in client.query("hello")]

        with pytest.raises(RuntimeError, match="async with"):
            asyncio.run(_consume())

    def test_query_builds_request_and_yields_events(self, monkeypatch):
        captured = {}

        def _aconnect_sse(client, method, path, json):
            captured["client"] = client
            captured["method"] = method
            captured["path"] = path
            captured["json"] = json
            return _FakeEventSource(
                [
                    (
                        '{"type":"assistant","message":{"content":'
                        '[{"type":"text","text":"Hello "}]}}'
                    ),
                    '{"type":"assistant","message":{"content":[{"type":"text","text":"world"}]}}',
                    '{"type":"result","subtype":"success"}',
                ]
            )

        monkeypatch.setitem(
            sys.modules,
            "httpx_sse",
            types.SimpleNamespace(aconnect_sse=_aconnect_sse),
        )

        client = SandstormClient("https://example.com")
        client._client = object()

        events = asyncio.run(
            _collect_events(
                client,
                model="sonnet",
                max_turns=3,
                timeout=60,
                files={"notes.txt": "hello"},
                allowed_tools=["Read"],
            )
        )

        assert [event.type for event in events] == ["assistant", "assistant", "result"]
        assert events[0].text == "Hello "
        assert events[1].text == "world"
        assert captured["method"] == "POST"
        assert captured["path"] == "/query"
        assert captured["json"] == {
            "prompt": "test prompt",
            "allowed_tools": ["Read"],
            "model": "sonnet",
            "max_turns": 3,
            "timeout": 60,
            "files": {"notes.txt": "hello"},
        }

    def test_query_skips_invalid_json_events(self, monkeypatch):
        def _aconnect_sse(client, method, path, json):
            return _FakeEventSource(
                [
                    "not-json",
                    '{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}',
                ]
            )

        monkeypatch.setitem(
            sys.modules,
            "httpx_sse",
            types.SimpleNamespace(aconnect_sse=_aconnect_sse),
        )

        client = SandstormClient("https://example.com")
        client._client = object()

        events = asyncio.run(_collect_events(client))
        assert len(events) == 1
        assert events[0].text == "ok"

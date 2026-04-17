"""Tests for the trigger primitive (cron + webhook + reaction definitions).

Integration of cron scheduling + webhook route mounting happens in main.py
and is exercised via the TestClient in a smoke test; the unit tests here
cover the pure logic so we can iterate on it quickly.
"""

from __future__ import annotations

import asyncio

import pytest

from sandstorm.triggers import (
    TriggerDefinition,
    load_triggers,
    render_prompt,
    start_cron_scheduler,
    verify_webhook_secret,
)


class TestLoadTriggers:
    def test_absent_returns_empty(self):
        assert load_triggers({}) == []

    def test_wrong_type_raises(self):
        with pytest.raises(ValueError, match="must be a list"):
            load_triggers({"triggers": "not-a-list"})

    def test_parses_cron(self):
        triggers = load_triggers(
            {
                "triggers": [
                    {
                        "name": "daily",
                        "type": "cron",
                        "schedule": "0 9 * * MON-FRI",
                        "prompt": "Post standup",
                    }
                ]
            }
        )
        assert len(triggers) == 1
        t = triggers[0]
        assert t.name == "daily"
        assert t.type == "cron"
        assert t.schedule == "0 9 * * MON-FRI"

    def test_sub_hourly_cron_accepted(self):
        triggers = load_triggers(
            {
                "triggers": [
                    {
                        "name": "heartbeat",
                        "type": "cron",
                        "schedule": "* * * * *",
                        "prompt": "ping",
                    }
                ]
            }
        )
        assert triggers[0].schedule == "* * * * *"

    def test_invalid_cron_rejected(self):
        with pytest.raises(ValueError, match="invalid cron schedule"):
            load_triggers(
                {
                    "triggers": [
                        {
                            "name": "bad",
                            "type": "cron",
                            "schedule": "not a cron",
                            "prompt": "x",
                        }
                    ]
                }
            )

    def test_parses_webhook_with_secret(self):
        triggers = load_triggers(
            {
                "triggers": [
                    {
                        "name": "gh",
                        "type": "webhook",
                        "path": "/triggers/gh",
                        "secret": "s3cret",
                        "prompt": "triage {{body.issue.title}}",
                    }
                ]
            }
        )
        assert triggers[0].path == "/triggers/gh"
        assert triggers[0].secret == "s3cret"

    def test_webhook_without_secret_warns(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="sandstorm.triggers"):
            load_triggers(
                {
                    "triggers": [
                        {
                            "name": "open",
                            "type": "webhook",
                            "path": "/triggers/open",
                            "prompt": "x",
                        }
                    ]
                }
            )
        assert any("no `secret`" in rec.getMessage() for rec in caplog.records)

    def test_duplicate_webhook_path_rejected(self):
        with pytest.raises(ValueError, match="duplicate webhook path"):
            load_triggers(
                {
                    "triggers": [
                        {
                            "name": "a",
                            "type": "webhook",
                            "path": "/triggers/x",
                            "prompt": "p1",
                        },
                        {
                            "name": "b",
                            "type": "webhook",
                            "path": "/triggers/x",
                            "prompt": "p2",
                        },
                    ]
                }
            )

    def test_duplicate_name_rejected(self):
        with pytest.raises(ValueError, match="duplicate trigger name"):
            load_triggers(
                {
                    "triggers": [
                        {"name": "x", "type": "cron", "schedule": "* * * * *", "prompt": "p"},
                        {"name": "x", "type": "cron", "schedule": "0 * * * *", "prompt": "p"},
                    ]
                }
            )

    def test_parses_reaction(self):
        triggers = load_triggers(
            {
                "triggers": [
                    {
                        "name": "summarize",
                        "type": "reaction",
                        "emoji": "robot_face",
                        "channels": ["C123", "C456"],
                        "prompt": "Summarize {{message.text}}",
                    }
                ]
            }
        )
        t = triggers[0]
        assert t.type == "reaction"
        assert t.emoji == "robot_face"
        assert t.channels == ("C123", "C456")


class TestRenderPrompt:
    def test_substitutes_dotted_body(self):
        out = render_prompt(
            "Triage {{body.issue.title}}: {{body.issue.body}}",
            body={"issue": {"title": "Bug", "body": "Broken"}},
        )
        assert out == "Triage Bug: Broken"

    def test_missing_path_renders_empty(self):
        out = render_prompt(
            "{{body.missing.deep}} -- rest",
            body={"issue": {"title": "x"}},
        )
        assert out == " -- rest"

    def test_scalar_reaction(self):
        out = render_prompt("reacted: {{reaction}}", reaction="thumbsup")
        assert out == "reacted: thumbsup"

    def test_message_and_channel(self):
        out = render_prompt(
            "In {{channel.id}}, {{message.user}} said {{message.text}}",
            message={"user": "U1", "text": "hello"},
            channel={"id": "C1"},
        )
        assert out == "In C1, U1 said hello"

    def test_header_lookup(self):
        out = render_prompt(
            "trace={{headers.x-request-id}}",
            headers={"x-request-id": "abc"},
        )
        assert out == "trace=abc"


class TestVerifyWebhookSecret:
    def test_no_secret_allows_all(self):
        assert verify_webhook_secret(None, None) is True
        assert verify_webhook_secret("", "anything") is True

    def test_match(self):
        assert verify_webhook_secret("s3cret", "s3cret") is True

    def test_mismatch(self):
        assert verify_webhook_secret("s3cret", "wrong") is False

    def test_missing_header(self):
        assert verify_webhook_secret("s3cret", None) is False


class TestStartCronScheduler:
    def test_returns_none_with_no_cron_triggers(self):
        async def _do() -> None:
            result = await start_cron_scheduler([], lambda t: asyncio.sleep(0))
            assert result is None

        asyncio.run(_do())

    def test_returns_none_with_only_webhook_triggers(self):
        webhook_only = [
            TriggerDefinition(
                name="w",
                type="webhook",
                prompt="x",
                path="/w",
            )
        ]

        async def _do() -> None:
            result = await start_cron_scheduler(webhook_only, lambda t: asyncio.sleep(0))
            assert result is None

        asyncio.run(_do())

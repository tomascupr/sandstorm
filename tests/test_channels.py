"""Tests for the per-channel overlay resolver."""

from __future__ import annotations

import logging

from sandstorm.channels import resolve_channel_config, validate_channels_section


class TestResolveChannelConfig:
    def test_no_config_returns_none(self):
        assert resolve_channel_config(None, "C1") is None
        assert resolve_channel_config({}, "C1") is None

    def test_no_channel_id_returns_none(self):
        config = {"channels": {"C1": {"starter": "support-triage"}}}
        assert resolve_channel_config(config, None) is None

    def test_channels_not_dict_returns_none(self):
        assert resolve_channel_config({"channels": "not-a-dict"}, "C1") is None

    def test_unconfigured_channel_returns_none(self):
        config = {"channels": {"C1": {"starter": "support-triage"}}}
        assert resolve_channel_config(config, "C_OTHER") is None

    def test_filters_unknown_keys(self):
        config = {
            "channels": {
                "C1": {
                    "starter": "support-triage",
                    "model": "sonnet",
                    "bogus": "should-be-dropped",
                }
            }
        }
        out = resolve_channel_config(config, "C1")
        assert out == {"starter": "support-triage", "model": "sonnet"}

    def test_allowed_tools_passthrough(self):
        config = {
            "channels": {
                "C1": {
                    "allowed_tools": ["Read", "Bash"],
                }
            }
        }
        out = resolve_channel_config(config, "C1")
        assert out == {"allowed_tools": ["Read", "Bash"]}

    def test_empty_overlay_after_filter_returns_none(self):
        config = {"channels": {"C1": {"bogus": "x"}}}
        assert resolve_channel_config(config, "C1") is None


class TestValidateChannelsSection:
    def test_non_dict_returns_none(self, caplog):
        with caplog.at_level(logging.WARNING, logger="sandstorm.channels"):
            assert validate_channels_section("not a dict") is None
        assert any("must be a dict" in rec.getMessage() for rec in caplog.records)

    def test_valid_overlays_kept(self):
        raw = {
            "C1": {"starter": "support-triage", "model": "sonnet"},
            "C2": {"allowed_tools": ["Read"]},
        }
        out = validate_channels_section(raw)
        assert out == raw

    def test_invalid_starter_type_drops_overlay(self, caplog):
        raw = {"C1": {"starter": 42}}
        with caplog.at_level(logging.WARNING, logger="sandstorm.channels"):
            assert validate_channels_section(raw) is None
        assert any("starter must be a string" in rec.getMessage() for rec in caplog.records)

    def test_invalid_model_type_drops_overlay(self, caplog):
        raw = {"C1": {"model": {"not": "a string"}}}
        with caplog.at_level(logging.WARNING, logger="sandstorm.channels"):
            assert validate_channels_section(raw) is None

    def test_invalid_allowed_tools_drops_overlay(self, caplog):
        raw = {"C1": {"allowed_tools": ["ok", 42]}}
        with caplog.at_level(logging.WARNING, logger="sandstorm.channels"):
            assert validate_channels_section(raw) is None

    def test_non_string_channel_key_dropped(self, caplog):
        raw = {42: {"starter": "x"}, "C1": {"starter": "ok"}}
        with caplog.at_level(logging.WARNING, logger="sandstorm.channels"):
            out = validate_channels_section(raw)
        assert out == {"C1": {"starter": "ok"}}

    def test_empty_result_returns_none(self):
        assert validate_channels_section({}) is None

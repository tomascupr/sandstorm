"""Tests for the user-scoped MemoryStore and its injection into agent config."""

import json

import pytest

import sandstorm.config as config_mod
from sandstorm.config import _build_agent_config
from sandstorm.memory import MemoryStore
from sandstorm.models import QueryRequest


class TestRememberAndList:
    def test_remember_returns_memory(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        m = store.remember("T1", "U1", "favourite db is postgres")
        assert m.team_id == "T1"
        assert m.user_id == "U1"
        assert m.text == "favourite db is postgres"
        assert m.deleted is False

    def test_list_returns_live_memories(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "likes oat milk")
        store.remember("T1", "U1", "ships to berlin")
        memories = store.list("T1", "U1")
        assert {m.text for m in memories} == {"likes oat milk", "ships to berlin"}

    def test_list_is_scoped_by_user(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "user-one secret")
        store.remember("T1", "U2", "user-two secret")
        assert [m.text for m in store.list("T1", "U1")] == ["user-one secret"]
        assert [m.text for m in store.list("T1", "U2")] == ["user-two secret"]

    def test_list_is_scoped_by_team(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "team-one secret")
        store.remember("T2", "U1", "team-two secret")
        assert [m.text for m in store.list("T1", "U1")] == ["team-one secret"]
        assert [m.text for m in store.list("T2", "U1")] == ["team-two secret"]

    def test_local_default_team_when_none(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember(None, None, "cli preference")
        memories = store.list(None, None)
        assert [m.text for m in memories] == ["cli preference"]


class TestForget:
    def test_forget_substring_tombstones(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "favourite db is postgres")
        store.remember("T1", "U1", "favourite lang is python")
        deleted = store.forget("T1", "U1", "postgres")
        assert deleted == 1
        assert [m.text for m in store.list("T1", "U1")] == ["favourite lang is python"]

    def test_forget_is_case_insensitive(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "likes OAT milk")
        assert store.forget("T1", "U1", "oat") == 1
        assert store.list("T1", "U1") == []

    def test_forget_scoped_to_user(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "my api_key is hidden")
        store.remember("T1", "U2", "my api_key is shared")
        deleted = store.forget("T1", "U1", "api_key")
        assert deleted == 1
        assert [m.text for m in store.list("T1", "U2")] == ["my api_key is shared"]

    def test_forget_nonexistent_returns_zero(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "fact one")
        assert store.forget("T1", "U1", "not there") == 0


class TestAsPromptPrefix:
    def test_empty_store_returns_empty_string(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        assert store.as_prompt_prefix("T1", "U1") == ""

    def test_bullets_include_all_live_memories(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "based in berlin")
        store.remember("T1", "U1", "prefers typescript")
        prefix = store.as_prompt_prefix("T1", "U1")
        assert "User memory" in prefix
        assert "- based in berlin" in prefix
        assert "- prefers typescript" in prefix
        assert prefix.endswith("\n\n")  # safe to concatenate

    def test_deleted_memories_excluded_from_prefix(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "U1", "fact one")
        store.remember("T1", "U1", "fact two")
        store.forget("T1", "U1", "two")
        prefix = store.as_prompt_prefix("T1", "U1")
        assert "fact one" in prefix
        assert "fact two" not in prefix


class TestJsonlPersistence:
    def test_reload_restores_live_memories(self, tmp_path):
        path = tmp_path / "m.jsonl"
        s1 = MemoryStore(path=path)
        s1.remember("T1", "U1", "kept")
        s2 = MemoryStore(path=path)
        assert [m.text for m in s2.list("T1", "U1")] == ["kept"]

    def test_tombstone_survives_reload(self, tmp_path):
        path = tmp_path / "m.jsonl"
        s1 = MemoryStore(path=path)
        s1.remember("T1", "U1", "forget me")
        s1.forget("T1", "U1", "forget")
        s2 = MemoryStore(path=path)
        assert s2.list("T1", "U1") == []

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "m.jsonl"
        valid_row = {
            "id": "m1",
            "team_id": "T1",
            "user_id": "U1",
            "text": "valid",
            "created_at": "2025-01-01T00:00:00+00:00",
            "deleted": False,
        }
        path.write_text(
            json.dumps(valid_row) + "\n" + "not valid json\n" + '{"incomplete": true}\n' + "\n"
        )
        store = MemoryStore(path=path)
        assert [m.text for m in store.list("T1", "U1")] == ["valid"]


class TestThreeLevelScope:
    def test_team_scope_shared_across_users(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "UA", "company holiday Monday", scope="team")

        # Different user in the same team sees the team fact
        seen_by_other = store.list("T1", "UB", scope="team")
        assert [m.text for m in seen_by_other] == ["company holiday Monday"]

        # Different team does NOT see it
        other_team = store.list("T2", "UA", scope="team")
        assert other_team == []

    def test_channel_scope_isolation(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "UA", "support rotation", scope="channel", channel_id="C_SUPPORT")
        store.remember("T1", "UA", "eng rotation", scope="channel", channel_id="C_ENG")

        support_view = store.list("T1", "UB", scope="channel", channel_id="C_SUPPORT")
        assert [m.text for m in support_view] == ["support rotation"]
        # Different channel, same user: no crossover
        eng_view = store.list("T1", "UB", scope="channel", channel_id="C_ENG")
        assert [m.text for m in eng_view] == ["eng rotation"]

    def test_channel_scope_requires_channel_id(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        with pytest.raises(ValueError, match="channel_id"):
            store.remember("T1", "U1", "x", scope="channel")

    def test_combined_prefix_orders_team_channel_user(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "UA", "user fact", scope="user")
        store.remember("T1", "UA", "channel fact", scope="channel", channel_id="C1")
        store.remember("T1", "UA", "team fact", scope="team")
        prefix = store.as_prompt_prefix("T1", "UA", channel_id="C1")
        assert prefix.index("team fact") < prefix.index("channel fact")
        assert prefix.index("channel fact") < prefix.index("user fact")

    def test_list_combined_view_without_channel_id_skips_channel(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "UA", "team fact", scope="team")
        store.remember("T1", "UA", "channel fact", scope="channel", channel_id="C1")
        store.remember("T1", "UA", "user fact", scope="user")
        # No channel_id = no channel memories visible
        seen = store.list("T1", "UA")
        assert "channel fact" not in [m.text for m in seen]
        assert {m.text for m in seen} == {"team fact", "user fact"}

    def test_forget_scoped_filter(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "UA", "shared holiday", scope="team")
        store.remember("T1", "UA", "my preference holiday", scope="user")
        # Forget only user-scoped
        deleted = store.forget("T1", "UA", "holiday", scope="user")
        assert deleted == 1
        team_still = [m.text for m in store.list("T1", "UA", scope="team")]
        assert team_still == ["shared holiday"]

    def test_forget_by_id_requires_ownership(self, tmp_path):
        """UI callers that receive a memory_id from a payload must only be
        able to tombstone their own memories. Used by the App Home Forget
        button to prevent cross-user deletion."""
        store = MemoryStore(path=tmp_path / "m.jsonl")
        alice = store.remember("T1", "UA", "alice fact", scope="user")
        bob = store.remember("T1", "UB", "bob fact", scope="user")

        # Alice can delete her own
        assert store.forget_by_id(alice.id, team_id="T1", user_id="UA") is True
        assert alice.deleted is True

        # Alice cannot delete Bob's by guessing his id
        assert store.forget_by_id(bob.id, team_id="T1", user_id="UA") is False
        assert bob.deleted is False

        # Different tenant cannot delete either
        assert store.forget_by_id(bob.id, team_id="T2", user_id="UB") is False
        assert bob.deleted is False

    def test_forget_team_requires_author_match(self, tmp_path):
        """Team memories are shared, but only the original author can delete.
        This keeps one tenant member from wiping another's workspace-wide
        knowledge via `/forget team <text>`."""
        store = MemoryStore(path=tmp_path / "m.jsonl")
        store.remember("T1", "UA", "alice team fact", scope="team")
        store.remember("T1", "UB", "bob team fact", scope="team")

        # Alice cannot delete Bob's team memory by matching text substring
        deleted = store.forget("T1", "UA", "bob", scope="team")
        assert deleted == 0
        still_visible = {m.text for m in store.list("T1", "UB", scope="team")}
        assert "bob team fact" in still_visible

        # Alice CAN delete her own team memory
        deleted = store.forget("T1", "UA", "alice", scope="team")
        assert deleted == 1

    def test_forget_by_id_team_scope_requires_author(self, tmp_path):
        """Team-scoped forget_by_id must also gate by author, so a forged
        memory_id from a Block Kit payload can't cross-delete."""
        store = MemoryStore(path=tmp_path / "m.jsonl")
        bob = store.remember("T1", "UB", "bob team fact", scope="team")
        assert store.forget_by_id(bob.id, team_id="T1", user_id="UA", scope="team") is False
        assert bob.deleted is False
        # But Bob himself can
        assert store.forget_by_id(bob.id, team_id="T1", user_id="UB", scope="team") is True
        assert bob.deleted is True

    def test_back_compat_loads_pre_v091_rows(self, tmp_path):
        """Old JSONL rows without scope/channel_id default to user scope."""
        path = tmp_path / "m.jsonl"
        pre_v091 = {
            "id": "abc",
            "team_id": "T1",
            "user_id": "UA",
            "text": "old school",
            "created_at": "2026-01-01T00:00:00+00:00",
            "deleted": False,
        }
        import json as _json

        path.write_text(_json.dumps(pre_v091) + "\n")

        store = MemoryStore(path=path)
        seen = store.list("T1", "UA", scope="user")
        assert [m.text for m in seen] == ["old school"]
        assert seen[0].scope == "user"
        assert seen[0].channel_id is None


class TestDequeEviction:
    def test_maxlen_evicts_oldest(self, tmp_path):
        store = MemoryStore(path=tmp_path / "m.jsonl", maxlen=3)
        for i in range(5):
            store.remember("T1", "U1", f"m{i}")
        memories = [m.text for m in store.list("T1", "U1")]
        # Deque holds 3 latest; earlier entries evicted without tombstone
        assert "m0" not in memories
        assert "m1" not in memories
        assert memories == ["m2", "m3", "m4"]

    def test_tombstone_for_evicted_entry_does_not_reenter(self, tmp_path):
        """Regression: a tombstone written for a memory that was later evicted
        from the deque must not re-enter storage on reload. Before the fix
        the tombstone-record path appended the deleted record to the deque,
        consuming a slot with a dead entry."""
        path = tmp_path / "m.jsonl"
        s1 = MemoryStore(path=path, maxlen=3)
        # Create then delete the first entry (writes a tombstone line)
        s1.remember("T1", "U1", "delete-me")
        s1.forget("T1", "U1", "delete-me")
        # Push enough new entries to evict the tombstone's id from the deque
        for i in range(5):
            s1.remember("T1", "U1", f"live-{i}")

        s2 = MemoryStore(path=path, maxlen=3)
        live = [m.text for m in s2.list("T1", "U1")]
        # All three slots hold real live entries; tombstone did not sneak in
        assert len(s2._memories) == 3
        assert "delete-me" not in live
        assert all(t.startswith("live-") for t in live)


@pytest.fixture()
def _api_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setenv("E2B_API_KEY", "e2b-test-key")


@pytest.fixture(autouse=True)
def _reset_loaded_dotenv(monkeypatch):
    monkeypatch.setattr(config_mod, "_LOADED_DOTENV_VALUES", {})
    monkeypatch.setattr(config_mod, "_env_mtime", 0.0)


def _patched_store(monkeypatch, tmp_path) -> MemoryStore:
    """Redirect the module-level memory_store used by config._build_agent_config
    to a temp-path store so tests stay isolated from real `.sandstorm/`."""
    store = MemoryStore(path=tmp_path / "m.jsonl")
    monkeypatch.setattr(config_mod, "memory_store", store)
    return store


class TestMemoryInjection:
    def test_no_memory_no_prefix(self, monkeypatch, tmp_path, _api_keys):
        _patched_store(monkeypatch, tmp_path)
        req = QueryRequest(prompt="hi", team_id="T1", user_id="U1")
        config, _ = _build_agent_config(req, {}, {})
        # Without any memories or env_append, system_prompt stays unset
        assert config.get("system_prompt") is None

    def test_memory_injected_as_append(self, monkeypatch, tmp_path, _api_keys):
        store = _patched_store(monkeypatch, tmp_path)
        store.remember("T1", "U1", "favourite db is postgres")
        req = QueryRequest(prompt="hi", team_id="T1", user_id="U1")
        config, _ = _build_agent_config(req, {}, {})
        sys_prompt = config["system_prompt"]
        assert isinstance(sys_prompt, str)
        assert "User memory" in sys_prompt
        assert "favourite db is postgres" in sys_prompt

    def test_memory_prepended_to_existing_append(self, monkeypatch, tmp_path, _api_keys):
        store = _patched_store(monkeypatch, tmp_path)
        store.remember("T1", "U1", "ships to berlin")
        req = QueryRequest(prompt="hi", team_id="T1", user_id="U1")
        config, _ = _build_agent_config(
            req,
            {"system_prompt_append": "Follow project conventions."},
            {},
        )
        sys_prompt = config["system_prompt"]
        # Memory comes first, then the config append, so project conventions
        # always land closest to the prompt (highest-precedence instruction)
        conv = sys_prompt.index("Follow project conventions.")
        assert sys_prompt.index("ships to berlin") < conv

    def test_memory_scoped_to_user(self, monkeypatch, tmp_path, _api_keys):
        store = _patched_store(monkeypatch, tmp_path)
        store.remember("T1", "U1", "user-one preference")
        store.remember("T1", "U2", "user-two preference")
        req = QueryRequest(prompt="hi", team_id="T1", user_id="U1")
        config, _ = _build_agent_config(req, {}, {})
        assert "user-one preference" in config["system_prompt"]
        assert "user-two preference" not in (config["system_prompt"] or "")

    def test_no_team_context_uses_local_scope(self, monkeypatch, tmp_path, _api_keys):
        store = _patched_store(monkeypatch, tmp_path)
        store.remember(None, None, "local-only fact")
        req = QueryRequest(prompt="hi")  # no team_id / user_id
        config, _ = _build_agent_config(req, {}, {})
        assert "local-only fact" in config["system_prompt"]

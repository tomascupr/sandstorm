"""Tests for the user-scoped MemoryStore."""

import json

from sandstorm.memory import MemoryStore


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

"""Тести для Memory System."""

from __future__ import annotations

import pytest

from posipaka.memory.manager import MemoryManager


@pytest.fixture
async def memory(tmp_path):
    mm = MemoryManager(
        sqlite_path=tmp_path / "test.db",
        chroma_path=tmp_path / "chroma",
        memory_md_path=tmp_path / "MEMORY.md",
        chroma_enabled=False,  # Disable chroma for unit tests
    )
    await mm.init()
    yield mm
    await mm.close()


@pytest.mark.asyncio
async def test_add_and_retrieve(memory):
    """Додати та отримати повідомлення."""
    await memory.add("s1", {"role": "user", "content": "Hello"})
    await memory.add("s1", {"role": "assistant", "content": "Hi there!"})

    messages = await memory.get_recent("s1")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["content"] == "Hi there!"


@pytest.mark.asyncio
async def test_session_isolation(memory):
    """Повідомлення різних сесій не змішуються."""
    await memory.add("s1", {"role": "user", "content": "Session 1"})
    await memory.add("s2", {"role": "user", "content": "Session 2"})

    msgs_s1 = await memory.get_recent("s1")
    msgs_s2 = await memory.get_recent("s2")

    assert len(msgs_s1) == 1
    assert msgs_s1[0]["content"] == "Session 1"
    assert len(msgs_s2) == 1
    assert msgs_s2[0]["content"] == "Session 2"


@pytest.mark.asyncio
async def test_clear_session(memory):
    """Очищення сесії видаляє всі повідомлення."""
    await memory.add("s1", {"role": "user", "content": "msg1"})
    await memory.add("s1", {"role": "user", "content": "msg2"})
    await memory.flush()  # дочекатись фонових записів

    await memory.clear_session("s1")

    messages = await memory.get_recent("s1")
    assert len(messages) == 0


@pytest.mark.asyncio
async def test_ram_limit(tmp_path):
    """RAM обрізається до short_term_limit."""
    mm = MemoryManager(
        sqlite_path=tmp_path / "test.db",
        chroma_path=tmp_path / "chroma",
        memory_md_path=tmp_path / "MEMORY.md",
        short_term_limit=5,
        chroma_enabled=False,
    )
    await mm.init()

    for i in range(10):
        await mm.add("s1", {"role": "user", "content": f"msg {i}"})

    # RAM should have only last 5
    assert len(mm._ram["s1"]) == 5
    assert mm._ram["s1"][0]["content"] == "msg 5"

    await mm.close()


@pytest.mark.asyncio
async def test_memory_md(memory):
    """Читання та запис MEMORY.md."""
    memory.update_memory_md("# Test facts\n- Fact 1\n")
    content = memory.get_memory_md()
    assert "Fact 1" in content


@pytest.mark.asyncio
async def test_stats(memory):
    """Статистика сесії."""
    await memory.add("s1", {"role": "user", "content": "hello"})
    await memory.flush()  # дочекатись фонових записів
    stats = await memory.get_stats("s1")
    assert stats["ram_messages"] == 1
    assert stats["db_messages"] == 1


@pytest.mark.asyncio
async def test_fact_extraction(memory):
    """Факти витягуються при ключових словах."""
    await memory.maybe_extract_facts("s1", "Запам'ятай що я люблю каву")
    facts = await memory.get_facts("s1")
    assert len(facts) == 1
    assert "каву" in facts[0]["fact"]

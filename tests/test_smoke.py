"""Offline smoke test — no network, no real API key. Run: python tests/test_smoke.py"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import budget
import memory

# Redirect all memory writes into a temp dir for the test
tmp = Path(tempfile.mkdtemp())
memory.MEMORY_DIR = tmp
memory.PROFILE_PATH = tmp / "profile.md"
memory.SESSIONS_DIR = tmp / "sessions"
budget.USAGE_DIR = tmp / "usage"

import bot


def usage(inp=1000, out=200, cw=0, cr=0):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_creation_input_tokens=cw, cache_read_input_tokens=cr,
    )


def test_memory():
    memory.PROFILE_PATH.write_text("# Who I am\n\n## Facts the agent has learned\n")
    memory.append_fact("Meditates every morning at 6am")
    assert "Meditates every morning at 6am" in memory.load_profile()
    memory.append_session("user", "hello")
    memory.append_session("agent", "hi there")
    recent = memory.recent_sessions()
    assert "hello" in recent and "hi there" in recent
    print("ok memory")


def test_budget():
    c = budget.cost_of("claude-haiku-4-5", usage(inp=1_000_000, out=0))
    assert abs(c - 1.00) < 1e-9, c
    c = budget.cost_of("claude-sonnet-5", usage(inp=0, out=1_000_000))
    assert abs(c - 15.00) < 1e-9, c
    c = budget.cost_of("claude-haiku-4-5", usage(inp=0, out=0, cr=1_000_000))
    assert abs(c - 0.10) < 1e-9, c
    budget.add_spend(0.25)
    budget.add_spend(0.30)
    assert budget.today_spend() >= 0.55
    assert budget.over_daily_cap()  # default cap 0.50
    print("ok budget")


def test_routing():
    assert bot.pick_model("what's the weather") == bot.HAIKU
    assert bot.pick_model("help me plan my week") == bot.SONNET
    assert bot.pick_model("x" * 800) == bot.SONNET
    print("ok routing")


def test_tool_loop():
    tool_block = SimpleNamespace(
        type="tool_use", name="remember_fact", id="toolu_1",
        input={"fact": "Prefers tea over coffee"},
    )
    first = SimpleNamespace(stop_reason="tool_use", content=[tool_block], usage=usage())
    text_block = SimpleNamespace(type="text", text="Noted — tea it is.")
    second = SimpleNamespace(stop_reason="end_turn", content=[text_block], usage=usage())
    with patch.object(bot, "client") as mock_client:
        mock_client.messages.create = MagicMock(side_effect=[first, second])
        reply, cost, msgs = bot.run_claude(bot.HAIKU, [{"role": "user", "content": "remember I prefer tea"}])
    assert reply == "Noted — tea it is."
    assert "Prefers tea over coffee" in memory.load_profile()
    assert cost > 0
    assert mock_client.messages.create.call_count == 2
    # history: user, assistant(tool_use), user(tool_result), assistant(text)
    assert len(msgs) == 4
    print("ok tool loop")


def test_rate_limit():
    for _ in range(bot.RATE_LIMIT[0]):
        assert not bot.rate_limited(42)
    assert bot.rate_limited(42)
    print("ok rate limit")


if __name__ == "__main__":
    try:
        test_memory()
        test_budget()
        test_routing()
        test_tool_loop()
        test_rate_limit()
        print("ALL TESTS PASSED")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

"""Tests for AI session log reader."""

from __future__ import annotations

import json
from pathlib import Path

from src.utils.ai_session_reader import (
    SessionEntry,
    SessionSummary,
    _parse_claude_code,
    _parse_codex,
    discover_sessions,
    format_cleaned,
    format_plan,
    format_summary,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _write_claude_session(path: Path, messages: list[dict]) -> None:
    """Write a minimal Claude Code session JSONL."""
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def _write_codex_session(path: Path, records: list[dict]) -> None:
    """Write a minimal Codex session JSONL."""
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── Claude Code parser ───────────────────────────────────────────────


def test_parse_claude_code_user_and_assistant(tmp_path: Path) -> None:
    session_file = tmp_path / "test-session.jsonl"
    _write_claude_session(session_file, [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-07-05T10:00:00Z"},
        {
            "type": "user",
            "timestamp": "2026-07-05T10:00:01Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "Fix the bug"}]},
        },
        {
            "type": "assistant",
            "timestamp": "2026-07-05T10:00:02Z",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "I'll fix it now."},
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status"}},
            ]},
        },
    ])

    summary = _parse_claude_code(session_file)
    assert summary.source == "claude-code"
    assert len(summary.user_questions) == 1
    assert summary.user_questions[0].summary == "Fix the bug"
    assert len(summary.tool_calls) == 1
    assert summary.tool_calls[0].tool_name == "Bash"


def test_parse_claude_code_skips_system_messages(tmp_path: Path) -> None:
    session_file = tmp_path / "test.jsonl"
    _write_claude_session(session_file, [
        {
            "type": "user",
            "timestamp": "2026-07-05T10:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "<system>You are helpful</system>"}]},
        },
        {
            "type": "user",
            "timestamp": "2026-07-05T10:00:01Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "Real question"}]},
        },
    ])

    summary = _parse_claude_code(session_file)
    # The < system message should be skipped
    user_qs = summary.user_questions
    assert len(user_qs) == 1
    assert user_qs[0].summary == "Real question"


# ── Codex parser ─────────────────────────────────────────────────────


def test_parse_codex_session(tmp_path: Path) -> None:
    session_file = tmp_path / "rollout-test.jsonl"
    _write_codex_session(session_file, [
        {"type": "session_meta", "timestamp": "2026-07-05T10:00:00Z", "payload": {"id": "test123", "timestamp": "2026-07-05T10:00:00Z"}},
        {
            "type": "response_item",
            "timestamp": "2026-07-05T10:00:01Z",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the app"}]},
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-05T10:00:02Z",
            "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I'll fix the routing."}]},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-07-05T10:00:03Z",
            "payload": {"message": {"role": "assistant", "content": "Running tests now."}},
        },
    ])

    summary = _parse_codex(session_file)
    assert summary.source == "codex"
    assert summary.started == "2026-07-05T10:00:00Z"
    assert len(summary.user_questions) == 1
    assert summary.user_questions[0].summary == "Fix the app"
    assert len(summary.ai_decisions) >= 1


def test_parse_codex_skips_developer_messages(tmp_path: Path) -> None:
    session_file = tmp_path / "rollout-test.jsonl"
    _write_codex_session(session_file, [
        {"type": "session_meta", "timestamp": "2026-07-05T10:00:00Z", "payload": {"id": "x", "timestamp": "2026-07-05T10:00:00Z"}},
        {
            "type": "response_item",
            "timestamp": "2026-07-05T10:00:01Z",
            "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "You are a helpful assistant"}]},
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-05T10:00:02Z",
            "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello"}]},
        },
    ])

    summary = _parse_codex(session_file)
    assert len(summary.user_questions) == 1
    assert summary.user_questions[0].summary == "Hello"


# ── Formatters ───────────────────────────────────────────────────────


def test_format_summary() -> None:
    s = SessionSummary(
        session_id="test",
        source="codex",
        started="2026-07-05T10:00:00Z",
        entries=[
            SessionEntry(ts="", role="user", summary="Fix the bug"),
            SessionEntry(ts="", role="assistant", summary="I'll fix it"),
            SessionEntry(ts="", role="assistant", summary="git status", tool_name="Bash"),
        ],
    )
    result = format_summary(s)
    assert "codex" in result
    assert "1Q" in result
    assert "1D" in result
    assert "1T" in result
    assert "Fix the bug" in result


def test_format_plan_identifies_errors() -> None:
    s = SessionSummary(
        session_id="test",
        source="claude-code",
        started="2026-07-05T10:00:00Z",
        entries=[
            SessionEntry(ts="", role="user", summary="Why does it fail?"),
            SessionEntry(ts="", role="tool_result", summary="Exit code 1", is_error=True),
        ],
    )
    plan = format_plan([s])
    assert "Errors Encountered" in plan
    assert "Exit code 1" in plan
    assert "Pain Points" in plan


def test_format_plan_clean_session() -> None:
    s = SessionSummary(
        session_id="test",
        source="codex",
        started="2026-07-05T10:00:00Z",
        entries=[
            SessionEntry(ts="", role="user", summary="Add a button"),
            SessionEntry(ts="", role="assistant", summary="Done"),
        ],
    )
    plan = format_plan([s])
    assert "No significant issues" in plan


def test_format_cleaned() -> None:
    s = SessionSummary(
        session_id="test-id",
        source="codex",
        started="2026-07-05T10:00:00Z",
        entries=[
            SessionEntry(ts="", role="user", summary="Hello"),
            SessionEntry(ts="", role="assistant", summary="Hi there"),
        ],
    )
    output = format_cleaned(s)
    assert "test-id" in output
    assert "codex" in output
    assert "Hello" in output
    assert "Hi there" in output

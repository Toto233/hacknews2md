"""Read and clean AI session logs from Codex and Claude Code.

Extracts the useful signal from raw session JSONL files:
- User questions and requests
- AI decisions and reasoning
- Commands executed and their outcomes
- Errors encountered
- Files modified

Usage::

    python -m src.utils.ai_session_reader                    # recent sessions
    python -m src.utils.ai_session_reader --last 3           # last 3 sessions
    python -m src.utils.ai_session_reader --source codex     # Codex only
    python -m src.utils.ai_session_reader --summary          # one-line per session
    python -m src.utils.ai_session_reader --plan             # improvement plan
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────

_CLAUDE_DIR = Path.home() / ".claude" / "projects"
_CODEX_DIR = Path.home() / ".codex" / "archived_sessions"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_hash() -> str | None:
    """Find the Claude Code project hash for the current working directory.

    Claude Code encodes ``D:\\python\\hacknews2md_re`` as
    ``d--python-hacknews2md-re``: colon→dash, backslash→dash,
    underscore→dash, then lowercase.
    """
    cwd = str(Path.cwd().resolve())

    encoded = cwd.replace(":", "-").replace("\\", "-").replace("/", "-").replace("_", "-").lower()

    if (_CLAUDE_DIR / encoded).exists():
        return encoded

    # Fallback: scan
    for p in _CLAUDE_DIR.iterdir():
        if p.is_dir() and p.name.lower() == encoded:
            return p.name

    return None


# ── Data model ───────────────────────────────────────────────────────


@dataclass
class SessionEntry:
    """A single cleaned entry from a session log."""
    ts: str
    role: str          # user | assistant | tool_result | system
    summary: str       # cleaned one-line summary
    tool_name: str | None = None
    tool_input: str | None = None
    is_error: bool = False


@dataclass
class SessionSummary:
    """A cleaned summary of an entire session."""
    session_id: str
    source: str        # codex | claude-code
    started: str
    entries: list[SessionEntry] = field(default_factory=list)

    @property
    def user_questions(self) -> list[SessionEntry]:
        return [e for e in self.entries if e.role == "user"]

    @property
    def ai_decisions(self) -> list[SessionEntry]:
        return [e for e in self.entries if e.role == "assistant" and not e.tool_name]

    @property
    def tool_calls(self) -> list[SessionEntry]:
        return [e for e in self.entries if e.tool_name]

    @property
    def errors(self) -> list[SessionEntry]:
        return [e for e in self.entries if e.is_error]


# ── Claude Code parser ───────────────────────────────────────────────

def _parse_claude_code(path: Path) -> SessionSummary:
    """Parse a Claude Code session JSONL file."""
    entries: list[SessionEntry] = []
    started = ""
    session_id = path.stem

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        dtype = d.get("type", "")
        if dtype == "queue-operation":
            ts = d.get("timestamp", "")
            if not started and ts:
                started = ts
            continue

        if dtype not in ("user", "assistant"):
            continue

        msg = d.get("message", {})
        content = msg.get("content", "")
        ts = d.get("timestamp", "")

        if not started and ts:
            started = ts

        if isinstance(content, str) and content.strip():
            entries.append(SessionEntry(ts=ts, role=dtype, summary=content[:200]))
            continue

        if not isinstance(content, list):
            continue

        for block in content:
            btype = block.get("type", "")

            if btype == "text":
                text = block.get("text", "").strip()
                if text and not text.startswith("<"):
                    entries.append(SessionEntry(ts=ts, role=dtype, summary=text[:200]))

            elif btype == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                summary = name
                tool_input = None

                if name == "Bash":
                    summary = f"Bash: {inp.get('command', '')[:100]}"
                    tool_input = inp.get("command", "")
                elif name in ("Edit", "Write", "Read"):
                    summary = f"{name}: {inp.get('file_path', '')}"
                    tool_input = inp.get("file_path", "")
                elif name == "Agent":
                    summary = f"Agent: {inp.get('description', inp.get('prompt', ''))[:80]}"
                else:
                    summary = f"{name}: {json.dumps(inp, ensure_ascii=False)[:80]}"

                entries.append(SessionEntry(
                    ts=ts, role="assistant", summary=summary,
                    tool_name=name, tool_input=tool_input,
                ))

            elif btype == "tool_result":
                result_content = block.get("content", "")
                is_error = block.get("is_error", False)
                if isinstance(result_content, list):
                    texts = [r.get("text", "") for r in result_content if r.get("type") == "text"]
                    result_content = " ".join(texts)
                entries.append(SessionEntry(
                    ts=ts, role="tool_result",
                    summary=str(result_content)[:150],
                    is_error=is_error,
                ))

    return SessionSummary(
        session_id=session_id,
        source="claude-code",
        started=started,
        entries=entries,
    )


# ── Codex parser ─────────────────────────────────────────────────────

def _parse_codex(path: Path) -> SessionSummary:
    """Parse a Codex session JSONL file."""
    entries: list[SessionEntry] = []
    started = ""
    session_id = path.stem  # e.g. rollout-2026-03-07T11-24-41-...

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        dtype = d.get("type", "")

        if dtype == "session_meta":
            payload = d.get("payload", {})
            started = payload.get("timestamp", d.get("timestamp", ""))
            continue

        if dtype == "response_item":
            payload = d.get("payload", {})
            role = payload.get("role", "")
            rtype = payload.get("type", "")
            ts = d.get("timestamp", "")

            # Skip system/developer messages
            if role in ("developer", "system"):
                continue

            content = payload.get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                btype = block.get("type", "")
                text = block.get("text", block.get("input_text", block.get("output_text", "")))
                if not text or not isinstance(text, str):
                    continue

                # Skip system context blocks
                if text.startswith("<") or text.startswith("# AGENTS.md") or "environment_context" in text:
                    continue

                text = text.strip()
                if not text:
                    continue

                if role == "user":
                    entries.append(SessionEntry(ts=ts, role="user", summary=text[:200]))
                elif role == "assistant":
                    entries.append(SessionEntry(ts=ts, role="assistant", summary=text[:200]))

        elif dtype == "event_msg":
            payload = d.get("payload", {})
            msg = payload.get("message", {})
            if not isinstance(msg, dict):
                # Payload itself might have text
                text = payload.get("text", "")
                if not text and isinstance(payload, str):
                    text = payload
                if text and isinstance(text, str):
                    text = text.strip()
                    if text and not text.startswith("{"):
                        entries.append(SessionEntry(
                            ts=d.get("timestamp", ""),
                            role="assistant",
                            summary=text[:200],
                        ))
                continue

            role = msg.get("role", "assistant")
            text = msg.get("content", "")
            if isinstance(text, str) and text.strip():
                entries.append(SessionEntry(
                    ts=d.get("timestamp", ""),
                    role=role,
                    summary=text.strip()[:200],
                ))

    return SessionSummary(
        session_id=session_id,
        source="codex",
        started=started,
        entries=entries,
    )


# ── Discovery ────────────────────────────────────────────────────────

def discover_sessions(
    source: str | None = None,
    limit: int = 5,
) -> list[tuple[str, Path]]:
    """Find recent session log files, newest first.

    Returns list of (source, path) tuples.
    """
    sessions: list[tuple[str, Path]] = []

    # Claude Code sessions
    if source in (None, "claude-code"):
        proj_hash = _project_hash()
        if proj_hash:
            proj_dir = _CLAUDE_DIR / proj_hash
            for f in proj_dir.glob("*.jsonl"):
                sessions.append(("claude-code", f))

    # Codex sessions
    if source in (None, "codex"):
        if _CODEX_DIR.exists():
            for f in _CODEX_DIR.glob("rollout-*.jsonl"):
                sessions.append(("codex", f))

    # Sort by modification time, newest first
    sessions.sort(key=lambda x: x[1].stat().st_mtime, reverse=True)
    return sessions[:limit]


def parse_session(source: str, path: Path) -> SessionSummary:
    """Parse a session log file based on its source."""
    if source == "codex":
        return _parse_codex(path)
    return _parse_claude_code(path)


# ── Output formatters ────────────────────────────────────────────────

def format_summary(session: SessionSummary) -> str:
    """One-line summary of a session."""
    n_user = len(session.user_questions)
    n_decisions = len(session.ai_decisions)
    n_tools = len(session.tool_calls)
    n_errors = len(session.errors)
    first_q = session.user_questions[0].summary[:60] if session.user_questions else "(no user input)"
    return (
        f"[{session.source}] {session.started[:10]} "
        f"({n_user}Q, {n_decisions}D, {n_tools}T, {n_errors}E) "
        f"{first_q}"
    )


def format_cleaned(session: SessionSummary) -> str:
    """Cleaned human-readable session transcript."""
    lines = [
        f"{'=' * 60}",
        f"Session: {session.session_id}",
        f"Source:  {session.source}",
        f"Started: {session.started}",
        f"{'=' * 60}",
    ]

    for entry in session.entries:
        prefix = {
            "user": "👤 USER",
            "assistant": "🤖 AI",
            "tool_result": "📋 RESULT",
        }.get(entry.role, f"❓ {entry.role.upper()}")

        if entry.tool_name:
            prefix = f"🔧 {entry.tool_name}"

        marker = " ❌" if entry.is_error else ""
        lines.append(f"{prefix}: {entry.summary}{marker}")

    return "\n".join(lines)


def format_plan(sessions: list[SessionSummary]) -> str:
    """Generate an improvement plan from recent sessions."""
    all_errors: list[tuple[str, SessionEntry]] = []
    all_decisions: list[tuple[str, SessionEntry]] = []
    user_pain_points: list[tuple[str, SessionEntry]] = []

    for s in sessions:
        for e in s.errors:
            all_errors.append((s.source, e))
        for e in s.ai_decisions:
            if any(kw in e.summary.lower() for kw in ("fix", "error", "问题", "修复", "bug", "fail", "issue")):
                all_decisions.append((s.source, e))
        for e in s.user_questions:
            if any(kw in e.summary.lower() for kw in ("问题", "bug", "fix", "fail", "为什么", "why", "error")):
                user_pain_points.append((s.source, e))

    lines = ["# AI Session Improvement Plan", ""]

    if user_pain_points:
        lines.append("## Recurring User Pain Points")
        for src, entry in user_pain_points:
            lines.append(f"- [{src}] {entry.summary}")
        lines.append("")

    if all_errors:
        lines.append("## Errors Encountered")
        for src, entry in all_errors:
            lines.append(f"- [{src}] {entry.summary}")
        lines.append("")

    if all_decisions:
        lines.append("## Key Decisions (problem-related)")
        for src, entry in all_decisions:
            lines.append(f"- [{src}] {entry.summary}")
        lines.append("")

    if not (user_pain_points or all_errors or all_decisions):
        lines.append("No significant issues found in recent sessions.")

    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read and clean AI session logs")
    parser.add_argument("--source", choices=["codex", "claude-code"], default=None)
    parser.add_argument("--last", type=int, default=3, help="Number of recent sessions")
    parser.add_argument("--summary", action="store_true", help="One-line per session")
    parser.add_argument("--plan", action="store_true", help="Generate improvement plan")
    parser.add_argument("--full", action="store_true", help="Full cleaned transcript")
    args = parser.parse_args(argv)

    session_files = discover_sessions(source=args.source, limit=args.last)
    if not session_files:
        print("No session logs found.")
        return 0

    sessions = [parse_session(src, path) for src, path in session_files]

    if args.plan:
        print(format_plan(sessions))
    elif args.full:
        for s in sessions:
            print(format_cleaned(s))
            print()
    else:
        for s in sessions:
            print(format_summary(s))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

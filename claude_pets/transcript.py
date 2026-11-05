"""Transcript tailing: context-window usage and (for hook-less sessions) activity.

Claude Code appends one JSON object per line to
``~/.claude/projects/<slug>/<session-id>.jsonl``.  :class:`TranscriptTailer`
follows those files incrementally and reduces each line to a tiny normalized
record::

    {"kind": "usage", "model": str, "context_tokens": int, "ts": float}
    {"kind": "tool_use", "tool": str, "input": dict, "id": str, "ts": float}
    {"kind": "tool_result", "id": str, "is_error": bool, "ts": float}
    {"kind": "user_prompt", "text": str, "ts": float}
    {"kind": "assistant_text", "ts": float}
    {"kind": "compact", "ts": float}

Sub-agent ("sidechain") lines and harness-injected user messages are skipped.
"""

from __future__ import annotations

import glob
import json
import os
import re
import time
from datetime import datetime

from . import paths
from .hook import trim_tool_input

TAIL_BYTES = 256 * 1024
MAX_READ = 4 * 1024 * 1024

DEFAULT_CONTEXT = 200_000
LARGE_CONTEXT = 1_000_000
#: Model families whose default window is the large one (heuristic; a session
#: whose usage exceeds 200k is switched to the large window regardless).
_LARGE_FAMILIES = ("fable", "mythos")

_SLUG_RE = re.compile(r"[^A-Za-z0-9]")
_MACHINE_PREFIXES = (
    "<task-notification", "<system-reminder", "<local-command", "<command-name",
    "<command-message", "[SYSTEM NOTIFICATION", "<bash-", "<user-prompt-submit-hook",
    "Caveat:", "[Request interrupted",
)


def context_limit_for(model, tokens: int = 0, previous: int = 0) -> int:
    """Best guess of the context window for ``model`` given observed usage."""
    name = str(model or "").lower()
    if previous >= LARGE_CONTEXT or tokens > DEFAULT_CONTEXT:
        return LARGE_CONTEXT
    if "[1m]" in name or name.endswith("-1m") or any(f in name for f in _LARGE_FAMILIES):
        return LARGE_CONTEXT
    return DEFAULT_CONTEXT


def project_slug(cwd: str) -> str:
    """Directory name Claude Code uses under ``~/.claude/projects`` for ``cwd``."""
    return _SLUG_RE.sub("-", cwd or "")


def transcript_path_for(session_id: str, cwd: str = "", projects_dir: str | None = None) -> str:
    """Path of a session's transcript ("" when it cannot be located yet)."""
    projects_dir = projects_dir or paths.CLAUDE_PROJECTS_DIR
    if not session_id:
        return ""
    if cwd:
        direct = os.path.join(projects_dir, project_slug(cwd), session_id + ".jsonl")
        if os.path.exists(direct):
            return direct
    matches = glob.glob(os.path.join(glob.escape(projects_dir), "*", glob.escape(session_id) + ".jsonl"))
    if matches:
        return max(matches, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    if cwd:
        return os.path.join(projects_dir, project_slug(cwd), session_id + ".jsonl")
    return ""


def _timestamp(record) -> float:
    stamp = record.get("timestamp")
    if isinstance(stamp, str) and stamp:
        try:
            return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time()


def _is_machine_text(text: str) -> bool:
    return text.lstrip().startswith(_MACHINE_PREFIXES)


def normalize_record(record) -> list[dict]:
    """Reduce one transcript line (already parsed) to normalized records."""
    if not isinstance(record, dict) or record.get("isSidechain") is True:
        return []
    kind = record.get("type")
    out = []
    if kind == "assistant":
        message = record.get("message")
        if not isinstance(message, dict):
            return []
        ts = _timestamp(record)
        model = message.get("model")
        usage = message.get("usage")
        if isinstance(usage, dict) and isinstance(model, str) and not model.startswith("<"):
            tokens = 0
            for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                value = usage.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    tokens += int(value)
            if tokens > 0:
                out.append({"kind": "usage", "model": model, "context_tokens": tokens, "ts": ts})
        content = message.get("content")
        if isinstance(content, list):
            said = False
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    out.append({
                        "kind": "tool_use",
                        "tool": str(block.get("name") or ""),
                        "input": trim_tool_input(block.get("input")),
                        "id": str(block.get("id") or ""),
                        "ts": ts,
                    })
                elif block.get("type") == "text" and not said:
                    said = True
                    out.append({"kind": "assistant_text", "ts": ts})
    elif kind == "user":
        if record.get("isMeta") is True:
            return []
        message = record.get("message")
        if not isinstance(message, dict):
            return []
        ts = _timestamp(record)
        if record.get("isCompactSummary") is True:
            return [{"kind": "compact", "ts": ts}]
        content = message.get("content")
        if isinstance(content, str):
            if content.strip() and not _is_machine_text(content):
                out.append({"kind": "user_prompt", "text": content[:2000], "ts": ts})
        elif isinstance(content, list):
            texts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    out.append({
                        "kind": "tool_result",
                        "id": str(block.get("tool_use_id") or ""),
                        "is_error": block.get("is_error") is True,
                        "ts": ts,
                    })
                elif block.get("type") == "text" and isinstance(block.get("text"), str):
                    texts.append(block["text"])
            text = "\n".join(texts)
            if text.strip() and not _is_machine_text(text):
                out.append({"kind": "user_prompt", "text": text[:2000], "ts": ts})
    elif kind == "system" and record.get("subtype") == "compact_boundary":
        out.append({"kind": "compact", "ts": _timestamp(record)})
    return out


class _File:
    __slots__ = ("path", "offset", "partial", "started", "inode")

    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self.partial = b""
        self.started = False
        self.inode = None


class TranscriptTailer:
    """Follows any number of transcript files; call :meth:`poll` on a timer."""

    def __init__(self, tail_bytes: int = TAIL_BYTES):
        self._tail_bytes = tail_bytes
        self._files: dict[str, _File] = {}

    def watch(self, session_id: str, path: str) -> None:
        if not session_id or not path:
            return
        current = self._files.get(session_id)
        if current is None or current.path != path:
            self._files[session_id] = _File(path)

    def unwatch(self, session_id: str) -> None:
        self._files.pop(session_id, None)

    def watching(self, session_id: str) -> str:
        entry = self._files.get(session_id)
        return entry.path if entry else ""

    def poll(self) -> dict:
        """``{session_id: (records, initial)}`` for every file that has news."""
        result = {}
        for session_id, entry in list(self._files.items()):
            try:
                found = self._poll_one(entry)
            except OSError:
                continue
            if found is not None:
                result[session_id] = found
        return result

    def _poll_one(self, entry: _File):
        try:
            stat = os.stat(entry.path)
        except OSError:
            return None  # not written yet; try again next time
        if entry.started and (stat.st_ino != entry.inode or stat.st_size < entry.offset):
            entry.started = False  # replaced or truncated: start over
            entry.offset = 0
            entry.partial = b""
        initial = not entry.started
        if not initial and stat.st_size == entry.offset:
            return None
        with open(entry.path, "rb") as handle:
            if initial:
                entry.inode = stat.st_ino
                entry.started = True
                start = max(0, stat.st_size - self._tail_bytes)
                handle.seek(start)
                data = handle.read(MAX_READ)
                entry.offset = start + len(data)
                if start > 0:
                    cut = data.find(b"\n")
                    data = data[cut + 1:] if cut >= 0 else b""
            else:
                handle.seek(entry.offset)
                data = handle.read(MAX_READ)
                entry.offset += len(data)
        data = entry.partial + data
        lines = data.split(b"\n")
        entry.partial = lines.pop()  # incomplete last line (or b"")
        if len(entry.partial) > MAX_READ:
            entry.partial = b""
        records = []
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            records.extend(normalize_record(parsed))
        if not records and not initial:
            return None
        return records, initial

"""Reader for Claude Code's session registry (``~/.claude/sessions/<pid>.json``).

Every running Claude Code process keeps one small JSON file there with its
session id, cwd, name and a coarse status (``busy`` / ``idle`` / ``shell`` /
``waiting``).  :class:`RegistryWatcher` returns the entries whose process is
really alive; it is cheap enough to poll every second or two.

The ``*.key`` files next to the JSON files are secrets and are never opened.
"""

from __future__ import annotations

import json
import os
import re

from . import paths

_ENTRY_RE = re.compile(r"^(\d+)\.json$")


def proc_start_time(pid: int) -> str:
    """Field 22 (starttime) of ``/proc/<pid>/stat``; "" when the process is gone."""
    try:
        with open("/proc/%d/stat" % pid) as handle:
            stat = handle.read()
        # comm (field 2) may contain spaces and parentheses: split after the last ")"
        return stat[stat.rindex(")") + 2:].split()[19]
    except (OSError, ValueError, IndexError):
        return ""


class RegistryWatcher:
    def __init__(self, sessions_dir: str | None = None, start_time=proc_start_time):
        self.sessions_dir = sessions_dir or paths.CLAUDE_SESSIONS_DIR
        self._start_time = start_time
        self._cache: dict[str, tuple[tuple[int, int], dict | None]] = {}

    def poll(self) -> list[dict]:
        """Entries of all live sessions (each a fresh dict, ``pid`` normalised to int)."""
        try:
            with os.scandir(self.sessions_dir) as it:
                names = [entry.name for entry in it]
        except OSError:
            self._cache.clear()
            return []
        seen = set()
        result = []
        for name in names:
            match = _ENTRY_RE.match(name)
            if not match:
                continue
            seen.add(name)
            data = self._load(name)
            if data is None:
                continue
            pid = data.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool):
                pid = int(match.group(1))
            started = self._start_time(pid)
            if not started:
                continue  # process is gone; a stale file was left behind
            expected = data.get("procStart")
            if expected not in (None, "") and str(expected) != started:
                continue  # the pid was reused by some other process
            entry = dict(data)
            entry["pid"] = pid
            result.append(entry)
        for name in list(self._cache):
            if name not in seen:
                del self._cache[name]
        return result

    def _load(self, name: str):
        path = os.path.join(self.sessions_dir, name)
        try:
            stat = os.stat(path)
        except OSError:
            self._cache.pop(name, None)
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached = self._cache.get(name)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        data = None
        try:
            with open(path, encoding="utf-8") as handle:
                parsed = json.load(handle)
            if isinstance(parsed, dict):
                data = parsed
        except (OSError, ValueError):
            # half-written file: keep serving the last good copy until it parses
            if cached is not None:
                return cached[1]
            return None
        self._cache[name] = (stamp, data)
        return data

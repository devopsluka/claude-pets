"""Shared helpers for the test suite (no test cases in here)."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from claude_pets.hook import trim_payload  # noqa: E402
from claude_pets.tracker import SessionTracker  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


class FakeClock:
    def __init__(self, start=1_800_000_000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds
        return self.t


class Recorder:
    """Collects everything a tracker tells its listeners."""

    def __init__(self, tracker):
        self.calls = []
        tracker.subscribe(self)

    def __call__(self, state, signals):
        self.calls.append((state.session_id, state.activity, list(signals)))

    def names(self):
        return [name for _, _, signals in self.calls for name, _ in signals]

    def data(self, name):
        return [data for _, _, signals in self.calls for sig, data in signals if sig == name]

    def clear(self):
        self.calls.clear()


class Harness:
    """A tracker on a fake clock, with fake process liveness."""

    def __init__(self):
        self.clock = FakeClock()
        self.dead = set()
        self.tracker = SessionTracker(clock=self.clock, pid_alive=lambda pid: pid not in self.dead)
        self.rec = Recorder(self.tracker)

    def hook(self, event, sid="s1", meta=None, ts=None, **fields):
        payload = {
            "session_id": sid,
            "hook_event_name": event,
            "cwd": "/home/user/projects/demo",
            "transcript_path": "/home/user/.claude/projects/-home-user-projects-demo/%s.jsonl" % sid,
            "permission_mode": "default",
        }
        payload.update(fields)
        meta = {"pid": 4242, "entrypoint": "cli", "attended": "1"} if meta is None else meta
        self.tracker.feed_hook({
            "type": "hook", "v": 1, "ts": self.clock() if ts is None else ts,
            "meta": meta, "payload": trim_payload(payload),
        })
        return self.tracker.get(sid)

    def tick(self, seconds=1.0, step=1.0):
        """Advance the clock in ``step`` increments, ticking each time."""
        remaining = seconds
        while remaining > 1e-9:
            delta = min(step, remaining)
            self.clock.advance(delta)
            self.tracker.tick()
            remaining -= delta

    def state(self, sid="s1"):
        return self.tracker.get(sid)


def fixture(name):
    with open(os.path.join(FIXTURES, "hooks", name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


def session_fixture(name):
    with open(os.path.join(FIXTURES, "sessions", name + ".jsonl"), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def registry_entry(sid="s1", pid=4242, status="idle", clock=None, **extra):
    now_ms = int((clock() if clock else 1_800_000_000.0) * 1000)
    entry = {
        "pid": pid, "sessionId": sid, "cwd": "/home/user/projects/demo",
        "startedAt": now_ms - 3_600_000, "procStart": "123", "kind": "interactive",
        "entrypoint": "cli", "name": "demo-1a", "status": status,
        "updatedAt": now_ms, "statusUpdatedAt": now_ms,
    }
    entry.update(extra)
    return entry

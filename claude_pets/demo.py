"""Scripted fake sessions, to see the pets in action without real work.

The demo speaks the same language as Claude Code's hooks: it feeds the
tracker hook messages, so everything downstream behaves exactly as it does
for real sessions.
"""

import itertools

_ids = itertools.count(1)


def _tool(name, tool_input, seconds, fail=False):
    return [(0.0, "PreToolUse", {"tool_name": name, "tool_input": tool_input}),
            (seconds, "PostToolUseFailure" if fail else "PostToolUse",
             {"tool_name": name, "tool_input": tool_input,
              **({"error": "Command failed with exit code 1"} if fail else {"tool_response": {}})})]


SCRIPTS = (
    ("webshop", [
        (1.5, "UserPromptSubmit", {"prompt": "add a dark mode toggle to the settings page"}),
        (2.5, *_tool("Read", {"file_path": "/demo/webshop/src/Settings.tsx"}, 2.5)[0][1:]),
        *_tool("Read", {"file_path": "/demo/webshop/src/Settings.tsx"}, 2.5)[1:],
        *[(1.2,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Grep", {"pattern": "useTheme"}, 2.5))],
        *[(1.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Edit", {"file_path": "/demo/webshop/src/Settings.tsx"}, 4.0))],
        *[(1.0,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Edit", {"file_path": "/demo/webshop/src/theme.css"}, 3.5))],
        *[(1.2,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Bash", {"command": "npm test", "description": "Run the test suite"}, 5.0))],
        (2.0, "Stop", {}),
        (14.0, "UserPromptSubmit", {"prompt": "perfect, thanks! great job"}),
        (3.0, "Stop", {}),
    ]),
    ("api-server", [
        (3.0, "UserPromptSubmit", {"prompt": "the login endpoint returns 500, please fix"}),
        *[(2.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Bash", {"command": "curl -s localhost:8080/login", "description": "Reproduce the 500"}, 2.5, fail=True))],
        *[(1.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Bash", {"command": "go build ./...", "description": "Build the server"}, 3.0, fail=True))],
        *[(1.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Bash", {"command": "go test ./auth", "description": "Run auth tests"}, 3.0, fail=True))],
        *[(1.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Edit", {"file_path": "/demo/api-server/auth/login.go"}, 4.0))],
        (1.5, "PreToolUse", {"tool_name": "Bash", "tool_input": {"command": "rm -rf ./tmp/cache", "description": "Clear the cache"}}),
        (0.3, "PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "rm -rf ./tmp/cache", "description": "Clear the cache"}}),
        (9.0, "PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "rm -rf ./tmp/cache"}, "tool_response": {}}),
        *[(1.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Bash", {"command": "go test ./...", "description": "Run all tests"}, 5.0))],
        (2.0, "Stop", {}),
        (20.0, "UserPromptSubmit", {"prompt": "still broken on staging, why??"}),
        *[(2.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Read", {"file_path": "/demo/api-server/deploy/staging.yaml"}, 3.0))],
        (2.0, "Stop", {}),
    ]),
    ("research-notes", [
        (5.0, "UserPromptSubmit", {"prompt": "survey how other tools handle offline sync"}),
        *[(2.0,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("WebSearch", {"query": "offline-first sync CRDT comparison"}, 4.0))],
        (1.0, "PreToolUse", {"tool_name": "Agent", "tool_input": {"subagent_type": "Explore", "description": "Survey sync engines"}}),
        (0.4, "SubagentStart", {"agent_type": "Explore", "agent_id": "a1"}),
        (0.6, "SubagentStart", {"agent_type": "Explore", "agent_id": "a2"}),
        (0.6, "SubagentStart", {"agent_type": "general-purpose", "agent_id": "a3"}),
        (6.0, "SubagentStop", {"agent_type": "Explore", "agent_id": "a1"}),
        (2.0, "SubagentStop", {"agent_type": "Explore", "agent_id": "a2"}),
        (2.0, "SubagentStop", {"agent_type": "general-purpose", "agent_id": "a3"}),
        (0.5, "PostToolUse", {"tool_name": "Agent", "tool_input": {"subagent_type": "Explore"}, "tool_response": {}}),
        *[(1.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("TodoWrite", {"todos": []}, 2.5))],
        *[(1.5,) + step[1:] if i == 0 else step for i, step in
          enumerate(_tool("Write", {"file_path": "/demo/research-notes/sync-survey.md"}, 4.0))],
        (2.0, "Stop", {}),
        (30.0, "UserPromptSubmit", {"prompt": "now summarise it in one paragraph"}),
        (5.0, "Stop", {}),
    ]),
)


class _Fake:
    def __init__(self, project, script, now):
        n = next(_ids)
        self.session_id = "demo-%04d-%s" % (n, project)
        self.cwd = "/demo/%s" % project
        self.script = script
        self.index = -1
        self.due = now + 0.4 * n
        self.tool_id = 0
        self.started = False


class Demo:
    def __init__(self, tracker):
        self.tracker = tracker
        self.fakes = []
        self.until = 0.0

    def session_ids(self):
        return [f.session_id for f in self.fakes]

    def start(self, count, now, cast="", seconds=0.0):
        """Start pretend sessions. ``cast="legends"`` brings one session per legend
        (the project name asks the daemon for that character)."""
        if cast == "legends":
            from .render.creature import LEGENDS
            for i, name in enumerate(LEGENDS):
                self.fakes.append(_Fake(name, SCRIPTS[i % len(SCRIPTS)][1], now))
        else:
            for i in range(max(1, min(count, len(SCRIPTS)))):
                project, script = SCRIPTS[(len(self.fakes) + i) % len(SCRIPTS)]
                self.fakes.append(_Fake(project, script, now))
        self.until = now + seconds if seconds > 0 else 0.0

    def stop(self):
        for fake in self.fakes:
            self._send(fake, "SessionEnd", {"reason": "other"}, 0.0)
        self.fakes = []

    def _send(self, fake, event, extra, ts):
        payload = {"session_id": fake.session_id, "cwd": fake.cwd, "hook_event_name": event,
                   "transcript_path": "", "permission_mode": "default"}
        payload.update(extra)
        if event == "PreToolUse":
            fake.tool_id += 1
        if event in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"):
            payload.setdefault("tool_use_id", "demo_tool_%d" % fake.tool_id)
        self.tracker.feed_hook({"type": "hook", "v": 1, "ts": ts, "meta": {"entrypoint": "demo"},
                                "payload": payload})

    def step(self, now):
        if self.until and now >= self.until:
            self.until = 0.0
            self.stop()
            return
        for fake in self.fakes:
            guard = 0
            while now >= fake.due and guard < 8:
                guard += 1
                if not fake.started:
                    fake.started = True
                    self._send(fake, "SessionStart", {"source": "startup"}, now)
                    fake.index = 0
                    fake.due = now + fake.script[0][0]
                    continue
                _delay, event, extra = fake.script[fake.index]
                self._send(fake, event, dict(extra), now)
                fake.index = (fake.index + 1) % len(fake.script)
                pause = fake.script[fake.index][0]
                fake.due = now + (pause + (25.0 if fake.index == 0 else 0.0))

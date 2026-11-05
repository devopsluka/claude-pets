import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import test_support
from test_support import fixture

from claude_pets import hook

HOOK_BIN = os.path.join(test_support.ROOT, "bin", "claude-pets-hook")


class Listener:
    """A throwaway stand-in for the daemon's socket."""

    def __init__(self):
        # AF_UNIX paths are limited to ~107 bytes: keep it short
        self.dir = tempfile.mkdtemp(prefix="cp-", dir=os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        self.path = os.path.join(self.dir, "s")
        self.lines = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(16)
        self.server.settimeout(0.2)
        self.running = True
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while self.running:
            try:
                conn, _ = self.server.accept()
            except OSError:
                continue
            data = b""
            conn.settimeout(1)
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            except OSError:
                pass
            conn.close()
            self.lines.extend(line for line in data.split(b"\n") if line)

    def wait(self, count=1, timeout=3.0):
        end = time.time() + timeout
        while len(self.lines) < count and time.time() < end:
            time.sleep(0.01)
        return [json.loads(line) for line in self.lines]

    def close(self):
        self.running = False
        self.thread.join(1)
        self.server.close()
        for name in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, name))
        os.rmdir(self.dir)


def run_hook(stdin_bytes, env_extra):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    env.update(env_extra)
    start = time.perf_counter()
    done = subprocess.run([HOOK_BIN], input=stdin_bytes, capture_output=True, env=env, timeout=10)
    return done, (time.perf_counter() - start) * 1000.0


class TrimTest(unittest.TestCase):
    def test_file_bodies_are_never_forwarded(self):
        payload = fixture("PostToolUse.Edit")
        payload["tool_input"]["new_string"] = "SECRET" * 4000
        payload["tool_response"]["originalFile"] = "TOPSECRET" * 4000
        wire = json.dumps(hook.trim_payload(payload))
        self.assertNotIn("SECRET", wire)
        self.assertLess(len(wire), 2500)
        trimmed = hook.trim_payload(payload)
        self.assertEqual(trimmed["tool_input"]["new_string"], {"_len": 24000})
        self.assertTrue(trimmed["tool_input"]["file_path"].endswith("out.txt"))
        self.assertEqual(trimmed["tool_use_id"], payload["tool_use_id"])

    def test_bash_response_summary(self):
        trimmed = hook.trim_payload(fixture("PostToolUse.Bash"))
        self.assertEqual(trimmed["tool_response"], {"interrupted": False, "noOutputExpected": False, "stdout_tail": "hello"})
        big = hook.trim_tool_response({"stdout": "a" * 5000 + "END", "stderr": "e" * 5000, "interrupted": True,
                                       "exit_code": 2, "junk": {"x": 1}})
        self.assertEqual(len(big["stdout_tail"]), 300)
        self.assertTrue(big["stdout_tail"].endswith("END"))
        self.assertEqual(len(big["stderr"]), 300)
        self.assertEqual((big["interrupted"], big["exit_code"]), (True, 2))
        self.assertNotIn("junk", big)
        self.assertEqual(hook.trim_tool_response("x" * 99), {"_len": 99})
        self.assertEqual(hook.trim_tool_response(None), {})

    def test_private_and_bulky_top_level_fields(self):
        stop = hook.trim_payload(dict(fixture("Stop"), last_assistant_message="the whole answer " * 500))
        self.assertNotIn("last_assistant_message", stop)
        self.assertEqual(stop["background_tasks"], [])
        self.assertIs(stop["stop_hook_active"], False)
        sub = hook.trim_payload(fixture("SubagentStop"))
        self.assertEqual(sub["background_tasks"][0]["type"], "subagent")
        self.assertNotIn("description", sub["background_tasks"][0])
        batch = hook.trim_payload(fixture("PostToolBatch"))
        self.assertEqual(sorted(batch["tool_calls"][0]), ["tool_name", "tool_use_id"])
        prompt = hook.trim_payload({"hook_event_name": "UserPromptSubmit", "prompt": "p" * 9000})
        self.assertEqual(len(prompt["prompt"]), 2000)
        compact = hook.trim_payload(fixture("synthetic/PostCompact"))
        self.assertNotIn("compact_summary", compact)

    def test_tool_input_shapes(self):
        trimmed = hook.trim_tool_input({
            "command": "c" * 900, "prompt": "p" * 900, "todos": [1, 2, 3], "flag": True, "n": 3,
            "nested": {"a": 1}, "nothing": None, 7: "ignored",
        })
        self.assertEqual(len(trimmed["command"]), 300)
        self.assertEqual(len(trimmed["prompt"]), 200)
        self.assertEqual(trimmed["todos"], {"_len": 3})
        self.assertEqual((trimmed["flag"], trimmed["n"], trimmed["nested"], trimmed["nothing"]), (True, 3, {"_len": 1}, None))
        self.assertEqual(hook.trim_tool_input("nope"), {})

    def test_every_fixture_stays_small(self):
        folder = os.path.join(test_support.FIXTURES, "hooks")
        for root, _, files in os.walk(folder):
            for name in files:
                with open(os.path.join(root, name), encoding="utf-8") as handle:
                    message = hook.build_message(json.load(handle), env={"CLAUDE_PID": "12"}, ts=1.0)
                self.assertLess(len(json.dumps(message)), 8192, name)


class MetaTest(unittest.TestCase):
    def test_meta_from_environment(self):
        meta = hook.build_meta({
            "CLAUDE_PID": str(os.getpid()), "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_SESSION_ATTENDED": "1",
            "CLAUDE_PROJECT_DIR": "/w/demo", "TERM": "xterm-kitty", "KITTY_WINDOW_ID": "3",
            "KITTY_LISTEN_ON": "unix:/tmp/kitty-1", "TMUX": "", "SSH_CONNECTION": "1.2.3.4 5 6.7.8.9 22",
            "DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "TERM_PROGRAM": "vscode",
        })
        self.assertEqual(meta["pid"], os.getpid())
        self.assertEqual((meta["entrypoint"], meta["attended"], meta["project_dir"]), ("cli", "1", "/w/demo"))
        self.assertEqual((meta["kitty_window_id"], meta["kitty_listen_on"]), ("3", "unix:/tmp/kitty-1"))
        self.assertIs(meta["ssh"], True)
        self.assertIs(meta["vscode"], True)
        self.assertNotIn("tmux", meta)             # empty values are omitted
        self.assertNotIn("wezterm_pane", meta)

    def test_pid_falls_back_to_the_process_tree(self):
        self.assertEqual(hook.find_claude_pid({"CLAUDE_PID": "not-a-pid"}) > 1, True)
        self.assertEqual(hook.find_claude_pid({"CLAUDE_PID": "4321"}), 4321)

    def test_daemon_allowed(self):
        self.assertFalse(hook.daemon_allowed({}))                                   # no display
        self.assertFalse(hook.daemon_allowed({"DISPLAY": ":0", hook.SOCKET_ENV: "/x"}))


class SpawnTest(unittest.TestCase):
    def test_spawn_is_detached_and_rate_limited(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "bin"))
            marker = os.path.join(tmp, "spawned.txt")
            with open(os.path.join(tmp, "bin", "claude-pets"), "w") as handle:   # a stand-in, not the real daemon
                handle.write("import os, sys\nopen(%r, 'a').write(' '.join(sys.argv[1:]) + ' '"
                             " + os.environ.get('GDK_BACKEND', '') + ' ' + os.getcwd() + '\\n')\n" % marker)
            run = os.path.join(tmp, "run")
            env = {"DISPLAY": ":0", "PATH": os.environ.get("PATH", "")}
            with mock.patch.multiple(hook.paths, APP_ROOT=tmp, RUNTIME_DIR=run,
                                     SPAWN_LOCK=os.path.join(run, "spawn.lock")):
                self.assertTrue(hook.spawn_daemon(env))
                self.assertFalse(hook.spawn_daemon(env))        # cool-down: no stampede
            end = time.time() + 5
            while not os.path.exists(marker) and time.time() < end:
                time.sleep(0.02)
            with open(marker) as handle:
                self.assertEqual(handle.read(), "daemon x11 /\n")

    def test_no_launcher_no_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.multiple(hook.paths, APP_ROOT=tmp, RUNTIME_DIR=tmp,
                                     SPAWN_LOCK=os.path.join(tmp, "spawn.lock")):
                self.assertFalse(hook.spawn_daemon({"DISPLAY": ":0"}))

    def test_stopped_flag_and_disabled_config_block_spawning(self):
        with tempfile.TemporaryDirectory() as tmp:
            flag = os.path.join(tmp, "stopped")
            config = os.path.join(tmp, "config.json")
            env = {"WAYLAND_DISPLAY": "wayland-0"}
            with mock.patch.multiple(hook.paths, STOPPED_FLAG=flag, CONFIG_FILE=config):
                self.assertTrue(hook.daemon_allowed(env))
                open(flag, "w").close()
                self.assertFalse(hook.daemon_allowed(env))
                os.unlink(flag)
                with open(config, "w") as handle:
                    handle.write('{"enabled": false}')
                self.assertFalse(hook.daemon_allowed(env))
                with open(config, "w") as handle:
                    handle.write('{"enabled": true, "scale": 1.5}')
                self.assertTrue(hook.daemon_allowed(env))
                with open(config, "w") as handle:
                    handle.write("{broken")
                self.assertTrue(hook.daemon_allowed(env))

    def test_session_start_is_retried_in_the_background(self):
        listener_dir = tempfile.mkdtemp(prefix="cp-", dir=os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
        path = os.path.join(listener_dir, "s")
        try:
            with mock.patch.dict(os.environ, {hook.SOCKET_ENV: path}):
                started = time.perf_counter()
                hook._retry_detached(b'{"type":"hook","payload":{"hook_event_name":"SessionStart"}}\n')
                self.assertLess(time.perf_counter() - started, 0.1)      # the hook itself does not wait
            time.sleep(0.25)                                             # the "daemon" comes up late
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            server.listen(1)
            server.settimeout(3)
            conn, _ = server.accept()
            data = conn.recv(4096)
            conn.close()
            server.close()
            self.assertIn(b"SessionStart", data)
        finally:
            if os.path.exists(path):
                os.unlink(path)
            os.rmdir(listener_dir)


class EndToEndTest(unittest.TestCase):
    def test_delivers_one_wire_line(self):
        listener = Listener()
        try:
            payload = fixture("PostToolUse.Bash")
            done, _ = run_hook(json.dumps(payload).encode(), {
                hook.SOCKET_ENV: listener.path, "CLAUDE_PID": "4242", "CLAUDE_CODE_ENTRYPOINT": "cli",
            })
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))
            (message,) = listener.wait(1)
        finally:
            listener.close()
        self.assertEqual((message["type"], message["v"]), ("hook", 1))
        self.assertLess(abs(message["ts"] - time.time()), 5)
        self.assertEqual(message["meta"]["pid"], 4242)
        self.assertEqual(message["payload"]["hook_event_name"], "PostToolUse")
        self.assertEqual(message["payload"]["tool_input"]["command"], "echo hello")
        self.assertEqual(message["payload"]["session_id"], payload["session_id"])

    def test_always_silent_and_successful(self):
        missing = os.path.join(tempfile.gettempdir(), "cp-no-such-socket")
        for stdin in (b"", b"   ", b"not json", b"[1, 2]", b'{"hook_event_name": "Stop"}', b"\xff\xfe"):
            done, _ = run_hook(stdin, {hook.SOCKET_ENV: missing})
            self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""), stdin)

    def test_is_fast(self):
        listener = Listener()
        try:
            stdin = json.dumps(fixture("PreToolUse")).encode()
            run_hook(stdin, {hook.SOCKET_ENV: listener.path})          # warm the bytecode cache
            with_socket = sorted(run_hook(stdin, {hook.SOCKET_ENV: listener.path})[1] for _ in range(15))
            missing = os.path.join(listener.dir, "gone")
            without = sorted(run_hook(stdin, {hook.SOCKET_ENV: missing})[1] for _ in range(15))
            listener.wait(16)
        finally:
            listener.close()
        print("\n[hook timing] socket present: median %.1f ms (min %.1f) | socket absent: median %.1f ms (min %.1f)"
              % (with_socket[7], with_socket[0], without[7], without[0]))
        self.assertLess(with_socket[7], 150)   # generous: CI noise; the target is < 40 ms
        self.assertLess(without[7], 150)


if __name__ == "__main__":
    unittest.main()

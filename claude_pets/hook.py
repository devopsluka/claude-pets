"""Claude Code hook client.

Reads one hook event (JSON on stdin), trims it, and forwards it to the pets
daemon as a single line on its UNIX socket.  Runs on *every* hook event of
*every* session, so it has to be quick and completely silent: it never
prints, never fails, and never waits for the daemon.

If the daemon is not running it is spawned detached (unless the user stopped
or disabled the pets, or there is no display to show them on).
"""

import json
import os
import socket
import sys
import time

_T0 = time.time()

from . import paths  # noqa: E402  (after _T0 on purpose: timestamp the event early)

PROTOCOL_VERSION = 1
#: Test hook: send to this socket instead of the daemon's (and never spawn one).
SOCKET_ENV = "CLAUDE_PETS_SOCKET"
SEND_TIMEOUT = 0.3
SPAWN_COOLDOWN = 5.0
SESSION_START_RETRY = 1.5

_MAX_STR = 300
_MAX_TOP_STR = 500
_MAX_PROMPT = 2000
_MAX_PATH = 1024

#: tool_input values that are file bodies — never forwarded, only their size.
_BULKY_INPUT = frozenset({
    "content", "new_string", "old_string", "new_source", "edits", "todos",
    "questions", "plan",
})
#: top-level payload fields that are never forwarded (large and/or private).
_DROP_TOP = frozenset({
    "last_assistant_message", "compact_summary", "custom_instructions",
    "permission_suggestions", "requested_schema", "content", "session_crons",
})
_RESPONSE_SCALARS = (
    "is_error", "isError", "interrupted", "exit_code", "exitCode",
    "returnCode", "code", "status", "isAsync", "agentId", "type", "success",
    "noOutputExpected",
)
_PATH_KEYS = frozenset({"transcript_path", "cwd", "agent_transcript_path"})


def _clip(text, limit):
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def trim_tool_input(tool_input):
    """Keep the short scalars that describe *what* a tool is doing."""
    if not isinstance(tool_input, dict):
        return {}
    out = {}
    for key, value in tool_input.items():
        if len(out) >= 24:
            break
        if not isinstance(key, str):
            continue
        if isinstance(value, str):
            if key in _BULKY_INPUT:
                out[key] = {"_len": len(value)}
            else:
                out[key] = _clip(value, 200 if key == "prompt" else _MAX_STR)
        elif value is None or isinstance(value, (bool, int, float)):
            out[key] = value
        elif isinstance(value, (list, dict)):
            out[key] = {"_len": len(value)}
    return out


def trim_tool_response(response):
    """Reduce a tool response to a few status scalars and short output tails."""
    if isinstance(response, dict):
        out = {}
        for key in _RESPONSE_SCALARS:
            value = response.get(key)
            if value is None:
                continue
            if isinstance(value, (bool, int, float)):
                out[key] = value
            elif isinstance(value, str):
                out[key] = _clip(value, 80)
        stderr = response.get("stderr")
        if isinstance(stderr, str) and stderr:
            out["stderr"] = _clip(stderr, _MAX_STR)
        stdout = response.get("stdout")
        if isinstance(stdout, str) and stdout:
            out["stdout_tail"] = stdout[-_MAX_STR:]
        return out
    if isinstance(response, (str, list)):
        return {"_len": len(response)}
    return {}


def _trim_background_tasks(tasks):
    out = []
    if isinstance(tasks, list):
        for task in tasks[:20]:
            if isinstance(task, dict):
                out.append({
                    key: _clip(str(task[key]), 60)
                    for key in ("id", "type", "status", "agent_type")
                    if task.get(key) is not None
                })
    return out


def _trim_tool_calls(calls):
    out = []
    if isinstance(calls, list):
        for call in calls[:50]:
            if isinstance(call, dict):
                out.append({
                    key: _clip(str(call[key]), 120)
                    for key in ("tool_name", "tool_use_id")
                    if call.get(key) is not None
                })
    return out


def trim_payload(payload):
    """Shrink a hook payload to what the tracker needs (target < ~8 KB)."""
    out = {}
    for key, value in payload.items():
        if not isinstance(key, str) or key in _DROP_TOP:
            continue
        if key == "tool_input":
            out[key] = trim_tool_input(value)
        elif key == "tool_response":
            out[key] = trim_tool_response(value)
        elif key == "background_tasks":
            out[key] = _trim_background_tasks(value)
        elif key == "tool_calls":
            out[key] = _trim_tool_calls(value)
        elif isinstance(value, str):
            if key == "prompt":
                limit = _MAX_PROMPT
            elif key in _PATH_KEYS:
                limit = _MAX_PATH
            else:
                limit = _MAX_TOP_STR
            out[key] = _clip(value, limit)
        elif value is None or isinstance(value, (bool, int, float)):
            out[key] = value
        elif isinstance(value, (list, dict)):
            out[key] = {"_len": len(value)}
    return out


def _comm(pid):
    try:
        with open("/proc/%d/comm" % pid) as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _ppid(pid):
    try:
        with open("/proc/%d/stat" % pid) as handle:
            stat = handle.read()
        return int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def find_claude_pid(env):
    """PID of the Claude Code process this hook belongs to."""
    value = env.get("CLAUDE_PID", "")
    if value.isdigit() and int(value) > 1:
        return int(value)
    pid = os.getppid()
    for _ in range(12):
        if pid <= 1:
            break
        if _comm(pid) == "claude":
            return pid
        pid = _ppid(pid)
    return os.getppid()


def find_tty(pid):
    for fd in (0, 1, 2):
        try:
            target = os.readlink("/proc/%d/fd/%d" % (pid, fd))
        except OSError:
            continue
        if target.startswith("/dev/pts/") or target.startswith("/dev/tty"):
            return target
    return ""


def build_meta(env):
    pid = find_claude_pid(env)
    meta = {
        "pid": pid,
        "tty": find_tty(pid),
        "entrypoint": env.get("CLAUDE_CODE_ENTRYPOINT", ""),
        "attended": env.get("CLAUDE_CODE_SESSION_ATTENDED", ""),
        "project_dir": env.get("CLAUDE_PROJECT_DIR", ""),
        "term_program": env.get("TERM_PROGRAM", ""),
        "term": env.get("TERM", ""),
        "kitty_window_id": env.get("KITTY_WINDOW_ID", ""),
        "kitty_listen_on": env.get("KITTY_LISTEN_ON", ""),
        "tmux": env.get("TMUX", ""),
        "tmux_pane": env.get("TMUX_PANE", ""),
        "wezterm_pane": env.get("WEZTERM_PANE", ""),
        "windowid": env.get("WINDOWID", ""),
        "vscode": bool(env.get("VSCODE_PID") or env.get("TERM_PROGRAM") == "vscode"),
        "ssh": bool(env.get("SSH_CONNECTION")),
        "display": env.get("DISPLAY", ""),
        "wayland_display": env.get("WAYLAND_DISPLAY", ""),
    }
    return {key: value for key, value in meta.items() if value not in ("", None, False)}


def build_message(payload, env=None, ts=None):
    return {
        "type": "hook",
        "v": PROTOCOL_VERSION,
        "ts": time.time() if ts is None else ts,
        "meta": build_meta(os.environ if env is None else env),
        "payload": trim_payload(payload),
    }


def send(line, timeout=SEND_TIMEOUT, path=None):
    """Deliver one protocol line; True when the daemon took it."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(path or os.environ.get(SOCKET_ENV) or paths.SOCKET_PATH)
        sock.sendall(line)
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def daemon_allowed(env=None):
    """May this hook start the daemon?"""
    env = os.environ if env is None else env
    if env.get(SOCKET_ENV):
        return False
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return False
    if os.path.exists(paths.STOPPED_FLAG):
        return False
    try:
        with open(paths.CONFIG_FILE) as handle:
            config = json.load(handle)
        if isinstance(config, dict) and config.get("enabled") is False:
            return False
    except (OSError, ValueError):
        pass
    return True


def _detach():
    """In a forked child: leave the hook's session and drop its pipes."""
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    os.closerange(3, 256)


def spawn_daemon(env=None):
    """Start the daemon detached. True when a spawn was attempted."""
    env = os.environ if env is None else env
    launcher = os.path.join(paths.APP_ROOT, "bin", "claude-pets")
    if not os.path.exists(launcher):
        return False
    import fcntl

    paths.ensure_runtime_dir()
    lock = os.open(paths.SPAWN_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        stat = os.fstat(lock)
        if stat.st_size and time.time() - stat.st_mtime < SPAWN_COOLDOWN:
            return False
        os.ftruncate(lock, 0)
        os.write(lock, b"%d\n" % int(time.time()))
        pid = os.fork()
        if pid == 0:
            try:
                _detach()
                os.chdir("/")
                child_env = dict(env)
                child_env["GDK_BACKEND"] = "x11"
                os.execve(
                    "/usr/bin/python3",
                    ["/usr/bin/python3", "-I", launcher, "daemon"],
                    child_env,
                )
            finally:
                os._exit(0)
        return True
    finally:
        os.close(lock)


def _retry_detached(line, deadline=SESSION_START_RETRY):
    """Keep trying to deliver ``line`` from a detached child (never blocks the hook)."""
    if os.fork() != 0:
        return
    try:
        _detach()
        end = time.time() + deadline
        while time.time() < end:
            time.sleep(0.1)
            if send(line):
                break
    finally:
        os._exit(0)


def main(stdin=None, env=None):
    """Entry point: forward one hook event. Always returns 0."""
    try:
        env = os.environ if env is None else env
        raw = (stdin if stdin is not None else sys.stdin.buffer).read()
        if isinstance(raw, str):
            raw = raw.encode("utf-8", "replace")
        if not raw.strip():
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return 0
        message = build_message(payload, env, ts=_T0)
        line = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        if send(line):
            return 0
        if daemon_allowed(env):
            spawn_daemon(env)
            if payload.get("hook_event_name") == "SessionStart":
                _retry_detached(line)
    except BaseException:  # a hook must never disturb the session
        pass
    return 0

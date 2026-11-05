"""Session tracker: the live picture of every Claude Code session.

Three feeds flow in —

* **hooks** (:meth:`SessionTracker.feed_hook`): precise, real-time events sent
  by ``bin/claude-pets-hook`` from inside each session;
* **registry** (:meth:`SessionTracker.feed_registry`): Claude Code's own
  ``~/.claude/sessions/<pid>.json`` files — discovers sessions that have no
  hooks (yet), tells us when a process is gone, and catches user interrupts;
* **transcripts** (:meth:`SessionTracker.feed_transcript`): context-window
  usage, and tool activity for sessions without hooks —

and one :class:`~claude_pets.model.SessionState` per session comes out, pushed
to subscribers together with one-shot :class:`~claude_pets.model.Signal` s.

Hook events may arrive slightly out of order (tool hooks run async), so tool
bookkeeping is keyed by ``tool_use_id`` and guarded by the event timestamps.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import OrderedDict
from urllib.parse import urlsplit

from .model import Activity, Signal, SessionState
from .mood import MoodEngine
from .transcript import context_limit_for

log = logging.getLogger("claude_pets.tracker")

LISTEN_SECS = 1.2          # LISTENING -> THINKING
DONE_SECS = 6.0            # DONE -> IDLE
FAILED_SECS = 20.0         # FAILED -> IDLE
STARTING_SECS = 8.0        # STARTING -> IDLE when no prompt follows
PENDING_END_SECS = 5.0     # wait for the SessionStart that follows /clear
BATCH_GRACE = 0.75         # wait for async PostToolUse before calling a tool "denied"
HEADLESS_NEED_GRACE = 1.0  # headless permission requests are usually auto-answered
REGISTRY_IDLE_GRACE = 4.0  # registry idle this long while we think "working" = interrupt
REGISTRY_MISSING_POLLS = 3
TOMBSTONE_SECS = 30.0      # ignore registry leftovers of a session that just ended
ANNOUNCE_SECS = 15.0       # one SESSION_START per fresh session (registry + hook both see it)
FRESH_SECS = 6.0           # a registry entry this young is a startup, not a discovery
COMPACT_TIMEOUT = 300.0
STALE_SECS = 12 * 3600.0
LIVENESS_EVERY = 3.0
SUSPEND_GAP = 60.0         # a tick gap this long means the machine slept
MAX_COMPLETED = 256
CONTEXT_HIGH = 0.8

READ_TOOLS = frozenset({"Read", "NotebookRead"})
SEARCH_TOOLS = frozenset({"Grep", "Glob", "LS", "ToolSearch"})
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SHELL_TOOLS = frozenset({"Bash", "BashOutput", "KillShell", "KillBash", "TaskOutput", "TaskStop", "Monitor"})
WEB_TOOLS = frozenset({"WebFetch", "WebSearch"})
AGENT_TOOLS = frozenset({"Agent", "Task", "Workflow", "SendMessage"})
PLAN_TOOLS = frozenset({
    "TodoWrite", "TodoRead", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet",
    "EnterPlanMode", "ExitPlanMode",
})
ASK_TOOLS = frozenset({"AskUserQuestion"})
_BROWSER_HINTS = ("claude-in-chrome", "claude_browser", "playwright", "puppeteer", "browser", "chrome-devtools")

_TERM_KEYS = (
    "tty", "term_program", "term", "kitty_window_id", "kitty_listen_on", "tmux",
    "tmux_pane", "wezterm_pane", "windowid", "vscode", "ssh",
)
_MACHINE_SOURCES = frozenset({"system", "loop_wakeup", "schedule_wakeup", "poll_event"})
_MACHINE_PREFIXES = (
    "<task-notification", "<system-reminder", "<local-command", "<command-name",
    "<command-message", "[SYSTEM NOTIFICATION", "<bash-", "<user-prompt-submit-hook",
)

_TEST_RE = re.compile(
    r"\b(?:pytest|py\.test|tox|nox|unittest|jest|vitest|mocha|rspec|phpunit|ctest|bats"
    r"|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test\S*|t)\b"
    r"|(?:cargo|go|dotnet|bazel|swift|mix|deno|bun)\s+(?:nex)?test"
    r"|playwright\s+test|cypress\s+run|helm\s+unittest)\b"
)
_BUILD_RE = re.compile(
    r"\b(?:(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?build\S*"
    r"|(?:cargo|go|dotnet|bazel|swift)\s+build"
    r"|make|ninja|cmake\s+--build|mvn|mvnw|gradle|gradlew|tsc|docker\s+build"
    r"|helm\s+(?:template|package)|terraform\s+plan)\b"
)
_LINT_RE = re.compile(
    r"\b(?:(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:lint\S*|typecheck|check|format\S*)"
    r"|cargo\s+(?:check|clippy|fmt)|go\s+vet|eslint|ruff|mypy|pyright|flake8|pylint"
    r"|shellcheck|golangci-lint|prettier\s+--check|black\s+--check"
    r"|helm\s+lint|kubeval|terraform\s+validate)\b"
)
_COMMIT_RE = re.compile(r"\bgit\s+(?:-\S+\s+(?:\S+\s+)?)*commit\b")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# -- sentiment ---------------------------------------------------------------
_PRAISE = [
    (r"\bthank(?:s| you| u)\b|\bthx\b|\bty\b", 2),
    (r"\b(?:great|good|nice|awesome|amazing|excellent) (?:job|work|stuff|one)\b", 2),
    (r"\bwell done\b|\bnailed it\b|\byou rock\b|\bgood bot\b|\blgtm\b", 2),
    (r"\b(?:awesome|amazing|perfect|excellent|brilliant|fantastic|wonderful|beautiful|superb|impressive)\b", 2),
    (r"\blove (?:it|this|that)\b|\blooks (?:good|great|amazing|perfect)\b", 2),
    (r"\b(?:it )?works (?:now|great|perfectly|like a charm)\b|\bit works\b", 2),
    (r"^(?:nice|great|cool|sweet|yay)\b[ !.]*", 1),
    (r"[\U0001F389\U0001F64F\U0001F44D\U0001F60D\U0001F970\U0001F44F❤\U0001F525\U0001F680]", 2),
    # Slovenian
    (r"\bhvala\b|\bbravo\b|\bodli[cč]no\b|\bkrasno\b|\bsuper\b|\bzakon\b|\bcarsko\b|\bfantasti[cč]no\b", 2),
    (r"\b(?:zdaj )?dela(?:\s+super|\s+odli[cč]no)\b|\bdeluje\b(?!\s*ne)", 1),
]
_FRUSTRATED = [
    (r"\bwtf\b|\bffs\b|\bugh+\b|\bargh+\b|\bfuck\w*|\bshit\w*|\bdamn(?:it)?\b|\bdammit\b|\bcrap\b", 2),
    (r"\bstill (?:broken|failing|wrong|not|doesn'?t|does not|isn'?t|is not|the same|crash\w*)\b", 2),
    (r"\b(?:broken|wrong|failing|failed) again\b|\bagain\s*[?!]{2,}", 2),
    (r"\bnot what i (?:asked|wanted|said|meant)\b|\bi (?:told|asked) you\b|\bi said\b", 2),
    (r"\bwhy did you\b|\byou (?:broke|deleted|ruined|removed|ignored|forgot)\b|\bstop doing\b", 2),
    (r"\b(?:terrible|awful|useless|stupid|garbage|horrible|ridiculous|nonsense)\b", 2),
    (r"\b(?:that'?s|this is|it'?s|completely|totally|all) wrong\b", 2),
    (r"\b(?:undo|revert) (?:that|this|it|everything|all)\b|\bno,? no\b|\bcome on\b|\bseriously\b", 1),
    (r"\b(?:doesn'?t|does not|didn'?t|did not) work\b|\bnot working\b|\bbroken\b", 1),
    (r"[!?]{3,}", 1),
    (r"[\U0001F926\U0001F621\U0001F624\U0001F92C\U0001F620]", 2),
    # Slovenian
    (r"\bše vedno ne\b|\bse vedno ne\b|\b[zž]e spet\b|\bspet (?:ne|narobe|isto)\b", 2),
    (r"\bnarobe\b|\bnapa[cč]no\b|\bni prav\b|\bgrozno\b|\bsranje\b|\bkaj za vraga\b|\bzakaj si\b|\bpokvaril\w*", 2),
    (r"\bne (?:dela|deluje)\b", 1),
]
_PRAISE = [(re.compile(p, re.I | re.M), w) for p, w in _PRAISE]
_FRUSTRATED = [(re.compile(p, re.I | re.M), w) for p, w in _FRUSTRATED]


def classify_sentiment(text) -> str:
    """``praise`` / ``frustrated`` / ``neutral`` — conservative on purpose."""
    if not isinstance(text, str) or not text.strip():
        return "neutral"
    sample = text if len(text) <= 700 else text[:350] + "\n" + text[-350:]
    praise = sum(w for rx, w in _PRAISE if rx.search(sample))
    anger = sum(w for rx, w in _FRUSTRATED if rx.search(sample))
    letters = [c for c in sample if c.isalpha()]
    if len(letters) >= 12 and sum(c.isupper() for c in letters) >= 0.8 * len(letters):
        anger += 1  # SHOUTING
    if anger >= 2 and praise < 2:
        return "frustrated"
    if praise >= 2 and anger == 0:
        return "praise"
    return "neutral"


def is_machine_prompt(text, source=None) -> bool:
    """True for prompts injected by the harness rather than typed by the user."""
    if source in _MACHINE_SOURCES:
        return True
    return isinstance(text, str) and text.lstrip().startswith(_MACHINE_PREFIXES)


def snippet(text, limit: int = 80) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _clip(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _base(path) -> str:
    path = str(path or "").rstrip("/")
    return os.path.basename(path) or path


def command_head(command, limit: int = 36) -> str:
    """Program + subcommand of a shell command, without arguments or secrets."""
    line = ""
    for raw in str(command or "").splitlines():
        if raw.strip() and not raw.strip().startswith("#"):
            line = raw.strip()
            break
    words = []
    for token in line.split():
        if not words and (_ENV_ASSIGN_RE.match(token) or token in ("sudo", "env", "time", "nohup", "exec")):
            continue
        if not words and token == "cd":
            return "cd"
        if token.startswith("-") or any(ch in token for ch in "=/$\"'`|&;<>(){}"):
            if not words and "/" in token and not any(ch in token for ch in "=$\"'`|&;<>(){}"):
                words.append(os.path.basename(token))  # /usr/bin/foo -> foo
                continue
            break
        words.append(token)
        if len(words) >= 3:
            break
    return _clip(" ".join(words), limit)


def shell_kind(command) -> str:
    """``test`` / ``build`` / ``lint`` / ``commit`` / ```` for a shell command."""
    text = str(command or "")[:600]
    if _TEST_RE.search(text):
        return "test"
    if _LINT_RE.search(text):
        return "lint"
    if _BUILD_RE.search(text):
        return "build"
    return ""


def is_git_commit(command) -> bool:
    text = str(command or "")[:600]
    return bool(_COMMIT_RE.search(text)) and "--dry-run" not in text


def classify_tool(name, tool_input=None):
    """Map a tool call to ``(activity, detail, target)``."""
    name = str(name or "")
    ti = tool_input if isinstance(tool_input, dict) else {}

    def text(key):
        value = ti.get(key)
        return value if isinstance(value, str) else ""

    if name in READ_TOOLS:
        target = _base(text("file_path") or text("notebook_path"))
        return Activity.READING, ("Reading " + target) if target else "Reading", target
    if name in SEARCH_TOOLS:
        if name == "Grep":
            target = _clip(text("pattern"), 24)
            return Activity.SEARCHING, ("Searching for “%s”" % target) if target else "Searching", target
        if name == "Glob":
            target = _clip(text("pattern"), 28)
            return Activity.SEARCHING, ("Finding " + target) if target else "Finding files", target
        if name == "ToolSearch":
            return Activity.SEARCHING, "Looking for tools", ""
        target = _base(text("path"))
        return Activity.SEARCHING, ("Listing " + target) if target else "Listing files", target
    if name in WRITE_TOOLS:
        target = _base(text("file_path") or text("notebook_path"))
        verb = "Writing" if name == "Write" else "Editing"
        return Activity.WRITING, ("%s %s" % (verb, target)) if target else verb, target
    if name in SHELL_TOOLS:
        if name != "Bash":
            return Activity.RUNNING, "Checking a background task", ""
        command = text("command")
        kind = shell_kind(command)
        head = command_head(command)
        if kind == "test":
            return Activity.TESTING, "Running tests", head
        if kind == "build":
            return Activity.TESTING, "Building", head
        if kind == "lint":
            return Activity.TESTING, "Checking the code", head
        described = _clip(text("description"), 44)
        if described:
            return Activity.RUNNING, described, head
        return Activity.RUNNING, ("Running " + head) if head else "Running a command", head
    if name in WEB_TOOLS:
        if name == "WebSearch":
            target = _clip(text("query"), 28)
            return Activity.BROWSING, ("Searching the web for “%s”" % target) if target else "Searching the web", target
        host = ""
        try:
            host = urlsplit(text("url")).hostname or ""
        except ValueError:
            host = ""
        return Activity.BROWSING, ("Browsing " + host) if host else "Browsing the web", host
    if name in AGENT_TOOLS:
        target = _clip(text("description"), 36) or text("subagent_type")
        return Activity.DELEGATING, ("Delegating: " + target) if target else "Delegating", target
    if name in PLAN_TOOLS:
        if name == "ExitPlanMode":
            return Activity.PLANNING, "Presenting the plan", ""
        if name == "EnterPlanMode":
            return Activity.PLANNING, "Planning", ""
        return Activity.PLANNING, "Updating the plan", ""
    if name in ASK_TOOLS:
        return Activity.ASKING, "Asking you a question", ""
    if name == "Skill":
        target = _clip(text("skill"), 28)
        return Activity.TOOL, ("Using skill " + target) if target else "Using a skill", target
    if name.startswith("mcp__"):
        parts = name.split("__")
        server = parts[1] if len(parts) > 1 else ""
        tool = "__".join(parts[2:]) if len(parts) > 2 else ""
        lowered = name.lower()
        if any(hint in lowered for hint in _BROWSER_HINTS):
            return Activity.BROWSING, "Using the browser", tool
        label = _clip(server.replace("_", " "), 22)
        if tool:
            label = "%s · %s" % (label, _clip(tool.replace("_", " "), 22))
        return Activity.TOOL, "Using " + label, tool
    return Activity.TOOL, ("Using " + _clip(name, 28)) if name else "Using a tool", ""


def _input_key(tool_input) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("command", "file_path", "notebook_path", "url", "pattern", "query", "skill", "description"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return ""


def _pid_alive(pid) -> bool:
    return os.path.exists("/proc/%d" % pid)


class _Tool:
    __slots__ = ("name", "activity", "detail", "target", "started", "agent_id", "key")

    def __init__(self, name, activity, detail, target, started, agent_id, key):
        self.name = name
        self.activity = activity
        self.detail = detail
        self.target = target
        self.started = started
        self.agent_id = agent_id
        self.key = key


class _Aux:
    """Private per-session bookkeeping (lives on the state as ``_aux``)."""

    def __init__(self):
        self.running = OrderedDict()     # tool_use_id -> _Tool
        self.completed = OrderedDict()   # tool_use_id -> True (bounded)
        self.agents = set()              # ids of running subagents
        self.listen_until = 0.0
        self.done_until = 0.0
        self.failed_until = 0.0
        self.starting_until = 0.0
        self.note = ""                   # detail text for DONE / FAILED
        self.compacting_since = 0.0
        self.pending_end = None          # (deadline, reason)
        self.batch_pending = {}          # tool_use_id -> deadline
        self.need_tool = ""
        self.need_key = ""
        self.need_agent = ""
        self.need_later = None           # (deadline, reason, detail) for headless sessions
        self.in_registry = False
        self.missing = 0
        self.reg_status = ""
        self.reg_status_at = 0.0
        self.last_hook_at = 0.0
        self.prompt_ts = 0.0
        self.stop_ts = 0.0
        self.turn_counted = False
        self.context_high = False
        self.last_tick = 0.0
        self.liveness_at = 0.0
        self.announced_at = 0.0          # when SESSION_START was last emitted
        self.sig = None


class SessionTracker:
    """Turns hook / registry / transcript input into live session states."""

    def __init__(self, clock=time.time, mood=None, pid_alive=None):
        self._clock = clock
        self._mood = mood or MoodEngine()
        self._pid_alive = pid_alive or _pid_alive
        self._sessions: dict[str, SessionState] = {}
        self._ended: dict[str, float] = {}   # session_id -> when it ended (tombstones)
        self._listeners = []

    # -- public API ---------------------------------------------------------
    def subscribe(self, fn) -> None:
        self._listeners.append(fn)

    def get(self, session_id):
        return self._sessions.get(session_id)

    def all(self) -> list:
        return list(self._sessions.values())

    def nudge(self, session_id, *, mood=0.0, energy=0.0, stress=0.0) -> None:
        state = self._sessions.get(session_id)
        if state is None:
            return
        now = self._clock()
        self._mood.nudge(state, mood=mood, energy=energy, stress=stress)
        self._mood.refresh(state, now)
        self._notify(state, [])

    def feed_hook(self, msg) -> None:
        try:
            self._feed_hook(msg)
        except Exception:  # never let a malformed event take the daemon down
            log.exception("hook event failed")

    def feed_registry(self, entries) -> None:
        try:
            self._feed_registry(entries)
        except Exception:
            log.exception("registry snapshot failed")

    def feed_transcript(self, session_id, records, initial: bool = False) -> None:
        try:
            self._feed_transcript(session_id, records, initial)
        except Exception:
            log.exception("transcript batch failed")

    def tick(self, now=None) -> None:
        now = self._clock() if now is None else now
        for state in list(self._sessions.values()):
            try:
                self._tick_one(state, now)
            except Exception:
                log.exception("tick failed")

    # -- plumbing -------------------------------------------------------------
    def _create(self, session_id, now) -> SessionState:
        state = SessionState(session_id=session_id)
        state.started_at = now
        state.last_event_at = now
        state.activity_since = now
        state._aux = _Aux()
        state._aux.last_tick = now
        self._sessions[session_id] = state
        return state

    def _rekey(self, session_id, pid):
        """Another session id showed up in a process we already track (/clear, /resume)."""
        if not isinstance(pid, int) or pid <= 1:
            return None, None
        for old in self._sessions.values():
            if old.pid == pid and old.session_id != session_id and not old.ended:
                old_id = old.session_id
                del self._sessions[old_id]
                old.session_id = session_id
                self._sessions[session_id] = old
                self._reset_conversation(old)
                return old, old_id
        return None, None

    @staticmethod
    def _reset_conversation(state) -> None:
        aux = state._aux
        aux.running.clear()
        aux.completed.clear()
        aux.agents.clear()
        aux.batch_pending.clear()
        aux.pending_end = None
        aux.need_later = None
        aux.listen_until = aux.done_until = aux.failed_until = 0.0
        aux.compacting_since = 0.0
        aux.context_high = False
        aux.turn_counted = False
        state.subagents = 0
        state.turn_active = False
        state.needs_user = False
        state.needs_reason = state.needs_detail = ""
        state.needs_since = 0.0
        state.context_tokens = 0
        state.context_pct = None
        state.transcript_path = ""
        state.last_prompt = ""

    def _finish(self, state, signals, now) -> None:
        """Common tail of every feed: feelings, derived activity, notify, drop."""
        for name, data in signals:
            self._mood.apply(state, name, data, now)
            if name == Signal.SESSION_START:
                state._aux.announced_at = now
        if not state.ended:
            self._derive(state, now)
        self._mood.refresh(state, now)
        self._notify(state, signals)
        if state.ended:
            self._sessions.pop(state.session_id, None)
            self._ended[state.session_id] = now
            for session_id, when in list(self._ended.items()):
                if now - when > TOMBSTONE_SECS:
                    del self._ended[session_id]

    def _notify(self, state, signals) -> None:
        state._aux.sig = self._signature(state)
        for fn in list(self._listeners):
            try:
                fn(state, list(signals))
            except Exception:
                log.exception("listener failed")

    @staticmethod
    def _signature(state):
        return (state.activity, state.needs_user, state.emotion, state.ended, state.detail, state.subagents)

    def _end(self, state, reason, signals, now) -> None:
        state.ended = True
        state.activity = Activity.ENDED
        state.activity_since = now
        state.detail = ""
        state.tool = state.tool_target = ""
        state.needs_user = False
        state.turn_active = False
        signals.append((Signal.SESSION_END, {"reason": reason}))

    # -- needs-the-user bookkeeping -----------------------------------------
    @staticmethod
    def _need(state, reason, detail, now, signals) -> None:
        if state.needs_user and state.needs_reason == reason:
            if detail:
                state.needs_detail = detail
            return
        if not state.needs_user:
            state.needs_since = now
        state.needs_user = True
        state.needs_reason = reason
        state.needs_detail = detail
        signals.append((Signal.NEEDS_USER, {"reason": reason, "detail": detail}))

    @staticmethod
    def _resolve(state, signals) -> bool:
        aux = state._aux
        aux.need_later = None
        aux.need_tool = aux.need_key = aux.need_agent = ""
        if not state.needs_user:
            return False
        reason = state.needs_reason
        state.needs_user = False
        state.needs_reason = state.needs_detail = ""
        state.needs_since = 0.0
        signals.append((Signal.USER_RESPONDED, {"reason": reason}))
        return True

    # -- derived activity -----------------------------------------------------
    def _derive(self, state, now) -> None:
        aux = state._aux
        tool = target = ""
        main_tool = None
        for running in reversed(aux.running.values()):
            if not running.agent_id:
                main_tool = running
                break

        if aux.compacting_since:
            activity, detail = Activity.COMPACTING, "Tidying up its memory"
        elif state.needs_user and state.needs_reason == "permission":
            activity, detail = Activity.WAITING, "Waiting for your OK"
            tool = aux.need_tool
        elif state.needs_user and state.needs_reason in ("question", "elicitation"):
            activity, detail = Activity.ASKING, "Has a question for you"
        elif main_tool is not None:
            activity, detail = main_tool.activity, main_tool.detail
            tool, target = main_tool.name, main_tool.target
        elif state.subagents > 0:
            activity = Activity.DELEGATING
            detail = "1 helper at work" if state.subagents == 1 else "%d helpers at work" % state.subagents
        elif now < aux.listen_until:
            activity, detail = Activity.LISTENING, "Listening"
        elif now < aux.failed_until:
            activity, detail = Activity.FAILED, aux.note or "Something went wrong"
        elif now < aux.done_until:
            activity, detail = Activity.DONE, aux.note or "Done"
        elif state.turn_active:
            activity, detail = Activity.THINKING, "Thinking"
        elif now < aux.starting_until:
            activity, detail = Activity.STARTING, "Hello!"
        else:
            activity, detail = Activity.IDLE, ""

        if activity != state.activity:
            state.activity = activity
            state.activity_since = now
        state.detail = detail
        state.tool = tool
        state.tool_target = target

    # -- hooks ----------------------------------------------------------------
    def _feed_hook(self, msg) -> None:
        if not isinstance(msg, dict):
            return
        payload = msg.get("payload")
        if not isinstance(payload, dict):
            return
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return
        meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
        now = self._clock()
        ts = msg.get("ts")
        ts = float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else now
        if ts > now:
            ts = now
        event = payload.get("hook_event_name")
        event = event if isinstance(event, str) else ""
        signals = []

        state = self._sessions.get(session_id)
        created = False
        replaced = None
        if state is None:
            state, replaced = self._rekey(session_id, meta.get("pid"))
            if state is None:
                state = self._create(session_id, now)
                created = True
        aux = state._aux
        if aux.pending_end and event != "SessionEnd":
            aux.pending_end = None  # the session lives on (e.g. /clear kept the id)
        state.has_hooks = True
        state.last_event_at = now
        aux.last_hook_at = now
        self._apply_common(state, payload, meta)

        if event != "SessionStart" and (created or replaced):
            data = {"source": "discovered"}
            if replaced:
                data["replaces"] = replaced
            signals.append((Signal.SESSION_START, data))

        handler = getattr(self, "_on_" + event, None) if event.isidentifier() else None
        if handler is None:
            if signals:
                self._finish(state, signals, now)
            return
        if event == "SessionStart":
            handler(state, payload, ts, now, signals, created, replaced)
        else:
            handler(state, payload, ts, now, signals)
        self._finish(state, signals, now)

    @staticmethod
    def _apply_common(state, payload, meta) -> None:
        pid = meta.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 1:
            state.pid = pid
        entrypoint = meta.get("entrypoint")
        if isinstance(entrypoint, str) and entrypoint:
            state.entrypoint = entrypoint
        if state.entrypoint.startswith("sdk") or meta.get("attended") == "0":
            state.headless = True
        if not state.cwd:
            cwd = meta.get("project_dir") or payload.get("cwd")
            if isinstance(cwd, str) and cwd:
                state.cwd = cwd
        if state.cwd and not state.project:
            state.project = _base(state.cwd)
        transcript = payload.get("transcript_path")
        if isinstance(transcript, str) and transcript:
            state.transcript_path = transcript
        mode = payload.get("permission_mode")
        if isinstance(mode, str) and mode:
            state.permission_mode = mode
        for key in _TERM_KEYS:
            value = meta.get(key)
            if value:
                state.term[key] = value

    def _on_SessionStart(self, state, payload, ts, now, signals, created, replaced) -> None:
        aux = state._aux
        source = payload.get("source")
        source = source if isinstance(source, str) and source else "startup"
        model = payload.get("model")
        if isinstance(model, str) and model:
            state.model = model
        if source == "compact" and not created and not replaced:
            if aux.compacting_since:
                aux.compacting_since = 0.0
                signals.append((Signal.COMPACT_DONE, {}))
            return
        if source == "clear" and not replaced:
            transcript = state.transcript_path
            self._reset_conversation(state)
            state.transcript_path = transcript
        if created:
            state.started_at = ts
        tokens = payload.get("context_tokens")
        if isinstance(tokens, (int, float)) and not isinstance(tokens, bool) and tokens > 0:
            self._set_context(state, state.model, int(tokens), signals, quiet=True)
        if (not created and not replaced and source == "startup"
                and now - aux.announced_at < ANNOUNCE_SECS):
            return  # the registry already introduced this brand-new session
        aux.starting_until = now + STARTING_SECS
        data = {"source": source}
        if replaced:
            data["replaces"] = replaced
        signals.append((Signal.SESSION_START, data))

    def _on_SessionEnd(self, state, payload, ts, now, signals) -> None:
        reason = payload.get("reason")
        reason = reason if isinstance(reason, str) and reason else "other"
        if reason in ("clear", "resume"):
            state._aux.pending_end = (now + PENDING_END_SECS, reason)
            return
        self._end(state, reason, signals, now)

    def _on_UserPromptSubmit(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        text = payload.get("prompt")
        text = text if isinstance(text, str) else ""
        aux.prompt_ts = max(aux.prompt_ts, ts)
        aux.done_until = aux.failed_until = aux.starting_until = 0.0
        if is_machine_prompt(text, payload.get("source")):
            # task notifications, wake-ups: the turn simply carries on
            if not state.turn_active:
                state.turn_active = True
                if not state.turn_started_at:
                    state.turn_started_at = ts
            return
        self._resolve(state, signals)
        state.prompts += 1
        state.last_prompt = snippet(text)
        busy = state.turn_active and (aux.running or state.subagents > 0)
        if not busy:
            state.turn_started_at = ts
            state.turn_tools = state.turn_errors = state.turn_edits = 0
            aux.turn_counted = False
            aux.listen_until = now + LISTEN_SECS
        state.turn_active = True
        signals.append((Signal.PROMPT, {
            "sentiment": classify_sentiment(text),
            "snippet": state.last_prompt,
        }))

    def _on_PreToolUse(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        tool_id = payload.get("tool_use_id")
        tool_id = tool_id if isinstance(tool_id, str) else ""
        if tool_id and tool_id in aux.completed:
            return  # its PostToolUse overtook it
        if ts <= aux.stop_ts:
            return  # a straggler from a turn that already ended
        name = payload.get("tool_name")
        name = name if isinstance(name, str) else ""
        tool_input = payload.get("tool_input")
        agent_id = payload.get("agent_id")
        agent_id = agent_id if isinstance(agent_id, str) else ""
        activity, detail, target = classify_tool(name, tool_input)
        key = tool_id or "anon-%d" % (len(aux.running) + 1)
        aux.running[key] = _Tool(name, activity, detail, target, ts, agent_id, _input_key(tool_input))
        if agent_id and agent_id not in aux.agents:
            aux.agents.add(agent_id)  # we missed its SubagentStart
            state.subagents = len(aux.agents)
        if not state.turn_active:
            state.turn_active = True
            if not state.turn_started_at:
                state.turn_started_at = ts
        aux.listen_until = 0.0
        aux.done_until = aux.failed_until = 0.0
        # the model moved on: an old request on this thread must have been answered
        if (state.needs_user and state.needs_reason in ("permission", "question")
                and aux.need_agent == agent_id and state.needs_since
                and now - state.needs_since > 2.0
                and (name != aux.need_tool or _input_key(tool_input) != aux.need_key)):
            self._resolve(state, signals)
        if name in ASK_TOOLS and not agent_id:
            aux.need_tool, aux.need_key, aux.need_agent = name, _input_key(tool_input), agent_id
            self._need(state, "question", "Asking you a question", now, signals)
        data = {"tool": name, "activity": activity, "detail": detail}
        if agent_id:
            data["agent"] = True
        signals.append((Signal.TOOL_START, data))

    def _tool_done(self, state, payload):
        """Pop the finished tool; returns ``(name, tool_input, info, agent_id)``."""
        aux = state._aux
        tool_id = payload.get("tool_use_id")
        tool_id = tool_id if isinstance(tool_id, str) else ""
        info = aux.running.pop(tool_id, None) if tool_id else None
        if tool_id:
            aux.completed[tool_id] = True
            while len(aux.completed) > MAX_COMPLETED:
                aux.completed.popitem(last=False)
            aux.batch_pending.pop(tool_id, None)
        name = payload.get("tool_name")
        name = name if isinstance(name, str) else (info.name if info else "")
        tool_input = payload.get("tool_input")
        agent_id = payload.get("agent_id")
        agent_id = agent_id if isinstance(agent_id, str) else ""
        return name, tool_input, info, agent_id

    def _answers_need(self, state, name, tool_input, agent_id) -> bool:
        aux = state._aux
        if not state.needs_user and aux.need_later is None:
            return False
        if state.needs_reason == "idle":
            return True
        if aux.need_agent != agent_id:
            return False
        if aux.need_tool and name != aux.need_tool:
            return False
        if aux.need_key and _input_key(tool_input) != aux.need_key:
            return False
        return True

    def _on_PostToolUse(self, state, payload, ts, now, signals) -> None:
        name, tool_input, info, agent_id = self._tool_done(state, payload)
        if self._answers_need(state, name, tool_input, agent_id):
            self._resolve(state, signals)
        if not state.turn_active and ts > state._aux.stop_ts:
            state.turn_active = True  # joined mid-turn
        state.tools_ok += 1
        state.ok_streak += 1
        state.error_streak = 0
        state.turn_tools += 1
        if name in WRITE_TOOLS:
            state.edits += 1
            state.turn_edits += 1
        if name in SHELL_TOOLS:
            state.commands += 1
        data = {"tool": name, "streak": state.ok_streak}
        if agent_id:
            data["agent"] = True
        signals.append((Signal.TOOL_OK, data))
        if name == "Bash" and isinstance(tool_input, dict):
            command = tool_input.get("command")
            kind = shell_kind(command)
            if kind:
                label = {"test": "Tests passed", "build": "Build passed", "lint": "Checks passed"}[kind]
                signals.append((Signal.TESTS_PASSED, {"detail": label}))
            if is_git_commit(command):
                signals.append((Signal.COMMIT, {"detail": "Committed"}))

    def _on_PostToolUseFailure(self, state, payload, ts, now, signals) -> None:
        name, tool_input, info, agent_id = self._tool_done(state, payload)
        if self._answers_need(state, name, tool_input, agent_id):
            self._resolve(state, signals)
        if payload.get("is_interrupt") is True:
            signals.append((Signal.INTERRUPTED, {}))
            return
        if not state.turn_active and ts > state._aux.stop_ts:
            state.turn_active = True  # joined mid-turn
        state.tools_failed += 1
        state.error_streak += 1
        state.ok_streak = 0
        state.turn_errors += 1
        state.turn_tools += 1
        if name in SHELL_TOOLS:
            state.commands += 1
        detail = _clip(payload.get("error"), 80) if isinstance(payload.get("error"), str) else ""
        data = {"tool": name, "streak": state.error_streak, "detail": detail}
        if agent_id:
            data["agent"] = True
        signals.append((Signal.TOOL_ERROR, data))
        if name == "Bash" and isinstance(tool_input, dict):
            kind = shell_kind(tool_input.get("command"))
            if kind:
                label = {"test": "Tests failed", "build": "Build failed", "lint": "Checks failed"}[kind]
                signals.append((Signal.TESTS_FAILED, {"detail": label}))

    def _on_PostToolBatch(self, state, payload, ts, now, signals) -> None:
        """Every call of the batch has resolved; leftovers never ran (denied)."""
        aux = state._aux
        calls = payload.get("tool_calls")
        if not isinstance(calls, list):
            return
        for call in calls:
            tool_id = call.get("tool_use_id") if isinstance(call, dict) else None
            if isinstance(tool_id, str) and tool_id in aux.running:
                aux.batch_pending[tool_id] = now + BATCH_GRACE

    def _settle_batch(self, state, now, signals) -> bool:
        aux = state._aux
        changed = False
        for tool_id, deadline in list(aux.batch_pending.items()):
            if now < deadline:
                continue
            del aux.batch_pending[tool_id]
            info = aux.running.pop(tool_id, None)
            aux.completed[tool_id] = True
            if info is None:
                continue
            changed = True
            asked = state.needs_user or aux.need_later is not None
            if asked and aux.need_agent == info.agent_id and (not aux.need_tool or aux.need_tool == info.name):
                self._resolve(state, signals)
                signals.append((Signal.PERMISSION_DENIED, {"tool": info.name}))
        return changed

    def _on_PermissionRequest(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        name = payload.get("tool_name")
        name = name if isinstance(name, str) else ""
        tool_input = payload.get("tool_input")
        agent_id = payload.get("agent_id")
        aux.need_tool = name
        aux.need_key = _input_key(tool_input)
        aux.need_agent = agent_id if isinstance(agent_id, str) else ""
        _, _, target = classify_tool(name, tool_input)
        detail = "%s: %s" % (name, target) if target else name
        if state.headless:
            aux.need_later = (now + HEADLESS_NEED_GRACE, "permission", detail)
            return
        self._need(state, "permission", detail, now, signals)

    def _on_PermissionDenied(self, state, payload, ts, now, signals) -> None:
        name, tool_input, info, agent_id = self._tool_done(state, payload)
        if self._answers_need(state, name, tool_input, agent_id):
            self._resolve(state, signals)
        signals.append((Signal.PERMISSION_DENIED, {"tool": name}))

    def _on_Notification(self, state, payload, ts, now, signals) -> None:
        kind = payload.get("notification_type")
        message = _clip(payload.get("message"), 60) if isinstance(payload.get("message"), str) else ""
        if kind in ("permission_prompt", "worker_permission_prompt"):
            if not (state.needs_user and state.needs_reason == "permission"):
                state._aux.need_later = None
                self._need(state, "permission", state._aux.need_tool or message, now, signals)
        elif kind == "idle_prompt":
            if not state.needs_user:
                self._need(state, "idle", message, now, signals)
        elif kind in ("elicitation_dialog", "agent_needs_input"):
            self._need(state, "elicitation" if kind == "elicitation_dialog" else "question", message, now, signals)

    def _on_Elicitation(self, state, payload, ts, now, signals) -> None:
        server = payload.get("mcp_server_name")
        detail = _clip(server, 40) if isinstance(server, str) else ""
        state._aux.need_tool = state._aux.need_key = state._aux.need_agent = ""
        self._need(state, "elicitation", detail, now, signals)

    def _on_ElicitationResult(self, state, payload, ts, now, signals) -> None:
        self._resolve(state, signals)

    def _on_SubagentStart(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        agent_id = payload.get("agent_id")
        agent_id = agent_id if isinstance(agent_id, str) and agent_id else "agent-%d" % (len(aux.agents) + 1)
        aux.agents.add(agent_id)
        state.subagents = len(aux.agents)
        if not state.turn_active:
            state.turn_active = True
        agent_type = payload.get("agent_type")
        signals.append((Signal.SUBAGENT_START, {
            "agent_type": agent_type if isinstance(agent_type, str) else "",
            "count": state.subagents,
        }))

    def _on_SubagentStop(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        agent_id = payload.get("agent_id")
        if isinstance(agent_id, str) and agent_id in aux.agents:
            aux.agents.discard(agent_id)
        elif aux.agents and not isinstance(agent_id, str):
            aux.agents.pop()
        for tool_id, info in list(aux.running.items()):
            if info.agent_id and info.agent_id == agent_id:
                del aux.running[tool_id]
        state.subagents = len(aux.agents)
        agent_type = payload.get("agent_type")
        signals.append((Signal.SUBAGENT_STOP, {
            "agent_type": agent_type if isinstance(agent_type, str) else "",
            "count": state.subagents,
        }))

    def _on_PreCompact(self, state, payload, ts, now, signals) -> None:
        state._aux.compacting_since = now
        trigger = payload.get("trigger")
        signals.append((Signal.COMPACT_START, {"trigger": trigger if isinstance(trigger, str) else ""}))

    def _on_PostCompact(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        aux.compacting_since = 0.0
        aux.context_high = False
        state.context_tokens = 0
        state.context_pct = None
        signals.append((Signal.COMPACT_DONE, {}))

    def _on_Stop(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        if ts < aux.prompt_ts:
            return  # a newer prompt already started the next turn
        tasks = payload.get("background_tasks")
        if isinstance(tasks, list):
            alive = set()
            for task in tasks:
                if isinstance(task, dict) and task.get("type") == "subagent" \
                        and task.get("status") in (None, "running", "pending", "in_progress"):
                    alive.add(str(task.get("id") or "task-%d" % len(alive)))
            aux.agents = alive
            state.subagents = len(alive)
        aux.stop_ts = ts
        aux.running.clear()
        aux.batch_pending.clear()
        aux.listen_until = 0.0
        self._resolve(state, signals)
        if state.subagents > 0:
            state.turn_active = True  # helpers are still out; not done yet
            return
        duration = max(0.0, ts - state.turn_started_at) if state.turn_started_at else 0.0
        continued = bool(payload.get("stop_hook_active")) and aux.turn_counted
        state.turn_active = False
        state.last_turn_duration = duration
        if not continued:
            state.turns_done += 1
            aux.turn_counted = True
        aux.done_until = now + DONE_SECS
        aux.note = "Done"
        data = {
            "duration": duration,
            "tools": state.turn_tools,
            "errors": state.turn_errors,
            "edits": state.turn_edits,
        }
        if continued:
            data["continued"] = True
        signals.append((Signal.TURN_DONE, data))

    def _on_StopFailure(self, state, payload, ts, now, signals) -> None:
        aux = state._aux
        aux.stop_ts = ts
        aux.running.clear()
        aux.batch_pending.clear()
        aux.listen_until = aux.done_until = 0.0
        self._resolve(state, signals)
        error = payload.get("error")
        error = error if isinstance(error, str) and error else "unknown"
        state.turn_active = False
        if state.turn_started_at:
            state.last_turn_duration = max(0.0, ts - state.turn_started_at)
        aux.failed_until = now + FAILED_SECS
        aux.note = "API error: " + error.replace("_", " ")
        signals.append((Signal.TURN_FAILED, {"error": error}))

    def _on_TaskCompleted(self, state, payload, ts, now, signals) -> None:
        subject = payload.get("task_subject")
        signals.append((Signal.TASK_COMPLETED, {
            "detail": _clip(subject, 60) if isinstance(subject, str) else "",
        }))

    # -- registry ---------------------------------------------------------------
    def _feed_registry(self, entries) -> None:
        if not isinstance(entries, (list, tuple)):
            return
        now = self._clock()
        by_session = {}
        live_pids = set()
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("spare") is True:
                continue
            if entry.get("kind") == "daemon":
                continue  # the supervisor process is not a session
            session_id = entry.get("sessionId")
            if not isinstance(session_id, str) or not session_id:
                continue
            by_session[session_id] = entry
            pid = entry.get("pid")
            if isinstance(pid, int) and not isinstance(pid, bool):
                live_pids.add(pid)

        for session_id, entry in by_session.items():
            signals = []
            state = self._sessions.get(session_id)
            created = False
            if state is None:
                if now - self._ended.get(session_id, -1e18) < TOMBSTONE_SECS:
                    continue  # it just said goodbye; the file is a leftover
                state, replaced = self._rekey(session_id, entry.get("pid"))
                if state is not None:
                    signals.append((Signal.SESSION_START, {"source": "clear", "replaces": replaced}))
                    state._aux.starting_until = now + STARTING_SECS
                else:
                    state = self._create(session_id, now)
                    created = True
                    started = entry.get("startedAt")
                    fresh = (isinstance(started, (int, float)) and not isinstance(started, bool)
                             and now - started / 1000.0 < FRESH_SECS)
                    if fresh:
                        state._aux.starting_until = now + STARTING_SECS
                    signals.append((Signal.SESSION_START, {"source": "startup" if fresh else "discovered"}))
            before = self._signature(state)
            self._apply_registry(state, entry, now, signals, created)
            if not state.ended:
                self._derive(state, now)
            if signals or self._signature(state) != before:
                self._finish(state, signals, now)

        for state in list(self._sessions.values()):
            if state.session_id in by_session:
                continue
            aux = state._aux
            if aux.pending_end:
                continue
            pid_dead = bool(state.pid) and not self._pid_alive(state.pid)
            if aux.in_registry and not pid_dead:
                aux.missing += 1
                if aux.missing < REGISTRY_MISSING_POLLS:
                    continue
            elif not pid_dead:
                continue
            signals = []
            self._end(state, "process_exit", signals, now)
            self._finish(state, signals, now)

    def _apply_registry(self, state, entry, now, signals, created) -> None:
        aux = state._aux
        aux.in_registry = True
        aux.missing = 0
        pid = entry.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 1:
            state.pid = pid
        cwd = entry.get("cwd")
        if isinstance(cwd, str) and cwd and not state.cwd:
            state.cwd = cwd
        if state.cwd and not state.project:
            state.project = _base(state.cwd)
        name = entry.get("name")
        if isinstance(name, str) and name:
            state.name = name
        kind = entry.get("kind")
        if isinstance(kind, str) and kind:
            state.kind = kind
        entrypoint = entry.get("entrypoint")
        if isinstance(entrypoint, str) and entrypoint and not state.entrypoint:
            state.entrypoint = entrypoint
        if state.kind != "interactive" or state.entrypoint.startswith("sdk"):
            state.headless = True
        started = entry.get("startedAt")
        if isinstance(started, (int, float)) and not isinstance(started, bool) and started > 0:
            state.started_at = started / 1000.0

        status = entry.get("status")
        status = status if isinstance(status, str) else ""
        waiting_for = entry.get("waitingFor")
        waiting_for = waiting_for if isinstance(waiting_for, str) else ""
        stamp = entry.get("statusUpdatedAt") or entry.get("updatedAt")
        status_at = stamp / 1000.0 if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else now
        status_at = min(status_at, now)
        previous = aux.reg_status
        aux.reg_status = status
        aux.reg_status_at = status_at
        resting = status in ("idle", "shell", "")

        if state.has_hooks:
            # Safety net: Esc ends a turn without any Stop hook.
            engaged = state.turn_active or aux.running or (
                state.needs_user and state.needs_reason in ("permission", "question", "elicitation"))
            if (engaged and status in ("idle", "shell") and status_at >= aux.last_hook_at - 0.5
                    and now - max(status_at, aux.last_hook_at) > REGISTRY_IDLE_GRACE):
                self._settle_idle(state, now, signals)
                signals.append((Signal.INTERRUPTED, {}))
            return

        # No hooks in this session: the registry is all we have.
        if created:
            if status == "busy":
                state.turn_active = True
                state.turn_started_at = status_at
            elif status == "waiting":
                self._registry_need(state, waiting_for, status_at, signals)
            else:
                state.activity = Activity.IDLE
                state.activity_since = status_at  # may have been idle for hours
            return
        if status == previous:
            if status == "waiting":
                self._registry_need(state, waiting_for, now, signals)
            return
        if previous == "waiting":
            self._resolve(state, signals)
        if status == "busy":
            if not state.turn_active:
                state.turn_active = True
                state.turn_started_at = status_at
                state.turn_tools = state.turn_errors = state.turn_edits = 0
            aux.done_until = aux.failed_until = aux.starting_until = 0.0
        elif status == "waiting":
            self._registry_need(state, waiting_for, now, signals)
        elif resting and state.turn_active:
            duration = max(0.0, status_at - state.turn_started_at) if state.turn_started_at else 0.0
            state.turn_active = False
            state.last_turn_duration = duration
            state.turns_done += 1
            aux.running.clear()
            aux.agents.clear()
            state.subagents = 0
            aux.done_until = now + DONE_SECS
            aux.note = "Done"
            signals.append((Signal.TURN_DONE, {
                "duration": duration, "tools": state.turn_tools,
                "errors": state.turn_errors, "edits": state.turn_edits,
            }))

    def _registry_need(self, state, waiting_for, now, signals) -> None:
        if not waiting_for or waiting_for == "dialog open":
            return  # a menu the user opened themselves; nothing to nag about
        reason = "question" if "input" in waiting_for else "permission"
        self._need(state, reason, _clip(waiting_for, 60), now, signals)

    def _settle_idle(self, state, now, signals) -> None:
        aux = state._aux
        aux.running.clear()
        aux.batch_pending.clear()
        aux.agents.clear()
        state.subagents = 0
        aux.listen_until = aux.done_until = aux.failed_until = 0.0
        aux.compacting_since = 0.0
        state.turn_active = False
        self._resolve(state, signals)

    # -- transcripts ----------------------------------------------------------
    def _set_context(self, state, model, tokens, signals, quiet=False) -> None:
        aux = state._aux
        if isinstance(model, str) and model and not model.startswith("<"):
            state.model = model
        if tokens <= 0:
            return
        state.context_tokens = tokens
        state.context_limit = context_limit_for(state.model, tokens, state.context_limit)
        pct = min(1.0, tokens / float(state.context_limit))
        state.context_pct = pct
        if pct >= CONTEXT_HIGH:
            if not aux.context_high:
                aux.context_high = True
                if not quiet:
                    signals.append((Signal.CONTEXT_HIGH, {"pct": pct}))
        elif pct < CONTEXT_HIGH - 0.05:
            aux.context_high = False

    def _feed_transcript(self, session_id, records, initial) -> None:
        state = self._sessions.get(session_id)
        if state is None or not isinstance(records, (list, tuple)):
            return
        aux = state._aux
        now = self._clock()
        signals = []
        before = (self._signature(state), state.context_pct, state.model)
        drive = not state.has_hooks
        for record in records:
            if not isinstance(record, dict):
                continue
            kind = record.get("kind")
            ts = record.get("ts")
            ts = float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else now
            if kind == "usage":
                tokens = record.get("context_tokens")
                tokens = int(tokens) if isinstance(tokens, (int, float)) and not isinstance(tokens, bool) else 0
                self._set_context(state, record.get("model"), tokens, signals, quiet=initial)
            elif kind == "compact":
                aux.context_high = False
                if drive and not initial:
                    signals.append((Signal.COMPACT_DONE, {}))
            elif kind == "user_prompt":
                text = record.get("text")
                if not isinstance(text, str) or is_machine_prompt(text):
                    continue
                if initial or not drive:
                    if initial and drive:
                        state.last_prompt = snippet(text)
                    continue
                self._on_UserPromptSubmit(state, {"prompt": text}, ts, now, signals)
            elif not drive:
                continue
            elif kind == "tool_use":
                if initial:
                    continue
                self._on_PreToolUse(state, {
                    "tool_name": record.get("tool"), "tool_input": record.get("input"),
                    "tool_use_id": record.get("id"),
                }, max(ts, aux.stop_ts + 1e-6), now, signals)
            elif kind == "tool_result":
                tool_id = record.get("id")
                info = aux.running.get(tool_id) if isinstance(tool_id, str) else None
                if initial or info is None:
                    continue
                payload = {"tool_use_id": tool_id, "tool_name": info.name,
                           "tool_input": {"command": info.key} if info.name == "Bash" else {}}
                if record.get("is_error"):
                    self._on_PostToolUseFailure(state, payload, ts, now, signals)
                else:
                    self._on_PostToolUse(state, payload, ts, now, signals)
        state.last_event_at = now if records and not initial else state.last_event_at
        changed = (self._signature(state), state.context_pct, state.model) != before
        if signals or changed or initial:
            self._finish(state, signals, now)

    # -- time -------------------------------------------------------------------
    def _tick_one(self, state, now) -> None:
        aux = state._aux
        signals = []
        dt = now - aux.last_tick if aux.last_tick else 0.0
        aux.last_tick = now

        if aux.pending_end and now >= aux.pending_end[0]:
            reason = aux.pending_end[1]
            aux.pending_end = None
            self._end(state, reason, signals, now)
            self._finish(state, signals, now)
            return
        if state.pid and now - aux.liveness_at >= LIVENESS_EVERY:
            aux.liveness_at = now
            if not self._pid_alive(state.pid):
                self._end(state, "process_exit", signals, now)
                self._finish(state, signals, now)
                return
        if not state.pid and now - state.last_event_at > STALE_SECS:
            self._end(state, "stale", signals, now)
            self._finish(state, signals, now)
            return

        if aux.batch_pending:
            self._settle_batch(state, now, signals)
        if aux.need_later and now >= aux.need_later[0]:
            _, reason, detail = aux.need_later
            aux.need_later = None
            self._need(state, reason, detail, now, signals)
        if aux.compacting_since and now - aux.compacting_since > COMPACT_TIMEOUT:
            aux.compacting_since = 0.0

        for name, data in signals:
            self._mood.apply(state, name, data, now)
        self._derive(state, now)
        if dt > 0:
            if dt > SUSPEND_GAP and state.working:
                # the machine slept mid-turn: don't bill the nap as work
                state.energy = min(1.0, state.energy + dt / 900.0)
            else:
                self._mood.tick(state, dt, now)
        self._mood.refresh(state, now)
        if signals or self._signature(state) != aux.sig:
            self._notify(state, signals)

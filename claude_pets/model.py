"""Shared data model for Claude Pets.

This module is the contract between the two halves of the program:

* the **session core** (``hook`` client, ``tracker``, ``registry``,
  ``transcript``, ``mood``) which turns Claude Code hook events, the session
  registry and transcripts into a :class:`SessionState` per session, and
* the **desktop side** (``brain``, ``render``, ``overlay``, ``daemon``) which
  turns a :class:`SessionState` into a living pet.

Wire protocol (v1)
------------------
The daemon listens on a ``SOCK_STREAM`` UNIX socket at ``paths.SOCKET_PATH``.
A client connects, writes exactly one line of JSON (UTF-8, ``\\n`` terminated)
and may read one line of JSON back.

Hook event (no reply is sent, the client just closes)::

    {"type": "hook", "v": 1, "ts": 1791296594.95,
     "meta": {"pid": 998379, "tty": "/dev/pts/6", "entrypoint": "cli", ...},
     "payload": { ...the hook's stdin JSON, trimmed... }}

Control command (one JSON line is sent back)::

    {"type": "cmd", "v": 1, "cmd": "status", "args": {}}
    -> {"ok": true, ...}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

PROTOCOL_VERSION = 1


class Activity:
    """What a session is *doing* right now."""

    STARTING = "starting"      # session just opened
    IDLE = "idle"              # waiting for the user's next prompt
    LISTENING = "listening"    # a prompt was just submitted (brief)
    THINKING = "thinking"      # model is generating / between tools
    READING = "reading"        # Read, NotebookRead
    SEARCHING = "searching"    # Grep, Glob, LS, ToolSearch
    WRITING = "writing"        # Edit, Write, NotebookEdit
    RUNNING = "running"        # Bash and other shell-like tools
    TESTING = "testing"        # Bash that is a test / build / lint run
    BROWSING = "browsing"      # WebFetch, WebSearch, browser tools
    DELEGATING = "delegating"  # Agent / Task subagents are at work
    PLANNING = "planning"      # TodoWrite, Task*, plan mode
    TOOL = "tool"              # any other tool (MCP etc.)
    ASKING = "asking"          # AskUserQuestion / elicitation: needs the user
    WAITING = "waiting"        # permission prompt: needs the user
    COMPACTING = "compacting"  # context is being compacted
    DONE = "done"              # turn just finished fine (brief, then IDLE)
    FAILED = "failed"          # turn ended with an API error
    ENDED = "ended"            # session closed

    ALL = (
        STARTING, IDLE, LISTENING, THINKING, READING, SEARCHING, WRITING,
        RUNNING, TESTING, BROWSING, DELEGATING, PLANNING, TOOL, ASKING,
        WAITING, COMPACTING, DONE, FAILED, ENDED,
    )
    #: The session is busy on the user's behalf.
    WORKING = frozenset({
        LISTENING, THINKING, READING, SEARCHING, WRITING, RUNNING, TESTING,
        BROWSING, DELEGATING, PLANNING, TOOL, COMPACTING,
    })
    #: The session is blocked until the user does something.
    NEEDS_USER = frozenset({ASKING, WAITING})


class Signal:
    """One-shot events delivered next to a state update (animation triggers).

    Each signal is a ``(name, data)`` tuple; ``data`` is a small dict whose
    keys are listed next to each name.
    """

    SESSION_START = "session_start"      # source: startup|resume|clear|compact|discovered
    SESSION_END = "session_end"          # reason
    PROMPT = "prompt"                    # sentiment: praise|frustrated|neutral, snippet
    TOOL_START = "tool_start"            # tool, activity, detail
    TOOL_OK = "tool_ok"                  # tool, streak
    TOOL_ERROR = "tool_error"            # tool, streak, detail
    TESTS_PASSED = "tests_passed"        # detail
    TESTS_FAILED = "tests_failed"        # detail
    COMMIT = "commit"                    # detail
    NEEDS_USER = "needs_user"            # reason: permission|question|idle|elicitation, detail
    USER_RESPONDED = "user_responded"    # reason
    PERMISSION_DENIED = "permission_denied"  # tool
    TURN_DONE = "turn_done"              # duration, tools, errors, edits
    TURN_FAILED = "turn_failed"          # error
    INTERRUPTED = "interrupted"
    SUBAGENT_START = "subagent_start"    # agent_type, count
    SUBAGENT_STOP = "subagent_stop"      # agent_type, count
    COMPACT_START = "compact_start"      # trigger: manual|auto
    COMPACT_DONE = "compact_done"
    TASK_COMPLETED = "task_completed"    # detail
    CONTEXT_HIGH = "context_high"        # pct (crossed 0.8 going up)

    ALL = (
        SESSION_START, SESSION_END, PROMPT, TOOL_START, TOOL_OK, TOOL_ERROR,
        TESTS_PASSED, TESTS_FAILED, COMMIT, NEEDS_USER, USER_RESPONDED,
        PERMISSION_DENIED, TURN_DONE, TURN_FAILED, INTERRUPTED,
        SUBAGENT_START, SUBAGENT_STOP, COMPACT_START, COMPACT_DONE,
        TASK_COMPLETED, CONTEXT_HIGH,
    )


class Emotion:
    """How a session is *feeling* — the mood engine's summary label."""

    CONTENT = "content"        # neutral, at ease
    HAPPY = "happy"            # things are going well
    JOYFUL = "joyful"          # just succeeded / got praised
    PROUD = "proud"            # long clean streak or finished a big turn
    FOCUSED = "focused"        # deep in a long uninterrupted work run
    CURIOUS = "curious"        # exploring (reading / searching / browsing a lot)
    DETERMINED = "determined"  # user is unhappy or errors happened; pushing through
    TIRED = "tired"            # low energy after a long stretch of work
    SLEEPY = "sleepy"          # idle for a long time
    BORED = "bored"            # idle for a while, nothing to do
    STRESSED = "stressed"      # errors piling up, context nearly full
    FRUSTRATED = "frustrated"  # repeated failures in a row
    SAD = "sad"                # turn failed, got scolded, denied
    ANXIOUS = "anxious"        # has been waiting on the user for a long time
    SICK = "sick"              # API errors
    STUFFED = "stuffed"        # context window almost full

    ALL = (
        CONTENT, HAPPY, JOYFUL, PROUD, FOCUSED, CURIOUS, DETERMINED, TIRED,
        SLEEPY, BORED, STRESSED, FRUSTRATED, SAD, ANXIOUS, SICK, STUFFED,
    )


@dataclass
class SessionState:
    """Everything the desktop side needs to know about one Claude Code session."""

    session_id: str
    pid: Optional[int] = None
    cwd: str = ""
    project: str = ""            # display name of the project (basename of cwd)
    name: str = ""               # Claude Code's own session name from the registry ("pet-8f")
    kind: str = "interactive"    # registry "kind"
    entrypoint: str = ""         # CLAUDE_CODE_ENTRYPOINT ("cli", "sdk-cli", ...)
    headless: bool = False       # non-interactive (`claude -p` / SDK) session
    transcript_path: str = ""
    model: str = ""
    permission_mode: str = ""
    has_hooks: bool = False      # we have received at least one hook event for it
    started_at: float = 0.0      # epoch seconds
    last_event_at: float = 0.0   # epoch seconds of the last thing we learned

    # --- doing ---------------------------------------------------------
    activity: str = Activity.STARTING
    activity_since: float = 0.0
    detail: str = ""             # short human text for the speech bubble: "Editing server.ts"
    tool: str = ""               # tool currently running ("" when none)
    tool_target: str = ""        # file basename / command head / host / query
    needs_user: bool = False
    needs_reason: str = ""       # permission | question | idle | elicitation
    needs_detail: str = ""       # e.g. "Bash: rm -rf build"
    needs_since: float = 0.0
    subagents: int = 0           # subagents active right now

    # --- current / last turn ------------------------------------------
    turn_active: bool = False
    turn_started_at: float = 0.0
    turn_tools: int = 0
    turn_errors: int = 0
    turn_edits: int = 0
    last_turn_duration: float = 0.0
    last_prompt: str = ""        # snippet (<= 80 chars) of the latest user prompt

    # --- totals for this session --------------------------------------
    prompts: int = 0
    tools_ok: int = 0
    tools_failed: int = 0
    edits: int = 0
    commands: int = 0
    turns_done: int = 0
    ok_streak: int = 0
    error_streak: int = 0

    # --- context window -----------------------------------------------
    context_tokens: int = 0
    context_limit: int = 0
    context_pct: Optional[float] = None   # 0..1, None while unknown

    # --- feeling (maintained by the mood engine) ------------------------
    energy: float = 1.0          # 0 exhausted .. 1 fresh
    mood: float = 0.6            # 0 miserable .. 0.5 neutral .. 1 delighted
    stress: float = 0.0          # 0 calm .. 1 frazzled
    focus: float = 0.0           # 0 scattered .. 1 in the zone
    emotion: str = Emotion.CONTENT

    # --- where it lives (for "focus the terminal") ----------------------
    term: dict = field(default_factory=dict)
    # keys (all optional): tty, term_program, term, kitty_window_id,
    # kitty_listen_on, tmux, tmux_pane, wezterm_pane, windowid, vscode, ssh

    ended: bool = False

    @property
    def working(self) -> bool:
        return self.activity in Activity.WORKING

    def to_dict(self) -> dict:
        return asdict(self)

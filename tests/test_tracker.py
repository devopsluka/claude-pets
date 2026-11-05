import json
import unittest

from test_support import Harness, fixture, registry_entry, session_fixture

from claude_pets.hook import trim_payload
from claude_pets.model import Activity, Emotion, Signal
from claude_pets.tracker import (
    classify_sentiment, classify_tool, command_head, is_machine_prompt, shell_kind, snippet,
)


class BasicTurnTest(unittest.TestCase):
    def test_full_turn(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        self.assertEqual(st.activity, Activity.STARTING)
        self.assertTrue(st.has_hooks)
        self.assertEqual(st.project, "demo")
        self.assertEqual(st.pid, 4242)
        self.assertEqual(h.rec.data(Signal.SESSION_START), [{"source": "startup"}])

        st = h.hook("UserPromptSubmit", prompt="please fix the login bug in auth.ts\nthanks in advance")
        self.assertEqual(st.activity, Activity.LISTENING)
        self.assertTrue(st.turn_active)
        self.assertEqual(st.prompts, 1)
        self.assertEqual(st.last_prompt, "please fix the login bug in auth.ts thanks in advance")
        self.assertEqual(h.rec.data(Signal.PROMPT)[0]["sentiment"], "praise")

        h.tick(2)
        self.assertEqual(st.activity, Activity.THINKING)

        h.hook("PreToolUse", tool_name="Read", tool_use_id="t1", tool_input={"file_path": "/x/src/auth.ts"})
        self.assertEqual((st.activity, st.detail, st.tool, st.tool_target),
                         (Activity.READING, "Reading auth.ts", "Read", "auth.ts"))
        h.hook("PostToolUse", tool_name="Read", tool_use_id="t1", tool_input={"file_path": "/x/src/auth.ts"},
               tool_response={"type": "text"})
        self.assertEqual(st.activity, Activity.THINKING)
        self.assertEqual((st.tools_ok, st.ok_streak, st.turn_tools), (1, 1, 1))

        h.hook("PreToolUse", tool_name="Edit", tool_use_id="t2",
               tool_input={"file_path": "/x/src/auth.ts", "old_string": "a" * 5000, "new_string": "b"})
        self.assertEqual((st.activity, st.detail), (Activity.WRITING, "Editing auth.ts"))
        h.hook("PostToolUse", tool_name="Edit", tool_use_id="t2", tool_input={"file_path": "/x/src/auth.ts"})
        self.assertEqual((st.edits, st.turn_edits), (1, 1))

        h.clock.advance(30)
        h.hook("Stop", stop_hook_active=False, background_tasks=[])
        self.assertEqual(st.activity, Activity.DONE)
        self.assertFalse(st.turn_active)
        self.assertEqual(st.turns_done, 1)
        done = h.rec.data(Signal.TURN_DONE)[0]
        self.assertEqual((done["tools"], done["errors"], done["edits"]), (2, 0, 1))
        self.assertAlmostEqual(done["duration"], 32.0, delta=0.01)
        self.assertEqual(st.emotion, Emotion.JOYFUL)

        h.tick(7)
        self.assertEqual(st.activity, Activity.IDLE)

    def test_starting_settles_to_idle_without_prompt(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.tick(9)
        self.assertEqual(st.activity, Activity.IDLE)

    def test_unknown_session_is_created_on_the_fly(self):
        h = Harness()
        st = h.hook("PreToolUse", tool_name="Grep", tool_use_id="t1", tool_input={"pattern": "TODO"})
        self.assertTrue(st.has_hooks)
        self.assertEqual(st.activity, Activity.SEARCHING)
        self.assertEqual(st.detail, "Searching for “TODO”")
        self.assertEqual(h.rec.data(Signal.SESSION_START), [{"source": "discovered"}])

    def test_headless_flag(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup", meta={"pid": 9, "entrypoint": "sdk-cli", "attended": "0"})
        self.assertTrue(st.headless)

    def test_malformed_input_never_raises(self):
        h = Harness()
        for junk in (None, 3, "x", {}, {"payload": 1}, {"payload": {}}, {"payload": {"session_id": 5}},
                     {"payload": {"session_id": "s", "hook_event_name": ["x"]}},
                     {"payload": {"session_id": "s", "hook_event_name": "PreToolUse", "tool_input": "zz",
                                  "tool_use_id": {"a": 1}}, "meta": "nope", "ts": "soon"},
                     {"payload": {"session_id": "s", "hook_event_name": "PostToolBatch", "tool_calls": [1, None]}},
                     {"payload": {"session_id": "s", "hook_event_name": "Stop", "background_tasks": [3, {}]}},
                     {"payload": {"session_id": "s", "hook_event_name": "__init__"}}):
            h.tracker.feed_hook(junk)
        h.tracker.feed_registry("nope")
        h.tracker.feed_registry([None, 3, {"sessionId": 4}, {"sessionId": "r", "pid": "x", "startedAt": "y",
                                                             "statusUpdatedAt": []}])
        h.tracker.feed_transcript("s", [None, {"kind": "usage", "context_tokens": "many"}, {"kind": 4}])
        h.tracker.feed_transcript("nope", None)
        h.tick(3)

    def test_unknown_event_only_refreshes(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.rec.clear()
        h.clock.advance(5)
        h.hook("CwdChanged", old_cwd="/a", new_cwd="/b")
        self.assertEqual(st.last_event_at, h.clock())
        self.assertEqual(h.rec.calls, [])


class ToolBookkeepingTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.h.hook("SessionStart", source="startup")
        self.st = self.h.hook("UserPromptSubmit", prompt="go")
        self.h.tick(2)

    def test_parallel_tools(self):
        h, st = self.h, self.st
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="a", tool_input={"command": "sleep 5", "description": "Wait a bit"})
        h.hook("PreToolUse", tool_name="Read", tool_use_id="b", tool_input={"file_path": "/x/README.md"})
        self.assertEqual(st.detail, "Reading README.md")
        h.hook("PostToolUse", tool_name="Read", tool_use_id="b")
        self.assertEqual((st.activity, st.detail), (Activity.RUNNING, "Wait a bit"))
        h.hook("PostToolUse", tool_name="Bash", tool_use_id="a", tool_input={"command": "sleep 5"})
        self.assertEqual(st.activity, Activity.THINKING)
        self.assertEqual(st.commands, 1)

    def test_post_overtakes_pre(self):
        h, st = self.h, self.st
        h.hook("PostToolUse", tool_name="Read", tool_use_id="late")
        h.hook("PreToolUse", tool_name="Read", tool_use_id="late", tool_input={"file_path": "/x/a.py"})
        self.assertEqual(st.activity, Activity.THINKING)
        self.assertEqual(st.tools_ok, 1)

    def test_failures_build_a_streak(self):
        h, st = self.h, self.st
        for i in range(3):
            h.hook("PreToolUse", tool_name="Bash", tool_use_id="f%d" % i, tool_input={"command": "false"})
            h.hook("PostToolUseFailure", tool_name="Bash", tool_use_id="f%d" % i,
                   tool_input={"command": "false"}, error="Exit code 1", is_interrupt=False)
        self.assertEqual((st.tools_failed, st.error_streak, st.ok_streak, st.turn_errors), (3, 3, 0, 3))
        self.assertEqual([d["streak"] for d in h.rec.data(Signal.TOOL_ERROR)], [1, 2, 3])
        self.assertEqual(h.rec.data(Signal.TOOL_ERROR)[0]["detail"], "Exit code 1")
        self.assertEqual(st.emotion, Emotion.FRUSTRATED)
        h.hook("PostToolUse", tool_name="Read", tool_use_id="ok")
        self.assertEqual((st.error_streak, st.ok_streak), (0, 1))

    def test_interrupt_is_not_an_error(self):
        h, st = self.h, self.st
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="i", tool_input={"command": "sleep 99"})
        h.hook("PostToolUseFailure", tool_name="Bash", tool_use_id="i", error="interrupted", is_interrupt=True)
        self.assertEqual(st.tools_failed, 0)
        self.assertIn(Signal.INTERRUPTED, h.rec.names())

    def test_tests_and_commits(self):
        h, st = self.h, self.st
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="p", tool_input={"command": "python3 -m pytest -q tests/"})
        self.assertEqual((st.activity, st.detail), (Activity.TESTING, "Running tests"))
        h.hook("PostToolUse", tool_name="Bash", tool_use_id="p", tool_input={"command": "python3 -m pytest -q tests/"})
        self.assertEqual(h.rec.data(Signal.TESTS_PASSED), [{"detail": "Tests passed"}])
        h.hook("PostToolUseFailure", tool_name="Bash", tool_use_id="q", tool_input={"command": "npm run build"},
               error="Exit code 2")
        self.assertEqual(h.rec.data(Signal.TESTS_FAILED), [{"detail": "Build failed"}])
        h.hook("PostToolUse", tool_name="Bash", tool_use_id="c",
               tool_input={"command": "git add -A && git commit -m 'fix: login'"})
        self.assertEqual(len(h.rec.data(Signal.COMMIT)), 1)

    def test_stale_tool_events_after_stop(self):
        h, st = self.h, self.st
        early = h.clock()
        h.clock.advance(2)
        h.hook("Stop", stop_hook_active=False)
        h.hook("PreToolUse", tool_name="Read", tool_use_id="z", tool_input={"file_path": "/x/a"}, ts=early)
        h.hook("PostToolUse", tool_name="Read", tool_use_id="z", ts=early)
        self.assertEqual(st.activity, Activity.DONE)
        self.assertFalse(st.turn_active)
        self.assertEqual(st.tools_ok, 1)

    def test_stop_older_than_next_prompt_is_ignored(self):
        h, st = self.h, self.st
        stop_ts = h.clock()
        h.clock.advance(0.01)
        h.hook("UserPromptSubmit", prompt="<task-notification>\n<task-id>a1</task-id>")
        h.hook("Stop", stop_hook_active=False, ts=stop_ts)
        self.assertTrue(st.turn_active)
        self.assertEqual(st.turns_done, 0)
        self.assertEqual(st.activity, Activity.THINKING)

    def test_reentrant_stop_is_not_double_counted(self):
        h, st = self.h, self.st
        h.hook("Stop", stop_hook_active=False)
        h.clock.advance(1)
        h.hook("PreToolUse", tool_name="Read", tool_use_id="again", tool_input={"file_path": "/x/a"})
        self.assertTrue(st.turn_active)
        h.hook("PostToolUse", tool_name="Read", tool_use_id="again")
        h.clock.advance(1)
        h.hook("Stop", stop_hook_active=True)
        self.assertEqual(st.turns_done, 1)
        self.assertEqual([d.get("continued", False) for d in h.rec.data(Signal.TURN_DONE)], [False, True])

    def test_stop_failure(self):
        h, st = self.h, self.st
        h.hook("StopFailure", error="rate_limit", error_details="429")
        self.assertEqual((st.activity, st.detail), (Activity.FAILED, "API error: rate limit"))
        self.assertEqual(h.rec.data(Signal.TURN_FAILED), [{"error": "rate_limit"}])
        self.assertEqual(st.emotion, Emotion.SICK)
        h.tick(21)
        self.assertEqual(st.activity, Activity.IDLE)

    def test_compaction(self):
        h, st = self.h, self.st
        h.hook("PreCompact", trigger="auto", custom_instructions=None)
        self.assertEqual(st.activity, Activity.COMPACTING)
        self.assertEqual(h.rec.data(Signal.COMPACT_START), [{"trigger": "auto"}])
        h.hook("PostCompact", trigger="auto", compact_summary="x" * 9000)
        self.assertEqual(st.activity, Activity.THINKING)
        h.hook("SessionStart", source="compact")
        self.assertEqual(len(h.rec.data(Signal.COMPACT_DONE)), 1)
        self.assertEqual(len(h.rec.data(Signal.SESSION_START)), 1)

    def test_task_completed(self):
        self.h.hook("TaskCompleted", task_id="3", task_subject="Write the tests")
        self.assertEqual(self.h.rec.data(Signal.TASK_COMPLETED), [{"detail": "Write the tests"}])


class NeedsUserTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.h.hook("SessionStart", source="startup")
        self.st = self.h.hook("UserPromptSubmit", prompt="go")
        self.h.tick(2)

    def test_permission_approved(self):
        h, st = self.h, self.st
        ti = {"command": "rm -rf build", "description": "Remove the build dir"}
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="p1", tool_input=ti)
        h.hook("PermissionRequest", tool_name="Bash", tool_input=ti, permission_suggestions=[])
        self.assertEqual(st.activity, Activity.WAITING)
        self.assertEqual((st.needs_user, st.needs_reason, st.needs_detail), (True, "permission", "Bash: rm"))
        self.assertEqual(h.rec.data(Signal.NEEDS_USER), [{"reason": "permission", "detail": "Bash: rm"}])
        # an unrelated parallel tool finishing does not answer the prompt
        h.hook("PostToolUse", tool_name="Read", tool_use_id="other", tool_input={"file_path": "/x/a"})
        self.assertTrue(st.needs_user)
        h.tick(200)
        self.assertEqual(st.emotion, Emotion.ANXIOUS)
        h.hook("PostToolUse", tool_name="Bash", tool_use_id="p1", tool_input=ti)
        self.assertFalse(st.needs_user)
        self.assertEqual(h.rec.data(Signal.USER_RESPONDED), [{"reason": "permission"}])
        self.assertEqual(st.activity, Activity.THINKING)

    def test_permission_denied_shows_up_as_batch_leftover(self):
        h, st = self.h, self.st
        ti = {"command": "ls /nope"}
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="p1", tool_input=ti)
        h.hook("PermissionRequest", tool_name="Bash", tool_input=ti)
        self.assertEqual(st.activity, Activity.WAITING)
        h.clock.advance(5)
        h.hook("PostToolBatch", tool_calls=[{"tool_name": "Bash", "tool_use_id": "p1", "tool_response": "denied"}])
        h.tick(1)
        self.assertFalse(st.needs_user)
        self.assertEqual(st.activity, Activity.THINKING)
        self.assertEqual(h.rec.data(Signal.PERMISSION_DENIED), [{"tool": "Bash"}])
        self.assertEqual((st.tools_ok, st.tools_failed), (0, 0))

    def test_batch_does_not_misjudge_slow_async_post(self):
        h, st = self.h, self.st
        h.hook("PreToolUse", tool_name="Read", tool_use_id="r1", tool_input={"file_path": "/x/a"})
        h.hook("PostToolBatch", tool_calls=[{"tool_name": "Read", "tool_use_id": "r1"}])
        h.clock.advance(0.1)
        h.hook("PostToolUse", tool_name="Read", tool_use_id="r1")
        h.tick(2)
        self.assertEqual(st.tools_ok, 1)
        self.assertNotIn(Signal.PERMISSION_DENIED, h.rec.names())

    def test_permission_denied_event(self):
        h, st = self.h, self.st
        payload = fixture("synthetic/PermissionDenied")
        h.hook("PreToolUse", tool_name="Bash", tool_use_id=payload["tool_use_id"], tool_input=payload["tool_input"])
        h.tracker.feed_hook({"type": "hook", "ts": h.clock(), "meta": {"pid": 4242},
                             "payload": trim_payload(dict(payload, session_id="s1"))})
        self.assertEqual(h.rec.data(Signal.PERMISSION_DENIED), [{"tool": "Bash"}])
        self.assertEqual(st.activity, Activity.THINKING)

    def test_headless_permission_requests_get_a_grace_period(self):
        h = Harness()
        meta = {"pid": 77, "entrypoint": "sdk-cli", "attended": "0"}
        h.hook("SessionStart", sid="h1", meta=meta, source="startup")
        st = h.hook("UserPromptSubmit", sid="h1", meta=meta, prompt="go")
        h.hook("PreToolUse", sid="h1", meta=meta, tool_name="Bash", tool_use_id="p", tool_input={"command": "ls /nope"})
        h.hook("PermissionRequest", sid="h1", meta=meta, tool_name="Bash", tool_input={"command": "ls /nope"})
        self.assertFalse(st.needs_user)
        h.hook("PostToolBatch", sid="h1", meta=meta, tool_calls=[{"tool_name": "Bash", "tool_use_id": "p"}])
        h.tick(2)
        self.assertNotIn(Signal.NEEDS_USER, h.rec.names())
        self.assertEqual(h.rec.data(Signal.PERMISSION_DENIED), [{"tool": "Bash"}])
        # ... but a request that really blocks does surface
        h.hook("PreToolUse", sid="h1", meta=meta, tool_name="Bash", tool_use_id="q", tool_input={"command": "ls /x"})
        h.hook("PermissionRequest", sid="h1", meta=meta, tool_name="Bash", tool_input={"command": "ls /x"})
        h.tick(2)
        self.assertTrue(st.needs_user)
        self.assertEqual(st.activity, Activity.WAITING)

    def test_ask_user_question(self):
        h, st = self.h, self.st
        h.hook("PreToolUse", tool_name="AskUserQuestion", tool_use_id="q1", tool_input={"questions": [{"q": 1}]})
        self.assertEqual((st.activity, st.needs_reason), (Activity.ASKING, "question"))
        h.hook("PostToolUse", tool_name="AskUserQuestion", tool_use_id="q1", tool_input={"questions": [{"q": 1}]})
        self.assertFalse(st.needs_user)

    def test_notifications(self):
        h, st = self.h, self.st
        h.hook("Stop", stop_hook_active=False)
        h.tick(7)
        h.hook("Notification", message="Claude is waiting for your input", notification_type="idle_prompt")
        self.assertEqual((st.activity, st.needs_user, st.needs_reason), (Activity.IDLE, True, "idle"))
        h.hook("Notification", message="x", notification_type="auth_success")
        h.hook("UserPromptSubmit", prompt="next")
        self.assertFalse(st.needs_user)
        h.hook("Notification", message="Claude needs your permission to use Bash", notification_type="permission_prompt")
        self.assertEqual((st.activity, st.needs_reason), (Activity.WAITING, "permission"))

    def test_elicitation(self):
        h, st = self.h, self.st
        h.hook("Elicitation", mcp_server_name="github", message="Which repo?")
        self.assertEqual((st.activity, st.needs_reason, st.needs_detail), (Activity.ASKING, "elicitation", "github"))
        h.hook("ElicitationResult", mcp_server_name="github", action="accept")
        self.assertFalse(st.needs_user)

    def test_next_tool_on_same_thread_answers_a_stuck_request(self):
        h, st = self.h, self.st
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="p1", tool_input={"command": "make deploy"})
        h.hook("PermissionRequest", tool_name="Bash", tool_input={"command": "make deploy"})
        h.clock.advance(10)
        h.hook("PreToolUse", tool_name="Read", tool_use_id="r9", tool_input={"file_path": "/x/a"}, agent_id="sub1")
        self.assertTrue(st.needs_user)  # a helper's tool says nothing about the main thread
        h.hook("PreToolUse", tool_name="Read", tool_use_id="r10", tool_input={"file_path": "/x/a"})
        self.assertFalse(st.needs_user)


class SubagentTest(unittest.TestCase):
    def test_background_helpers_keep_the_turn_open(self):
        h = Harness()
        h.hook("SessionStart", source="startup")
        st = h.hook("UserPromptSubmit", prompt="research this")
        h.hook("PreToolUse", tool_name="Agent", tool_use_id="a1",
               tool_input={"description": "Survey the docs", "subagent_type": "general-purpose", "prompt": "x"})
        self.assertEqual((st.activity, st.detail), (Activity.DELEGATING, "Delegating: Survey the docs"))
        h.hook("SubagentStart", agent_id="sub1", agent_type="general-purpose")
        self.assertEqual(st.subagents, 1)
        h.hook("PostToolUse", tool_name="Agent", tool_use_id="a1", tool_response={"isAsync": True})
        self.assertEqual((st.activity, st.detail), (Activity.DELEGATING, "1 helper at work"))
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="s1", tool_input={"command": "echo sub"},
               agent_id="sub1", agent_type="general-purpose")
        self.assertEqual(st.activity, Activity.DELEGATING)
        self.assertTrue(h.rec.data(Signal.TOOL_START)[-1]["agent"])
        h.hook("PreToolUse", tool_name="Read", tool_use_id="m1", tool_input={"file_path": "/x/notes.txt"})
        self.assertEqual(st.detail, "Reading notes.txt")  # the main thread's own work shows
        h.hook("PostToolUse", tool_name="Read", tool_use_id="m1")
        h.hook("PostToolUse", tool_name="Bash", tool_use_id="s1", agent_id="sub1", agent_type="general-purpose")
        self.assertEqual(st.tools_ok, 3)
        h.clock.advance(3)
        h.hook("Stop", stop_hook_active=False,
               background_tasks=[{"id": "sub1", "type": "subagent", "status": "running"}])
        self.assertTrue(st.turn_active)
        self.assertEqual(st.activity, Activity.DELEGATING)
        self.assertNotIn(Signal.TURN_DONE, h.rec.names())
        h.hook("SubagentStop", agent_id="sub1", agent_type="general-purpose", stop_hook_active=False)
        self.assertEqual(st.subagents, 0)
        self.assertEqual([d["count"] for d in h.rec.data(Signal.SUBAGENT_STOP)], [0])
        h.hook("UserPromptSubmit", prompt="<task-notification>\n<task-id>sub1</task-id>")
        self.assertEqual(st.activity, Activity.THINKING)
        self.assertEqual(st.prompts, 1)
        self.assertEqual(len(h.rec.data(Signal.PROMPT)), 1)
        h.clock.advance(2)
        h.hook("Stop", stop_hook_active=False, background_tasks=[])
        self.assertEqual(st.activity, Activity.DONE)
        self.assertEqual(st.turns_done, 1)
        self.assertAlmostEqual(h.rec.data(Signal.TURN_DONE)[0]["duration"], 5.0, delta=0.01)

    def test_stop_resyncs_a_drifted_helper_count(self):
        h = Harness()
        st = h.hook("UserPromptSubmit", prompt="go")
        h.hook("SubagentStart", agent_id="lost", agent_type="Explore")
        h.hook("Stop", stop_hook_active=False, background_tasks=[])
        self.assertEqual(st.subagents, 0)
        self.assertEqual(st.activity, Activity.DONE)
        h.hook("SubagentStop", agent_id="lost", agent_type="Explore")
        self.assertEqual(st.subagents, 0)


class LifecycleTest(unittest.TestCase):
    def test_clear_rekeys_the_same_state(self):
        h = Harness()
        st = h.hook("SessionStart", sid="old", source="startup")
        h.hook("UserPromptSubmit", sid="old", prompt="thanks, great job")
        h.hook("Stop", sid="old", stop_hook_active=False)
        mood = st.mood
        h.hook("SessionEnd", sid="old", reason="clear")
        self.assertFalse(st.ended)
        self.assertIs(h.tracker.get("old"), st)
        h.rec.clear()
        st2 = h.hook("SessionStart", sid="new", source="clear")
        self.assertIs(st2, st)
        self.assertIsNone(h.tracker.get("old"))
        self.assertEqual(st.session_id, "new")
        self.assertEqual(h.rec.data(Signal.SESSION_START), [{"source": "clear", "replaces": "old"}])
        self.assertNotIn(Signal.SESSION_END, h.rec.names())
        self.assertEqual(st.mood, mood)
        self.assertEqual(st.transcript_path, "/home/user/.claude/projects/-home-user-projects-demo/new.jsonl")
        h.tick(10)
        self.assertFalse(st.ended)
        self.assertEqual(len(h.tracker.all()), 1)

    def test_clear_without_follow_up_ends(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.hook("SessionEnd", reason="clear")
        h.tick(6)
        self.assertTrue(st.ended)
        self.assertEqual(h.rec.data(Signal.SESSION_END), [{"reason": "clear"}])
        self.assertEqual(h.tracker.all(), [])

    def test_session_end_drops_and_leaves_a_tombstone(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.hook("SessionEnd", reason="prompt_input_exit")
        self.assertTrue(st.ended)
        self.assertEqual(st.activity, Activity.ENDED)
        self.assertEqual(h.rec.calls[-1][1], Activity.ENDED)
        self.assertIsNone(h.tracker.get("s1"))
        h.tracker.feed_registry([registry_entry(clock=h.clock)])  # the file lingers a moment
        self.assertEqual(h.tracker.all(), [])
        h.clock.advance(40)
        h.tracker.feed_registry([registry_entry(clock=h.clock)])
        self.assertEqual(len(h.tracker.all()), 1)

    def test_dead_process_ends_the_session(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.dead.add(4242)
        h.tick(4)
        self.assertTrue(st.ended)
        self.assertEqual(h.rec.data(Signal.SESSION_END), [{"reason": "process_exit"}])

    def test_tick_only_notifies_on_change(self):
        h = Harness()
        h.hook("SessionStart", source="startup")
        h.tick(9)   # STARTING -> IDLE
        h.rec.clear()
        h.tick(60)
        self.assertEqual(h.rec.calls, [])
        h.tick(200)  # ... until boredom sets in
        self.assertEqual([c[1] for c in h.rec.calls], [Activity.IDLE])
        self.assertEqual(h.state().emotion, Emotion.BORED)

    def test_nudge(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.rec.clear()
        before = st.mood
        h.tracker.nudge("s1", mood=0.2, stress=5)
        self.assertAlmostEqual(st.mood, before + 0.2)
        self.assertEqual(st.stress, 1.0)
        self.assertEqual(len(h.rec.calls), 1)
        h.tracker.nudge("missing", mood=1)


class RegistryFeedTest(unittest.TestCase):
    def test_discovery_and_hookless_turns(self):
        h = Harness()
        idle_since = h.clock() - 900
        entry = registry_entry(clock=h.clock, statusUpdatedAt=int(idle_since * 1000))
        h.tracker.feed_registry([entry])
        st = h.state()
        self.assertEqual(h.rec.data(Signal.SESSION_START), [{"source": "discovered"}])
        self.assertEqual((st.activity, st.name, st.project, st.pid, st.has_hooks),
                         (Activity.IDLE, "demo-1a", "demo", 4242, False))
        self.assertEqual(st.activity_since, idle_since)
        h.tick(1)
        self.assertEqual(st.emotion, Emotion.SLEEPY)  # it has been idle for 15 minutes already

        h.clock.advance(5)
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="busy")])
        self.assertEqual(st.activity, Activity.THINKING)
        h.clock.advance(20)
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="waiting", waitingFor="input needed")])
        self.assertEqual((st.activity, st.needs_reason), (Activity.ASKING, "question"))
        h.clock.advance(3)
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="busy")])
        self.assertFalse(st.needs_user)
        h.clock.advance(10)
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="shell")])
        self.assertEqual(st.activity, Activity.DONE)
        self.assertEqual(st.turns_done, 1)
        self.assertAlmostEqual(h.rec.data(Signal.TURN_DONE)[0]["duration"], 33.0, delta=0.01)

    def test_user_opened_dialog_is_not_a_need(self):
        h = Harness()
        h.tracker.feed_registry([registry_entry(clock=h.clock)])
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="waiting", waitingFor="dialog open")])
        self.assertFalse(h.state().needs_user)

    def test_fresh_entry_counts_as_startup_and_hook_does_not_repeat_it(self):
        h = Harness()
        entry = registry_entry(clock=h.clock, startedAt=int(h.clock() * 1000) - 800, status="idle")
        h.tracker.feed_registry([entry])
        st = h.state()
        self.assertEqual(st.activity, Activity.STARTING)
        h.clock.advance(0.5)
        h.hook("SessionStart", source="startup")
        self.assertEqual(h.rec.data(Signal.SESSION_START), [{"source": "startup"}])
        self.assertTrue(st.has_hooks)

    def test_spares_and_daemons_are_ignored_and_bg_is_headless(self):
        h = Harness()
        h.tracker.feed_registry([
            registry_entry(sid="spare", pid=1, clock=h.clock, spare=True),
            registry_entry(sid="daemon", pid=2, clock=h.clock, kind="daemon"),
            registry_entry(sid="bg", pid=3, clock=h.clock, kind="bg"),
            registry_entry(sid="sdk", pid=4, clock=h.clock, entrypoint="sdk-cli"),
        ])
        self.assertEqual(sorted(s.session_id for s in h.tracker.all()), ["bg", "sdk"])
        self.assertTrue(h.state("bg").headless)
        self.assertTrue(h.state("sdk").headless)

    def test_vanished_entries(self):
        h = Harness()
        h.tracker.feed_registry([registry_entry(clock=h.clock)])
        st = h.state()
        h.tracker.feed_registry([])     # a hiccup: the process is still alive
        h.tracker.feed_registry([])
        self.assertFalse(st.ended)
        h.tracker.feed_registry([registry_entry(clock=h.clock)])
        h.tracker.feed_registry([])
        h.tracker.feed_registry([])
        self.assertFalse(st.ended)      # the counter was reset when it came back
        h.dead.add(4242)
        h.tracker.feed_registry([])
        self.assertTrue(st.ended)
        self.assertEqual(h.rec.data(Signal.SESSION_END), [{"reason": "process_exit"}])

    def test_hook_only_session_survives_registry_race(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.tracker.feed_registry([])
        h.tracker.feed_registry([])
        h.tracker.feed_registry([])
        h.tracker.feed_registry([])
        self.assertFalse(st.ended)

    def test_registry_rekeys_a_cleared_session(self):
        h = Harness()
        h.tracker.feed_registry([registry_entry(sid="old", clock=h.clock)])
        st = h.state("old")
        h.rec.clear()
        h.tracker.feed_registry([registry_entry(sid="new", clock=h.clock)])
        self.assertIs(h.state("new"), st)
        self.assertEqual(h.rec.data(Signal.SESSION_START), [{"source": "clear", "replaces": "old"}])
        self.assertEqual(len(h.tracker.all()), 1)

    def test_interrupt_safety_net(self):
        h = Harness()
        h.hook("SessionStart", source="startup")
        st = h.hook("UserPromptSubmit", prompt="go")
        h.hook("PreToolUse", tool_name="Bash", tool_use_id="x", tool_input={"command": "sleep 100"})
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="busy")])
        h.clock.advance(30)
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="busy")])
        self.assertEqual(st.activity, Activity.RUNNING)
        idle = registry_entry(clock=h.clock, status="idle")   # user pressed Esc: no Stop hook
        h.tracker.feed_registry([idle])
        self.assertEqual(st.activity, Activity.RUNNING)       # give hooks a moment first
        h.clock.advance(5)
        h.tracker.feed_registry([idle])
        self.assertEqual(st.activity, Activity.IDLE)
        self.assertFalse(st.turn_active)
        self.assertIn(Signal.INTERRUPTED, h.rec.names())
        self.assertNotIn(Signal.TURN_DONE, h.rec.names())

    def test_registry_does_not_fight_fresh_hooks(self):
        h = Harness()
        st = h.hook("UserPromptSubmit", prompt="go")
        stale_idle = registry_entry(clock=h.clock, status="idle",
                                    statusUpdatedAt=int((h.clock() - 60) * 1000))
        h.clock.advance(10)
        h.tracker.feed_registry([stale_idle])   # idle stamp predates the prompt
        self.assertTrue(st.turn_active)
        self.assertNotIn(Signal.INTERRUPTED, h.rec.names())


class TranscriptFeedTest(unittest.TestCase):
    def test_context_usage_and_high_water_signal(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.tracker.feed_transcript("s1", [{"kind": "usage", "model": "claude-haiku-4-5", "context_tokens": 170_000,
                                          "ts": h.clock()}], initial=True)
        self.assertEqual((st.model, st.context_tokens, st.context_limit), ("claude-haiku-4-5", 170_000, 200_000))
        self.assertAlmostEqual(st.context_pct, 0.85)
        self.assertNotIn(Signal.CONTEXT_HIGH, h.rec.names())   # catch-up batches are silent
        h.tracker.feed_transcript("s1", [{"kind": "usage", "model": "claude-haiku-4-5", "context_tokens": 100_000}])
        h.tracker.feed_transcript("s1", [{"kind": "usage", "model": "claude-haiku-4-5", "context_tokens": 185_000}])
        h.tracker.feed_transcript("s1", [{"kind": "usage", "model": "claude-haiku-4-5", "context_tokens": 190_000}])
        self.assertEqual(len(h.rec.data(Signal.CONTEXT_HIGH)), 1)
        h.tick(1)
        self.assertEqual(st.emotion, Emotion.STUFFED)
        # usage beyond 200k proves a 1M window
        h.tracker.feed_transcript("s1", [{"kind": "usage", "model": "claude-haiku-4-5", "context_tokens": 280_000}])
        self.assertEqual(st.context_limit, 1_000_000)
        self.assertAlmostEqual(st.context_pct, 0.28)

    def test_hooked_session_ignores_transcript_activity(self):
        h = Harness()
        st = h.hook("SessionStart", source="startup")
        h.tracker.feed_transcript("s1", [
            {"kind": "user_prompt", "text": "hello"},
            {"kind": "tool_use", "tool": "Read", "input": {"file_path": "/x/a"}, "id": "t"},
        ])
        self.assertEqual((st.prompts, st.activity), (0, Activity.STARTING))

    def test_transcript_drives_a_hookless_session(self):
        h = Harness()
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="busy")])
        st = h.state()
        h.tracker.feed_transcript("s1", [{"kind": "user_prompt", "text": "old prompt"},
                                         {"kind": "tool_use", "tool": "Read", "input": {}, "id": "old"}], initial=True)
        self.assertEqual((st.last_prompt, st.prompts, st.activity), ("old prompt", 0, Activity.THINKING))
        h.tracker.feed_transcript("s1", [
            {"kind": "user_prompt", "text": "fix it, this is still broken!!!"},
            {"kind": "tool_use", "tool": "Bash", "input": {"command": "pytest -q"}, "id": "t1"},
        ])
        self.assertEqual((st.prompts, st.activity, st.detail), (1, Activity.TESTING, "Running tests"))
        self.assertEqual(h.rec.data(Signal.PROMPT)[0]["sentiment"], "frustrated")
        h.tracker.feed_transcript("s1", [{"kind": "tool_result", "id": "t1", "is_error": True}])
        self.assertEqual((st.tools_failed, st.activity), (1, Activity.THINKING))
        self.assertIn(Signal.TESTS_FAILED, h.rec.names())
        h.tracker.feed_transcript("s1", [{"kind": "tool_use", "tool": "Edit", "input": {"file_path": "/x/a.py"}, "id": "t2"},
                                         {"kind": "tool_result", "id": "t2", "is_error": False}])
        self.assertEqual((st.tools_ok, st.edits), (1, 1))
        h.clock.advance(4)
        h.tracker.feed_registry([registry_entry(clock=h.clock, status="idle")])
        done = h.rec.data(Signal.TURN_DONE)[0]
        self.assertEqual((done["tools"], done["errors"], done["edits"]), (2, 1, 1))


class RealPayloadReplayTest(unittest.TestCase):
    """Replays hook payloads captured from real `claude -p` sessions (v2.1.291)."""

    def replay(self, name):
        h = Harness()
        rows = session_fixture(name)
        start = h.clock()
        sid = rows[0]["payload"]["session_id"]
        meta = {"pid": 31337, "entrypoint": "sdk-cli", "attended": "0"}
        for row in rows:
            target = start + row["t"]
            while h.clock() + 0.5 <= target:
                h.tick(0.5)
            h.clock.t = max(h.clock(), target)
            h.tracker.feed_hook({"type": "hook", "v": 1, "ts": h.clock(), "meta": meta,
                                 "payload": trim_payload(row["payload"])})
        return h, sid

    def test_run_a_tools_denial_and_end(self):
        h, sid = self.replay("run-a")
        names = h.rec.names()
        self.assertEqual(names[0], Signal.SESSION_START)
        self.assertEqual(names[-1], Signal.SESSION_END)
        self.assertEqual(h.rec.data(Signal.SESSION_END), [{"reason": "other"}])
        self.assertEqual(len(h.rec.data(Signal.TOOL_OK)), 4)       # Read, Bash, Write, Edit
        self.assertEqual(h.rec.data(Signal.PERMISSION_DENIED), [{"tool": "Bash"}])
        self.assertNotIn(Signal.NEEDS_USER, names)                  # headless: auto-denied
        done = h.rec.data(Signal.TURN_DONE)
        self.assertEqual(len(done), 1)
        self.assertEqual((done[0]["tools"], done[0]["errors"], done[0]["edits"]), (4, 0, 2))
        self.assertIsNone(h.tracker.get(sid))
        details = [d["detail"] for d in h.rec.data(Signal.TOOL_START)]
        self.assertEqual(details[0], "Reading notes.txt")
        self.assertEqual(details[-2:], ["Writing out.txt", "Editing out.txt"])
        activities = [c[1] for c in h.rec.calls]
        for expected in (Activity.STARTING, Activity.LISTENING, Activity.THINKING, Activity.READING,
                         Activity.RUNNING, Activity.WRITING, Activity.DONE, Activity.ENDED):
            self.assertIn(expected, activities)

    def test_run_b_subagent_parallel_failure(self):
        h, sid = self.replay("run-b")
        names = h.rec.names()
        self.assertEqual(h.rec.data(Signal.SUBAGENT_START), [{"agent_type": "general-purpose", "count": 1}])
        self.assertEqual(h.rec.data(Signal.SUBAGENT_STOP), [{"agent_type": "general-purpose", "count": 0}])
        errors = h.rec.data(Signal.TOOL_ERROR)
        self.assertEqual(len(errors), 1)
        self.assertEqual((errors[0]["tool"], errors[0]["detail"]), ("Bash", "Exit code 1"))
        self.assertEqual(len(h.rec.data(Signal.TOOL_OK)), 4)       # Agent, Bash, sub-Bash, Read
        self.assertEqual(len(h.rec.data(Signal.PROMPT)), 1)         # the task notification is not a prompt
        self.assertEqual(len(h.rec.data(Signal.TURN_DONE)), 2)
        self.assertEqual(names[-1], Signal.SESSION_END)
        self.assertIn(Activity.DELEGATING, [c[1] for c in h.rec.calls])

    def test_real_wire_recording(self):
        """Messages exactly as `bin/claude-pets-hook` sent them from a real session
        that used the final hooks block (sync + async mix)."""
        h = Harness()
        start = h.clock()
        rows = session_fixture("wire-d")
        for msg in rows:
            target = start + msg["ts"]
            while h.clock() + 0.5 <= target:
                h.tick(0.5)
            h.clock.t = max(h.clock(), target)
            h.tracker.feed_hook(dict(msg, ts=h.clock()))
        names = h.rec.names()
        self.assertEqual((names[0], names[-1]), (Signal.SESSION_START, Signal.SESSION_END))
        self.assertEqual(len(h.rec.data(Signal.TOOL_OK)), 3)        # Read, Bash echo, Write
        self.assertEqual(len(h.rec.data(Signal.TOOL_ERROR)), 1)     # Bash false
        self.assertEqual(h.rec.data(Signal.PERMISSION_DENIED), [{"tool": "Bash"}])
        self.assertNotIn(Signal.NEEDS_USER, names)
        (done,) = h.rec.data(Signal.TURN_DONE)
        self.assertEqual((done["tools"], done["errors"], done["edits"]), (4, 1, 1))
        self.assertEqual(h.tracker.all(), [])
        for msg in rows:
            self.assertLess(len(json.dumps(msg)), 8192)

    def test_single_fixtures_trim_small_and_parse(self):
        import json
        import os
        from test_support import FIXTURES
        folder = os.path.join(FIXTURES, "hooks")
        count = 0
        for root, _, files in os.walk(folder):
            for name in files:
                with open(os.path.join(root, name), encoding="utf-8") as handle:
                    payload = json.load(handle)
                wire = json.dumps(trim_payload(payload))
                self.assertLess(len(wire), 8192, name)
                h = Harness()
                h.tracker.feed_hook({"type": "hook", "ts": h.clock(), "meta": {"pid": 5}, "payload": trim_payload(payload)})
                count += 1
        self.assertGreaterEqual(count, 25)


class ClassifierTest(unittest.TestCase):
    def test_tool_table(self):
        cases = [
            ("Read", {"file_path": "/a/b/c.py"}, Activity.READING, "Reading c.py"),
            ("Glob", {"pattern": "**/*.ts"}, Activity.SEARCHING, "Finding **/*.ts"),
            ("Write", {"file_path": "/a/new.md"}, Activity.WRITING, "Writing new.md"),
            ("NotebookEdit", {"notebook_path": "/a/n.ipynb"}, Activity.WRITING, "Editing n.ipynb"),
            ("Bash", {"command": "kubectl get pods -n prod"}, Activity.RUNNING, "Running kubectl get pods"),
            ("Bash", {"command": "cargo clippy --all"}, Activity.TESTING, "Checking the code"),
            ("Bash", {"command": "helm template ./chart"}, Activity.TESTING, "Building"),
            ("WebFetch", {"url": "https://docs.python.org/3/library/json.html"}, Activity.BROWSING, "Browsing docs.python.org"),
            ("WebSearch", {"query": "gnome wayland overlay"}, Activity.BROWSING, "Searching the web for “gnome wayland overlay”"),
            ("Task", {"subagent_type": "Explore"}, Activity.DELEGATING, "Delegating: Explore"),
            ("TodoWrite", {"todos": {"_len": 3}}, Activity.PLANNING, "Updating the plan"),
            ("ExitPlanMode", {}, Activity.PLANNING, "Presenting the plan"),
            ("AskUserQuestion", {}, Activity.ASKING, "Asking you a question"),
            ("Skill", {"skill": "design"}, Activity.TOOL, "Using skill design"),
            ("mcp__github__create_issue", {}, Activity.TOOL, "Using github · create issue"),
            ("mcp__claude-in-chrome__navigate", {}, Activity.BROWSING, "Using the browser"),
            ("SomethingNew", None, Activity.TOOL, "Using SomethingNew"),
        ]
        for name, tool_input, activity, detail in cases:
            got = classify_tool(name, tool_input)
            self.assertEqual((got[0], got[1]), (activity, detail), name)

    def test_command_head_never_leaks_arguments(self):
        self.assertEqual(command_head("curl -H 'Authorization: Bearer sk-secret' https://x.test"), "curl")
        self.assertEqual(command_head("API_KEY=abc123 npm run dev -- --port 3000"), "npm run dev")
        self.assertEqual(command_head("# comment\n  /usr/bin/python3 script.py --token=xyz"), "python3 script.py")
        self.assertEqual(command_head("sudo systemctl restart nginx"), "systemctl restart nginx")
        self.assertEqual(command_head("cd /secret/place && ls"), "cd")
        self.assertEqual(command_head(""), "")

    def test_shell_kind(self):
        self.assertEqual(shell_kind("npm test"), "test")
        self.assertEqual(shell_kind("go vet ./..."), "lint")
        self.assertEqual(shell_kind("make -j8"), "build")
        self.assertEqual(shell_kind("ls -la"), "")

    def test_sentiment(self):
        for text in ("thanks, that works great!", "Perfect \U0001F389", "hvala, super", "LGTM", "odlično, bravo"):
            self.assertEqual(classify_sentiment(text), "praise", text)
        for text in ("wtf, it's still broken", "this is wrong, i told you not to touch that file",
                     "NO NOT LIKE THAT, UNDO THAT", "še vedno ne dela", "spet narobe", "why did you delete my tests???"):
            self.assertEqual(classify_sentiment(text), "frustrated", text)
        for text in ("add a login page", "the build doesn't work, can you look at the error?", "run the tests again",
                     "what's wrong with this regex?", "poženi spet teste", "", None,
                     "thanks, but it's still broken"):
            self.assertEqual(classify_sentiment(text), "neutral", text)

    def test_machine_prompts_and_snippets(self):
        self.assertTrue(is_machine_prompt("<task-notification>\n<task-id>1</task-id>"))
        self.assertTrue(is_machine_prompt("anything", source="schedule_wakeup"))
        self.assertFalse(is_machine_prompt("fix <task-notification> parsing", source="user"))
        self.assertEqual(snippet("a\n  b\tc"), "a b c")
        self.assertEqual(len(snippet("x" * 500)), 80)


if __name__ == "__main__":
    unittest.main()

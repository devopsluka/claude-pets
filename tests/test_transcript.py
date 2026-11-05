import json
import os
import tempfile
import unittest

import test_support  # noqa: F401  (sys.path)

from claude_pets.transcript import (
    TranscriptTailer, context_limit_for, normalize_record, project_slug, transcript_path_for,
)


def assistant(blocks, tokens=(10, 2000, 300), model="claude-haiku-4-5-20251001", **extra):
    record = {
        "type": "assistant", "isSidechain": False, "timestamp": "2026-10-06T14:42:20.543Z",
        "message": {"role": "assistant", "model": model, "content": blocks,
                    "usage": {"input_tokens": tokens[0], "cache_read_input_tokens": tokens[1],
                              "cache_creation_input_tokens": tokens[2], "output_tokens": 50}},
    }
    record.update(extra)
    return record


def user(content, **extra):
    record = {"type": "user", "isSidechain": False, "timestamp": "2026-10-06T14:42:21.000Z",
              "message": {"role": "user", "content": content}}
    record.update(extra)
    return record


class NormalizeTest(unittest.TestCase):
    def test_assistant_tool_use_and_usage(self):
        records = normalize_record(assistant([
            {"type": "thinking", "thinking": "hm"},
            {"type": "text", "text": "Let me look."},
            {"type": "tool_use", "id": "toolu_1", "name": "Edit",
             "input": {"file_path": "/x/a.py", "old_string": "x" * 9999, "new_string": "y"}},
        ]))
        self.assertEqual([r["kind"] for r in records], ["usage", "assistant_text", "tool_use"])
        self.assertEqual(records[0]["context_tokens"], 2310)
        self.assertEqual(records[0]["model"], "claude-haiku-4-5-20251001")
        self.assertAlmostEqual(records[0]["ts"], 1791297740.543, places=2)
        tool = records[2]
        self.assertEqual((tool["tool"], tool["id"], tool["input"]["file_path"]), ("Edit", "toolu_1", "/x/a.py"))
        self.assertEqual(tool["input"]["old_string"], {"_len": 9999})   # file bodies never travel

    def test_user_records(self):
        self.assertEqual(normalize_record(user("fix the bug"))[0],
                         {"kind": "user_prompt", "text": "fix the bug", "ts": normalize_record(user("x"))[0]["ts"]})
        results = normalize_record(user([
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "boom", "is_error": True},
            {"type": "tool_result", "tool_use_id": "toolu_2", "content": "ok"},
        ]))
        self.assertEqual([(r["id"], r["is_error"]) for r in results], [("toolu_1", True), ("toolu_2", False)])

    def test_noise_is_skipped(self):
        self.assertEqual(normalize_record(user("<task-notification>\n<task-id>1</task-id>")), [])
        self.assertEqual(normalize_record(user("<local-command-caveat>x</local-command-caveat>")), [])
        self.assertEqual(normalize_record(user("real", isMeta=True)), [])
        self.assertEqual(normalize_record(assistant([{"type": "text", "text": "sub"}], isSidechain=True)), [])
        self.assertEqual(normalize_record(assistant([{"type": "text", "text": "x"}], tokens=(0, 0, 0), model="<synthetic>")),
                         [{"kind": "assistant_text", "ts": normalize_record(assistant([]))[0]["ts"]}])
        self.assertEqual(normalize_record({"type": "attachment", "attachment": {"type": "date"}}), [])
        self.assertEqual(normalize_record({"type": "queue-operation", "content": "x"}), [])
        for junk in (None, 3, "x", [], {"type": "assistant"}, {"type": "user", "message": 4}):
            self.assertEqual(normalize_record(junk), [])

    def test_compaction_markers(self):
        self.assertEqual(normalize_record({"type": "system", "subtype": "compact_boundary",
                                           "timestamp": "2026-10-06T14:42:21Z"})[0]["kind"], "compact")
        self.assertEqual(normalize_record(user("summary...", isCompactSummary=True))[0]["kind"], "compact")


class ContextLimitTest(unittest.TestCase):
    def test_heuristic(self):
        self.assertEqual(context_limit_for("claude-haiku-4-5-20251001", 50_000), 200_000)
        self.assertEqual(context_limit_for("claude-sonnet-5-5[1m]", 50_000), 1_000_000)
        self.assertEqual(context_limit_for("claude-fable-5-1", 50_000), 1_000_000)
        self.assertEqual(context_limit_for("claude-opus-5-5", 250_000), 1_000_000)
        self.assertEqual(context_limit_for("claude-opus-5-5", 50_000, previous=1_000_000), 1_000_000)
        self.assertEqual(context_limit_for(None, 0), 200_000)


class PathTest(unittest.TestCase):
    def test_slug_matches_claude_code(self):
        self.assertEqual(project_slug("/home/user/development/personal/pet"), "-home-user-development-personal-pet")
        self.assertEqual(project_slug("/tmp/claude-1000/-home-x/a_b.c"), "-tmp-claude-1000--home-x-a-b-c")

    def test_transcript_path_for(self):
        with tempfile.TemporaryDirectory() as projects:
            self.assertEqual(transcript_path_for("abc", "", projects), "")
            self.assertEqual(transcript_path_for("abc", "/w/demo", projects),
                             os.path.join(projects, "-w-demo", "abc.jsonl"))
            odd = os.path.join(projects, "some-other-slug")
            os.makedirs(odd)
            open(os.path.join(odd, "abc.jsonl"), "w").close()
            self.assertEqual(transcript_path_for("abc", "/w/demo", projects), os.path.join(odd, "abc.jsonl"))
            self.assertEqual(transcript_path_for("abc", "", projects), os.path.join(odd, "abc.jsonl"))

    def test_real_project_dirs_follow_the_slug_rule(self):
        from claude_pets import paths
        from claude_pets.registry import RegistryWatcher
        for entry in RegistryWatcher().poll():
            cwd, sid = entry.get("cwd"), entry.get("sessionId")
            if cwd and sid:
                found = transcript_path_for(sid, cwd)
                if os.path.exists(found):
                    self.assertEqual(os.path.dirname(found),
                                     os.path.join(paths.CLAUDE_PROJECTS_DIR, project_slug(cwd)))


class TailerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "s.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def append(self, *records, raw=None):
        with open(self.path, "ab") as handle:
            for record in records:
                handle.write(json.dumps(record).encode() + b"\n")
            if raw is not None:
                handle.write(raw)

    def test_initial_then_incremental(self):
        tailer = TranscriptTailer()
        tailer.watch("s", self.path)
        self.assertEqual(tailer.poll(), {})                 # file does not exist yet
        self.append(user("first"), assistant([{"type": "text", "text": "hi"}]))
        records, initial = tailer.poll()["s"]
        self.assertTrue(initial)
        self.assertEqual([r["kind"] for r in records], ["user_prompt", "usage", "assistant_text"])
        self.assertEqual(tailer.poll(), {})                 # nothing new
        self.append(assistant([{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a"}}]))
        records, initial = tailer.poll()["s"]
        self.assertFalse(initial)
        self.assertEqual([r["kind"] for r in records], ["usage", "tool_use"])

    def test_partial_lines_wait_for_their_newline(self):
        tailer = TranscriptTailer()
        tailer.watch("s", self.path)
        self.append(user("one"))
        tailer.poll()
        line = json.dumps(user("two")).encode()
        self.append(raw=line[:20])
        self.assertEqual(tailer.poll(), {})
        self.append(raw=line[20:] + b"\n")
        records, _ = tailer.poll()["s"]
        self.assertEqual([r["text"] for r in records], ["two"])

    def test_first_poll_reads_only_the_tail(self):
        for i in range(400):
            self.append(user("prompt number %d " % i + "x" * 200))
        tailer = TranscriptTailer(tail_bytes=4096)
        tailer.watch("s", self.path)
        records, initial = tailer.poll()["s"]
        self.assertTrue(initial)
        self.assertTrue(0 < len(records) < 30)
        self.assertTrue(records[-1]["text"].startswith("prompt number 399 "))
        self.assertTrue(all(r["text"].startswith("prompt number") for r in records))  # no torn first line

    def test_truncation_and_garbage(self):
        tailer = TranscriptTailer()
        tailer.watch("s", self.path)
        self.append(user("a"), user("b"), raw=b"not json\n\n")
        self.assertEqual(len(tailer.poll()["s"][0]), 2)
        with open(self.path, "wb"):
            pass
        self.append(user("fresh"))
        records, initial = tailer.poll()["s"]
        self.assertTrue(initial)
        self.assertEqual(records[0]["text"], "fresh")

    def test_watch_unwatch_rewatch(self):
        tailer = TranscriptTailer()
        self.append(user("a"))
        tailer.watch("s", self.path)
        tailer.watch("s", self.path)          # same path: keeps its position
        self.assertEqual(tailer.watching("s"), self.path)
        tailer.poll()
        other = os.path.join(self.tmp.name, "other.jsonl")
        with open(other, "w") as handle:
            handle.write(json.dumps(user("b")) + "\n")
        tailer.watch("s", other)               # /clear: new transcript
        records, initial = tailer.poll()["s"]
        self.assertTrue(initial)
        self.assertEqual(records[0]["text"], "b")
        tailer.unwatch("s")
        self.assertEqual(tailer.poll(), {})
        tailer.watch("", self.path)
        tailer.watch("x", "")
        self.assertEqual(tailer.poll(), {})


if __name__ == "__main__":
    unittest.main()

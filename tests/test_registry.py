import json
import os
import tempfile
import unittest

import test_support  # noqa: F401  (sys.path)

from claude_pets.registry import RegistryWatcher, proc_start_time


class RegistryWatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.starts = {}
        self.watcher = RegistryWatcher(self.dir, start_time=lambda pid: self.starts.get(pid, ""))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, pid, **fields):
        data = {"pid": pid, "sessionId": "sid-%d" % pid, "cwd": "/w", "procStart": "100", "status": "idle"}
        data.update(fields)
        path = os.path.join(self.dir, "%d.json" % pid)
        with open(path, "w") as handle:
            json.dump(data, handle)
        return path

    def test_only_live_processes_are_returned(self):
        self.write(10)
        self.write(11)
        self.starts = {10: "100"}
        entries = self.watcher.poll()
        self.assertEqual([e["sessionId"] for e in entries], ["sid-10"])
        self.starts[11] = "100"
        self.assertEqual(sorted(e["pid"] for e in self.watcher.poll()), [10, 11])

    def test_pid_reuse_is_detected(self):
        self.write(10, procStart="100")
        self.starts = {10: "999"}   # some other process owns pid 10 now
        self.assertEqual(self.watcher.poll(), [])

    def test_missing_proc_start_is_accepted(self):
        path = self.write(10)
        with open(path) as handle:
            data = json.load(handle)
        del data["procStart"]
        with open(path, "w") as handle:
            json.dump(data, handle)
        self.starts = {10: "5"}
        self.assertEqual(len(self.watcher.poll()), 1)

    def test_key_files_and_junk_are_never_opened(self):
        self.write(10)
        self.starts = {10: "100"}
        secret = os.path.join(self.dir, "10.abcdef.key")
        with open(secret, "w") as handle:
            handle.write("secret")
        os.chmod(secret, 0)
        with open(os.path.join(self.dir, "notes.json"), "w") as handle:
            handle.write("{}")
        with open(os.path.join(self.dir, "12.json"), "w") as handle:
            handle.write('{"pid": 12, "sess')     # half-written
        with open(os.path.join(self.dir, "13.json"), "w") as handle:
            handle.write("[1, 2]")
        self.starts.update({12: "1", 13: "1"})
        self.assertEqual([e["pid"] for e in self.watcher.poll()], [10])

    def test_returns_copies_and_refreshes_on_change(self):
        path = self.write(10, status="idle")
        self.starts = {10: "100"}
        first = self.watcher.poll()[0]
        first["status"] = "tampered"
        self.assertEqual(self.watcher.poll()[0]["status"], "idle")
        self.write(10, status="busy", waitingFor="x" * 40)
        os.utime(path, ns=(1, 1))
        self.assertEqual(self.watcher.poll()[0]["status"], "busy")

    def test_half_written_update_keeps_last_good_copy(self):
        path = self.write(10, status="idle")
        self.starts = {10: "100"}
        self.watcher.poll()
        with open(path, "w") as handle:
            handle.write('{"pid": 10, "stat')
        self.assertEqual(self.watcher.poll()[0]["status"], "idle")

    def test_removed_files_and_missing_dir(self):
        path = self.write(10)
        self.starts = {10: "100"}
        self.assertEqual(len(self.watcher.poll()), 1)
        os.unlink(path)
        self.assertEqual(self.watcher.poll(), [])
        self.assertEqual(RegistryWatcher(os.path.join(self.dir, "nope")).poll(), [])

    def test_proc_start_time_of_real_processes(self):
        self.assertTrue(proc_start_time(os.getpid()).isdigit())
        self.assertEqual(proc_start_time(2 ** 22 + 12345), "")

    def test_real_registry_is_readable(self):
        entries = RegistryWatcher().poll()   # the developer's own machine: must not raise
        for entry in entries:
            self.assertIsInstance(entry["pid"], int)
            self.assertIn("sessionId", entry)


if __name__ == "__main__":
    unittest.main()

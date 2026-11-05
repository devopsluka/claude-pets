import json
import os
import stat
import tempfile
import unittest

import test_support  # noqa: F401  (sys.path)

from claude_pets import hooks_install

USER_SETTINGS = """{
  "attribution": {
    "sessionUrl": false
  },
  "permissions": {
    "defaultMode": "auto"
  },
  "model": "fable",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/bin/audit-bash.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "notify-send done — finished"
          }
        ]
      }
    ]
  },
  "tui": "fullscreen"
}
"""


class HooksInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "settings.json")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.path, encoding="utf-8") as handle:
            return handle.read()

    def backups(self):
        return sorted(n for n in os.listdir(self.tmp.name) if ".bak-claude-pets-" in n)

    def test_command_is_guarded_and_relocatable(self):
        command = hooks_install.hook_command()
        self.assertIn(hooks_install.MARKER, command)
        self.assertTrue(command.startswith("[ -x "))
        self.assertTrue(command.endswith("|| true"))
        self.assertIn('"$HOME/', command)
        self.assertNotIn(os.path.expanduser("~"), command)
        odd = hooks_install.hook_command("/opt/my pets/app")
        self.assertIn("'/opt/my pets/app/bin/claude-pets-hook'", odd)

    def test_guarded_command_is_a_silent_no_op_when_not_installed(self):
        import subprocess
        command = hooks_install.hook_command(os.path.join(self.tmp.name, "missing"))
        done = subprocess.run(["sh", "-c", command], input=b"{}", capture_output=True)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))

    def test_install_into_missing_file(self):
        result = hooks_install.install(self.path)
        self.assertTrue(result["changed"])
        self.assertIsNone(result["backup_path"])
        data = json.loads(self.read())
        self.assertEqual(list(data), ["hooks"])
        self.assertEqual(sorted(data["hooks"]), sorted(hooks_install.EVENT_NAMES))
        for name, is_async in hooks_install.EVENTS:
            (group,) = data["hooks"][name]
            (hook,) = group["hooks"]
            self.assertEqual(hook["type"], "command")
            self.assertEqual(hook.get("async", False), is_async, name)
            self.assertNotIn("matcher", group)
        self.assertEqual(self.backups(), [])

    def test_install_preserves_everything_else(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(USER_SETTINGS)
        os.chmod(self.path, 0o600)
        result = hooks_install.install(self.path)
        self.assertTrue(result["changed"])
        self.assertEqual(len(self.backups()), 1)
        with open(result["backup_path"], encoding="utf-8") as handle:
            self.assertEqual(handle.read(), USER_SETTINGS)
        text = self.read()
        data = json.loads(text)
        original = json.loads(USER_SETTINGS)
        self.assertEqual(list(data), list(original))                      # key order kept
        self.assertEqual({k: v for k, v in data.items() if k != "hooks"},
                         {k: v for k, v in original.items() if k != "hooks"})
        self.assertEqual(data["hooks"]["PreToolUse"][0], original["hooks"]["PreToolUse"][0])
        self.assertEqual(data["hooks"]["Stop"][0], original["hooks"]["Stop"][0])
        self.assertEqual(len(data["hooks"]["PreToolUse"]), 2)
        self.assertIn("—", text)                                     # no \\u escapes introduced
        self.assertTrue(text.startswith('{\n  "attribution"'))            # 2-space indent kept
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_install_is_idempotent(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(USER_SETTINGS)
        hooks_install.install(self.path)
        first = self.read()
        again = hooks_install.install(self.path)
        self.assertFalse(again["changed"])
        self.assertIsNone(again["backup_path"])
        self.assertEqual(self.read(), first)
        self.assertEqual(len(self.backups()), 1)

    def test_install_upgrades_stale_entries(self):
        stale = {"hooks": {
            "PreToolUse": [{"hooks": [{"type": "command", "command": "/old/place/bin/claude-pets-hook"},
                                      {"type": "command", "command": "keep-me"}]}],
            "CwdChanged": [{"hooks": [{"type": "command", "command": "/old/place/bin/claude-pets-hook"}]}],
        }}
        with open(self.path, "w") as handle:
            json.dump(stale, handle)
        hooks_install.install(self.path)
        data = json.loads(self.read())
        self.assertNotIn("CwdChanged", data["hooks"])
        commands = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertEqual(commands, ["keep-me", hooks_install.hook_command()])
        self.assertTrue(hooks_install.status(self.path)["installed"])

    def test_uninstall_restores_the_original(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(USER_SETTINGS)
        hooks_install.install(self.path)
        result = hooks_install.uninstall(self.path)
        self.assertTrue(result["changed"])
        self.assertEqual(sorted(result["events"]), sorted(hooks_install.EVENT_NAMES))
        self.assertEqual(self.read(), USER_SETTINGS)
        self.assertFalse(hooks_install.uninstall(self.path)["changed"])

    def test_uninstall_prunes_what_it_emptied(self):
        hooks_install.install(self.path)
        hooks_install.uninstall(self.path)
        self.assertEqual(json.loads(self.read()), {})
        with open(self.path, "w") as handle:
            json.dump({"model": "opus"}, handle)
        self.assertFalse(hooks_install.uninstall(self.path)["changed"])

    def test_status(self):
        status = hooks_install.status(self.path)
        self.assertFalse(status["installed"])
        self.assertEqual(status["missing"], list(hooks_install.EVENT_NAMES))
        hooks_install.install(self.path)
        status = hooks_install.status(self.path)
        self.assertTrue(status["installed"])
        self.assertEqual((status["missing"], status["outdated"]), ([], []))
        data = json.loads(self.read())
        data["hooks"]["Stop"][0]["hooks"][0]["async"] = True
        del data["hooks"]["PreCompact"]
        with open(self.path, "w") as handle:
            json.dump(data, handle)
        status = hooks_install.status(self.path)
        self.assertEqual((status["installed"], status["missing"], status["outdated"]),
                         (False, ["PreCompact"], ["Stop"]))

    def test_broken_settings_are_left_alone(self):
        for broken in ('{"hooks": ', "[1, 2]", '{"hooks": []}', '{"hooks": {"Stop": {}}}'):
            with open(self.path, "w") as handle:
                handle.write(broken)
            with self.assertRaises(ValueError):
                hooks_install.install(self.path)
            self.assertEqual(self.read(), broken)
            self.assertEqual(self.backups(), [])
        self.assertFalse(hooks_install.status(self.path)["installed"])

    def test_symlinked_settings_stay_a_symlink(self):
        real = os.path.join(self.tmp.name, "dotfiles-settings.json")
        with open(real, "w") as handle:
            handle.write("{}\n")
        os.symlink(real, self.path)
        hooks_install.install(self.path)
        self.assertTrue(os.path.islink(self.path))
        with open(real) as handle:
            self.assertIn("claude-pets-hook", handle.read())

    def test_build_hooks_block(self):
        block = hooks_install.build_hooks_block("X/claude-pets-hook")
        self.assertEqual(list(block), list(hooks_install.EVENT_NAMES))
        self.assertEqual(block["PreToolUse"], [{"hooks": [
            {"type": "command", "command": "X/claude-pets-hook", "timeout": 5, "async": True}]}])
        self.assertEqual(block["Stop"], [{"hooks": [
            {"type": "command", "command": "X/claude-pets-hook", "timeout": 5}]}])


if __name__ == "__main__":
    unittest.main()

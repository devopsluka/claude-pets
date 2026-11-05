"""Going to a session's terminal: which door is used for which terminal."""

import os
import unittest
from unittest import mock

from claude_pets import focus


class FocusTests(unittest.TestCase):
    def run_focus(self, term, chain=(), commands=None, pid=4242, cwd="/work/shop", gapp=False, windows=""):
        """Run focus_terminal with every external effect faked; returns (result, calls)."""
        calls = []
        commands = commands or {}

        def fake_run(argv, timeout=1.5, capture=False):
            calls.append(list(argv))
            key = argv[0] if argv[0] != "kitty" else "kitty " + argv[4]
            if argv[:3] == ["wmctrl", "-l", "-p"]:
                return windows
            value = commands.get(key, False)
            if capture:
                return value if isinstance(value, str) else None
            return bool(value)

        with mock.patch.object(focus, "_run", fake_run), \
                mock.patch.object(focus, "term_from_pid", lambda _pid: {}), \
                mock.patch.object(focus, "ancestors", lambda _pid, limit=24: list(chain)), \
                mock.patch.object(focus, "activate_gapplication", lambda app, token: calls.append(["dbus", app, token]) or gapp), \
                mock.patch.object(focus.shutil, "which", lambda name: "/usr/bin/" + name), \
                mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
            done = focus.focus_terminal(term, pid=pid, cwd=cwd, make_token=lambda desktop: "TOKEN:%s" % desktop)
        return done, calls

    def test_kitty_gets_the_token_through_the_kitten(self):
        done, calls = self.run_focus({"kitty_window_id": "7", "kitty_listen_on": "unix:/tmp/kitty-1"},
                                     commands={"kitty kitten": "ok\n"})
        self.assertEqual(done, ["kitty"])
        self.assertEqual(calls[0][:7], ["kitty", "@", "--to", "unix:/tmp/kitty-1", "kitten", "--match", "id:7"])
        self.assertEqual(calls[0][-2:], [focus.KITTEN, "TOKEN:kitty.desktop"])
        self.assertTrue(os.path.exists(focus.KITTEN))

    def test_kitty_without_kitten_support_falls_back_to_focus_window_and_bell(self):
        done, calls = self.run_focus({"kitty_window_id": "7", "kitty_listen_on": "unix:/tmp/k", "tty": "/dev/null"},
                                     commands={"kitty kitten": False, "kitty focus-window": True})
        self.assertEqual(done, ["kitty-tab", "bell"])

    def test_gnome_terminals_are_activated_over_dbus_with_the_token(self):
        chain = [(4242, "claude"), (4000, "bash"), (3000, "ptyxis-agent"), (2000, "systemd")]
        done, calls = self.run_focus({}, chain=chain, gapp=True)
        self.assertEqual(done, ["app"])
        self.assertIn(["dbus", "org.gnome.Ptyxis", "TOKEN:org.gnome.Ptyxis.desktop"], calls)

    def test_x11_apps_are_raised_by_window_and_project_title(self):
        chain = [(4242, "claude"), (4100, "bash"), (900, "code"), (1, "systemd")]
        windows = ("0x01a0004b  0 900 fedora other-project – values.yaml\n"
                   "0x01a00d52  0 900 fedora shop – main.py\n"
                   "0x02000001  0 555 fedora unrelated\n")
        done, calls = self.run_focus({}, chain=chain, windows=windows, commands={"wmctrl": True})
        self.assertEqual(done, ["x11"])
        self.assertIn(["wmctrl", "-i", "-a", "0x01a00d52"], calls)

    def test_bell_is_the_last_resort(self):
        done, _calls = self.run_focus({"tty": "/dev/null"}, chain=[(4242, "claude"), (1, "systemd")])
        self.assertEqual(done, ["bell"])
        done, _calls = self.run_focus({}, chain=[(4242, "claude")])
        self.assertEqual(done, [])

    def test_tmux_selects_the_pane_then_raises_the_clients_terminal(self):
        calls_seen = {}

        def term_from(pid):
            return {"kitty_window_id": "3", "kitty_listen_on": "unix:/tmp/kitty-9"} if pid == 777 else {}

        commands = {"tmux": True, "kitty kitten": "ok"}
        calls = []

        def fake_run(argv, timeout=1.5, capture=False):
            calls.append(list(argv))
            if argv[0] == "tmux" and "list-clients" in argv:
                return "777\n"
            key = argv[0] if argv[0] != "kitty" else "kitty " + argv[4]
            value = commands.get(key, False)
            return (value if isinstance(value, str) else None) if capture else bool(value)

        with mock.patch.object(focus, "_run", fake_run), mock.patch.object(focus, "term_from_pid", term_from), \
                mock.patch.object(focus, "ancestors", lambda pid, limit=24: [(pid, "x")]), \
                mock.patch.object(focus.shutil, "which", lambda name: "/usr/bin/" + name):
            done = focus.focus_terminal({"tmux": "/tmp/tmux-1000/default,1,0", "tmux_pane": "%4"}, pid=4242,
                                        make_token=lambda desktop: "T")
        self.assertEqual(done, ["tmux", "kitty"])
        self.assertIn(["tmux", "-S", "/tmp/tmux-1000/default", "select-pane", "-t", "%4"], calls)
        self.assertTrue(any(c[:4] == ["kitty", "@", "--to", "unix:/tmp/kitty-9"] for c in calls))
        del calls_seen

    def test_ancestors_and_term_of_this_process(self):
        chain = focus.ancestors(os.getpid())
        self.assertEqual(chain[0][0], os.getpid())
        self.assertGreater(len(chain), 1)
        self.assertEqual(focus.ancestors("nope"), [])
        self.assertIsInstance(focus.term_from_pid(os.getpid()), dict)
        self.assertEqual(focus.term_from_pid(None), {})


if __name__ == "__main__":
    unittest.main()

"""The daemon's App wired to real GTK objects, but with nothing shown on screen
(needs an X display; skipped without one)."""

import os
import tempfile
import time
import types
import unittest
from unittest import mock

HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
if HAVE_DISPLAY:
    os.environ["GDK_BACKEND"] = "x11"
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        ready = Gtk.init_check([])
        HAVE_DISPLAY = bool(ready[0] if isinstance(ready, tuple) else ready)
    except Exception:
        HAVE_DISPLAY = False


@unittest.skipUnless(HAVE_DISPLAY, "no X display")
class AppTests(unittest.TestCase):
    def setUp(self):
        from claude_pets import config as config_mod
        from claude_pets.daemon import App
        from claude_pets.store import Store

        self.tmp = tempfile.TemporaryDirectory()
        self.saved = []
        patches = [mock.patch.object(config_mod, "save", lambda cfg, path=None: self.saved.append(dict(cfg))),
                   mock.patch.object(config_mod, "load", lambda path=None: dict(config_mod.DEFAULTS))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.app = App()
        self.app.store = Store(self.tmp.name)
        self.app.hidden_until = 4e9           # never map a window during tests
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for sid in list(self.app.actors):
            self.app._remove(sid)
        self.app.card.destroy()
        if self.app.frame_source:
            self.app.GLib.source_remove(self.app.frame_source)
        self.tmp.cleanup()

    def hook(self, event, sid="s1", cwd="/work/shop", **extra):
        payload = {"session_id": sid, "cwd": cwd, "hook_event_name": event, "transcript_path": ""}
        payload.update(extra)
        self.app.tracker.feed_hook({"type": "hook", "v": 1, "ts": time.time(), "meta": {}, "payload": payload})

    def test_monitor_change_rebuilds_every_window(self):
        self.hook("SessionStart", source="startup")
        self.hook("SessionStart", sid="s2", source="startup")
        before = {sid: actor.window for sid, actor in self.app.actors.items()}
        card = self.app.card
        held = self.app.actors["s1"].pet
        held.grab(500, 500)                    # a drag in progress when the screen goes away
        for _ in range(3):                     # unplugging fires several signals in a row
            self.app._on_monitors_changed()
        self.assertTrue(self.app._rebuild_timer)
        self.assertIs(self.app.actors["s1"].window, before["s1"])   # nothing yet: waits to settle
        self.assertFalse(self.app._rebuild_after_change())
        for sid, actor in self.app.actors.items():
            self.assertIsNot(actor.window, before[sid])
            self.assertIs(actor.window.pet, actor.pet)
        self.assertIsNot(self.app.card, card)
        self.assertFalse(held.held)
        self.assertEqual(self.app._rebuild_timer, 0)

    def test_sessions_become_pets_and_leave_again(self):
        self.hook("SessionStart", source="startup")
        self.hook("SessionStart", sid="s2", source="startup")          # same project: a sibling
        self.assertEqual(sorted(self.app.actors), ["s1", "s2"])
        a, b = self.app.actors["s1"].pet, self.app.actors["s2"].pet
        self.assertEqual((a.profile.index, b.profile.index), (1, 2))
        self.assertNotEqual(a.home_x, b.home_x)
        self.hook("PreToolUse", tool_name="Edit", tool_input={"file_path": "/work/shop/a.py"}, tool_use_id="t1")
        self.assertEqual(a.session.activity, "writing")
        status = self.app.command("status", {})
        self.assertEqual({p["session_id"] for p in status["pets"]}, {"s1", "s2"})
        self.assertFalse(status["visible"])
        self.hook("SessionEnd", reason="other")
        self.assertTrue(a.leaving)
        for _ in range(120):
            self.app.on_frame()
            a.update(1 / 30, 0)
        self.app.on_frame()
        self.assertNotIn("s1", self.app.actors)
        self.assertIn("s2", self.app.actors)

    def test_design_command_restyles_live_and_saves(self):
        self.hook("SessionStart", source="startup")
        reply = self.app.command("design", {"target": "s1", "set": {"species": "fox", "name": "Rune", "eye": "x"}})
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["live"])
        self.assertEqual(len(reply["errors"]), 1)
        pet = self.app.actors["s1"].pet
        self.assertEqual((pet.design.species, pet.name), ("fox", "Rune"))
        self.assertEqual(self.app.store.load_key(pet.profile.key).design.species, "fox")
        self.assertEqual(self.app.command("design", {"target": "Rune", "set": {}})["profile"]["name"], "Rune")
        self.assertFalse(self.app.command("design", {"target": "nobody", "set": {}})["ok"])

    def test_click_goes_to_the_terminal_and_petting_is_separate(self):
        self.hook("SessionStart", source="startup")
        pet = self.app.actors["s1"].pet
        calls = []

        def fake_focus(term, pid=None, cwd="", make_token=None):
            calls.append((cwd, make_token("kitty.desktop")))
            return ["kitty"]

        with mock.patch("claude_pets.focus.focus_terminal", fake_focus), \
                mock.patch.object(self.app, "make_token", lambda desktop=None, timestamp=0: "tok-%s" % timestamp):
            self.app.pet_clicked(pet, 12345)
            self.app.pet_clicked(pet, 12399)                # the second half of a double click: debounced
            self.assertEqual(calls, [("/work/shop", "tok-12345")])
            before = pet.profile.stats.get("pets", 0)
            self.app.pet_petted(pet)
            self.assertEqual(pet.profile.stats["pets"], before + 1)
            self.assertEqual(len(calls), 1)
            self.app.cfg["click"] = "pet"
            self.app.last_focus.clear()
            self.app.pet_clicked(pet, 20000)
            self.assertEqual(len(calls), 1)
            self.app.pet_double_clicked(pet, 20100)
            self.assertEqual(len(calls), 2)

    def test_menu_builds_and_hide_show_commands(self):
        self.hook("SessionStart", source="startup")
        actor = self.app.actors["s1"]
        with mock.patch.object(self.app.Gtk.Menu, "popup_at_pointer", lambda *a, **k: None):
            self.app.show_menu(actor.window, types.SimpleNamespace(time=1))
        labels = [item.get_label() for item in self.app.menu.get_children() if item.get_label()]
        self.assertIn("Go to its terminal", labels)
        self.assertTrue(any(label.startswith("Design ") for label in labels))
        self.app.hidden_until = 0.0
        self.app.command("hide", {"minutes": 5})
        self.assertFalse(self.app.visible())
        self.assertFalse(actor.window.visible)
        self.app.hidden_until = 4e9
        self.app.set_config("bubbles", "off")
        self.assertEqual(self.saved[-1]["bubbles"], "off")
        self.assertEqual(self.app.command("nope", {})["ok"], False)

    def test_clear_keeps_the_same_pet(self):
        self.hook("SessionStart", source="startup")
        self.app.tracker.get("s1").pid = 4242
        pet = self.app.actors["s1"].pet
        self.app.on_session(self.app.tracker.get("s1"), [])
        state = self.app.tracker.get("s1")
        state.session_id = "s9"                              # what the tracker does on /clear
        self.app.on_session(state, [("session_start", {"source": "clear", "replaces": "s1"})])
        self.assertEqual(list(self.app.actors), ["s9"])
        self.assertIs(self.app.actors["s9"].pet, pet)


if __name__ == "__main__":
    unittest.main()

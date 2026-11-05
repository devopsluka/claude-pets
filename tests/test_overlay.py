"""Pointer handling of a pet window (needs an X display; skipped without one)."""

import os
import random
import tempfile
import types
import unittest

HAVE_DISPLAY = bool(os.environ.get("DISPLAY"))
if HAVE_DISPLAY:
    os.environ["GDK_BACKEND"] = "x11"
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gtk

        ready = Gtk.init_check([])
        HAVE_DISPLAY = bool(ready[0] if isinstance(ready, tuple) else ready)
    except Exception:
        HAVE_DISPLAY = False


class FakeApp:
    def __init__(self, theme, cfg):
        self.theme, self.cfg = theme, cfg
        self.clicked, self.focused, self.menus, self.petted = [], [], [], []
        self.card = types.SimpleNamespace(hide=lambda *a: None, show_for=lambda *a: None)

    def pet_clicked(self, pet, timestamp=0):
        self.clicked.append((pet, timestamp))

    def pet_double_clicked(self, pet, timestamp=0):
        self.focused.append(pet)

    def pet_petted(self, pet):
        self.petted.append(pet)

    def show_menu(self, window, event):
        self.menus.append(window)


@unittest.skipUnless(HAVE_DISPLAY, "no X display")
class PetWindowTests(unittest.TestCase):
    def setUp(self):
        from claude_pets import config as config_mod
        from claude_pets.brain import Pet, World
        from claude_pets.overlay import PetWindow
        from claude_pets.render.tokens import Theme
        from claude_pets.store import Store

        self.tmp = tempfile.TemporaryDirectory()
        cfg = dict(config_mod.DEFAULTS)
        world = World(0, 32, 1920, 1194, 1.0, cfg, random.Random(2))
        self.pet = Pet("sid", Store(self.tmp.name).get("/work/demo"), world, 1000.0)
        world.pets.append(self.pet)
        for _ in range(90):
            self.pet.update(1 / 30, 1000.0)
        self.app = FakeApp(Theme("dark"), cfg)
        self.window = PetWindow(self.app, self.pet)

    def tearDown(self):
        self.window.destroy()
        self.tmp.cleanup()

    def event(self, kind=None, **kw):
        base = dict(button=1, type=kind or Gdk.EventType.BUTTON_PRESS, x=170.0, y=200.0, x_root=900.0,
                    y_root=1100.0, time=1000, state=Gdk.ModifierType(0), mode=Gdk.CrossingMode.NORMAL)
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_click_reports_the_pet_and_the_event_time(self):
        self.window.on_press(None, self.event())
        self.window.on_release(None, self.event(Gdk.EventType.BUTTON_RELEASE, time=1080))
        self.assertEqual(self.app.clicked, [(self.pet, 1080)])     # the time becomes the activation token
        self.assertFalse(self.pet.held)

    def test_double_click_is_reported_separately(self):
        self.window.on_press(None, self.event(Gdk.EventType._2BUTTON_PRESS))
        self.assertEqual(self.app.focused, [self.pet])

    def test_middle_click_and_wheel_pet_it(self):
        self.window.on_press(None, self.event(button=2))
        self.window.on_scroll(None, self.event())
        self.assertEqual(self.app.petted, [self.pet, self.pet])
        self.assertEqual(self.app.clicked, [])

    def test_right_click_opens_the_menu(self):
        self.window.on_press(None, self.event(button=3))
        self.assertEqual(self.app.menus, [self.window])

    def test_drag_carries_and_throws(self):
        held = Gdk.ModifierType.BUTTON1_MASK
        self.window.on_press(None, self.event())
        self.window.on_motion(None, self.event(Gdk.EventType.MOTION_NOTIFY, x_root=902.0, state=held, time=1010))
        self.assertFalse(self.pet.held)                      # below the drag threshold
        for i in range(1, 8):
            self.window.on_motion(None, self.event(Gdk.EventType.MOTION_NOTIFY, x_root=900.0 + i * 30,
                                                   y_root=1100.0 - i * 20, state=held, time=1010 + i * 16))
        self.assertTrue(self.pet.held)
        self.window.on_release(None, self.event(Gdk.EventType.BUTTON_RELEASE, time=1010 + 8 * 16))
        self.assertFalse(self.pet.held)
        self.assertTrue(self.pet.airborne)
        self.assertGreater(self.pet.vx, 500)                 # thrown to the right
        self.assertEqual(self.app.clicked, [])

    def test_render_reports_a_dirty_rectangle_inside_the_window(self):
        x0, y0, x1, y1 = self.window.render()
        self.assertEqual((x0, y0, x1, y1), (0, 0, self.window.width, self.window.height))   # first paint: all
        x0, y0, x1, y1 = self.window.render()
        self.assertTrue(0 <= x0 < x1 <= self.window.width and 0 <= y0 < y1 <= self.window.height)
        self.assertLess((x1 - x0) * (y1 - y0), self.window.width * self.window.height / 2)

    def test_hover_points_the_eyes(self):
        self.window.on_enter(None, self.event())
        self.window.on_motion(None, self.event(Gdk.EventType.MOTION_NOTIFY, x=200.0, y=180.0))
        self.assertTrue(self.pet.hover)
        self.assertIsNotNone(self.pet.pointer)
        self.window.on_leave(None, self.event())
        self.assertFalse(self.pet.hover)


if __name__ == "__main__":
    unittest.main()

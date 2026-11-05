"""Desktop windows: one small transparent, click-through window per pet plus
the hover card. Override-redirect X11 windows (through XWayland on a Wayland
desktop) are the one portable way to place something at an exact spot above
everything else without a compositor extension.
"""

import logging
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .render import scene  # noqa: E402
from .render.bubble import CARD_H, CARD_W, draw_card  # noqa: E402

log = logging.getLogger("claude-pets.overlay")

DRAG_THRESHOLD = 6.0
EVENTS = (Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
          | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_MOTION_MASK
          | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
          | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)


def _popup(width, height):
    win = Gtk.Window(type=Gtk.WindowType.POPUP)
    win.set_app_paintable(True)
    visual = win.get_screen().get_rgba_visual()
    if visual is not None:
        win.set_visual(visual)
    win.set_accept_focus(False)
    win.set_decorated(False)
    win.set_default_size(width, height)
    win.resize(width, height)
    return win


class PetWindow:
    def __init__(self, app, pet):
        self.app = app
        self.pet = pet
        self.scale = pet.world.scale
        self.width, self.height = scene.window_size(self.scale)
        self.frac = (0.0, 0.0)
        self.pos = None
        self.visible = False
        self.press = None                  # (x_root, y_root) of a button-1 press
        self.dragging = False
        self.trail = []                    # recent (time, x, y) while dragging
        self.hover_timer = 0
        win = self.win = _popup(self.width, self.height)
        win.set_title("Claude Pet")
        # Frames are rasterised here, into a client-side buffer, and only the
        # part that changed is handed to the X server as one image.
        factor = self.factor = max(1, win.get_scale_factor())
        self.buffer = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width * factor, self.height * factor)
        self.buffer.set_device_scale(factor, factor)
        self.buffer_cr = cairo.Context(self.buffer)
        self.painted = None                # extents of what the buffer currently shows
        win.add_events(EVENTS)
        win.connect("draw", self.on_draw)
        win.connect("button-press-event", self.on_press)
        win.connect("button-release-event", self.on_release)
        win.connect("motion-notify-event", self.on_motion)
        win.connect("enter-notify-event", self.on_enter)
        win.connect("leave-notify-event", self.on_leave)
        win.connect("scroll-event", self.on_scroll)
        self.sync(force=True)

    # -- placement ------------------------------------------------------

    def sync(self, force=False):
        """Move the window so the pet's ground point lands on (pet.x, pet.y)."""
        ax, ay = scene.anchor(self.scale)
        pet = self.pet
        left, top = pet.x - ax, pet.y - ay
        if pet.moving or pet.held or pet.airborne:
            ix, iy = int(left // 1), int(top // 1)
            self.frac = (left - ix, top - iy)
        else:                               # at rest: whole pixels keep the cached layers crisp
            ix, iy = int(round(left)), int(round(top))
            self.frac = (0.0, 0.0)
        if force or self.pos != (ix, iy):
            self.pos = (ix, iy)
            self.win.move(ix, iy)

    def show(self):
        if self.visible:
            return
        self.visible = True
        self.painted = None
        self.render()
        self.win.show()
        self.win.move(*self.pos)
        x, y, w, h = scene.body_rect(self.scale)
        self.win.input_shape_combine_region(cairo.Region(cairo.RectangleInt(x, y, w, h)))

    def hide(self):
        if self.visible:
            self.visible = False
            self.win.hide()

    def render(self):
        """Repaint the changed part of the buffer; returns the dirty rectangle."""
        box = scene.scene_extents(self.pet, self.width, self.height, self.frac)
        if self.painted is None:
            dirty = (0, 0, self.width, self.height)
        else:
            old = self.painted
            dirty = (min(box[0], old[0]), min(box[1], old[1]), max(box[2], old[2]), max(box[3], old[3]))
        self.painted = box
        cr = self.buffer_cr
        cr.save()
        cr.rectangle(dirty[0], dirty[1], dirty[2] - dirty[0], dirty[3] - dirty[1])
        cr.clip()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        try:
            scene.draw_scene(cr, self.pet, self.width, self.height, self.app.theme, self.app.cfg,
                             time.time(), frac=self.frac, clear=False, factor=self.factor)
        except Exception:
            log.exception("draw failed")
        cr.restore()
        self.buffer.flush()
        return dirty

    def redraw(self):
        if self.visible:
            x0, y0, x1, y1 = self.render()
            self.win.queue_draw_area(x0, y0, x1 - x0, y1 - y0)

    def destroy(self):
        if self.hover_timer:
            GLib.source_remove(self.hover_timer)
            self.hover_timer = 0
        self.win.destroy()

    # -- drawing --------------------------------------------------------

    def on_draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(self.buffer, 0, 0)
        cr.paint()
        return True

    # -- pointer --------------------------------------------------------

    def on_press(self, _widget, event):
        if event.button == 1:
            if event.type == Gdk.EventType._2BUTTON_PRESS:
                self.app.pet_double_clicked(self.pet, event.time)
                self.press = None
                return True
            if event.type == Gdk.EventType.BUTTON_PRESS:
                self.press = (event.x_root, event.y_root)
                self.dragging = False
                self.trail = [(event.time, event.x_root, event.y_root)]
        elif event.button == 2 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.app.pet_petted(self.pet)
        elif event.button == 3 and event.type == Gdk.EventType.BUTTON_PRESS:
            self.app.show_menu(self, event)
        return True

    def on_scroll(self, _widget, _event):
        """Stroking the pet with the wheel pets it."""
        self.app.pet_petted(self.pet)
        return True

    def on_motion(self, _widget, event):
        pet = self.pet
        if self.press is not None and event.state & Gdk.ModifierType.BUTTON1_MASK:
            if not self.dragging:
                dx, dy = event.x_root - self.press[0], event.y_root - self.press[1]
                if dx * dx + dy * dy < DRAG_THRESHOLD ** 2:
                    return True
                self.dragging = True
                self.app.card.hide()
                pet.grab(event.x_root, event.y_root)
            pet.drag_to(event.x_root, event.y_root)
            self.trail.append((event.time, event.x_root, event.y_root))
            del self.trail[:-6]
        else:
            ax, ay = scene.anchor(self.scale)
            pet.pointer = ((event.x - ax) / self.scale, (event.y - ay) / self.scale)
        return True

    def on_release(self, _widget, event):
        if event.button != 1:
            return True
        pet = self.pet
        if self.dragging:
            vx = vy = 0.0
            if len(self.trail) >= 2:
                t0, x0, y0 = self.trail[0]
                t1, x1, y1 = self.trail[-1]
                span = max(1, t1 - t0) / 1000.0
                if event.time - t1 < 120:
                    vx, vy = (x1 - x0) / span, (y1 - y0) / span
            pet.release(vx, vy)
            self.dragging = False
        elif self.press is not None:
            self.app.pet_clicked(pet, event.time)
        self.press = None
        return True

    def on_enter(self, _widget, _event):
        self.pet.hover = True
        if not self.hover_timer and not self.dragging:
            self.hover_timer = GLib.timeout_add(480, self._hover_due)
        return False

    def on_leave(self, _widget, event):
        if self.dragging or event.mode != Gdk.CrossingMode.NORMAL:
            return False
        self.pet.hover = False
        self.pet.pointer = None
        if self.hover_timer:
            GLib.source_remove(self.hover_timer)
            self.hover_timer = 0
        self.app.card.hide(self)
        return False

    def _hover_due(self):
        self.hover_timer = 0
        if self.pet.hover and not self.dragging and self.visible:
            self.app.card.show_for(self)
        return False


class CardWindow:
    """The status card that appears while the pointer rests on a pet."""

    PAD = 6

    def __init__(self, app):
        self.app = app
        self.owner = None
        self.width, self.height = CARD_W + 2 * self.PAD, CARD_H + 2 * self.PAD
        win = self.win = _popup(self.width, self.height)
        win.set_title("Claude Pet card")
        win.connect("draw", self.on_draw)
        self.shown_at = 0.0

    def show_for(self, pet_window):
        self.owner = pet_window
        pet = pet_window.pet
        world = pet.world
        x = int(min(max(pet.x - self.width / 2, world.left + 4), world.right - self.width - 4))
        y = int(pet.y - 128 * world.scale - self.height)
        if pet.bubble:
            y -= int(46 * max(1.0, world.scale * 0.9))
        y = max(int(world.top) + 4, y)
        self.shown_at = time.time()
        self.win.move(x, y)
        self.win.show()
        self.win.move(x, y)
        self.win.input_shape_combine_region(cairo.Region())
        self.win.queue_draw()

    def hide(self, pet_window=None):
        if pet_window is not None and pet_window is not self.owner:
            return
        if self.owner is not None:
            self.owner = None
            self.win.hide()

    def refresh(self):
        if self.owner is not None:
            if self.owner.pet.gone or not self.owner.visible:
                self.hide()
            else:
                self.win.queue_draw()

    def on_draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self.owner is None:
            return True
        try:
            now = time.time()
            alpha = min(1.0, (now - self.shown_at) / 0.12)
            draw_card(cr, self.PAD, self.PAD, self.owner.pet.card_info(now), self.app.theme, alpha)
            if alpha < 1.0:
                GLib.timeout_add(30, lambda: (self.win.queue_draw(), False)[1])
        except Exception:
            log.exception("card draw failed")
        return True

    def destroy(self):
        self.win.destroy()

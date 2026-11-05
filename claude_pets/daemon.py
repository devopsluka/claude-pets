"""The Claude Pets daemon: one small process that watches every Claude Code
session on this machine and keeps a pet on the desktop for each of them.
"""

import fcntl
import glob
import json
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import time

from . import config as config_mod
from . import paths

log = logging.getLogger("claude-pets")


def prepare_environment():
    """Pets are placed with X11 calls, so always talk to X (XWayland on Wayland)."""
    os.environ["GDK_BACKEND"] = "x11"
    os.environ.setdefault("NO_AT_BRIDGE", "1")
    # The daemon outlives the session whose hook started it: don't carry that
    # session's identity into things launched from here (the studio).
    for name in [n for n in os.environ if n.startswith("CLAUDE")
                 and n != "CLAUDE_CONFIG_DIR" and not n.startswith("CLAUDE_PETS_")]:
        del os.environ[name]
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
    xauth = os.environ.get("XAUTHORITY")
    if not xauth or not os.path.exists(xauth):
        runtime = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
        candidates = glob.glob(os.path.join(runtime, ".mutter-Xwaylandauth.*")) + glob.glob(
            os.path.join(runtime, "xauth_*"))
        if candidates:
            os.environ["XAUTHORITY"] = max(candidates, key=os.path.getmtime)


def acquire_lock():
    """Single instance: returns an open, locked fd or None if a daemon is running."""
    paths.ensure_dirs()
    fd = os.open(paths.PID_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, b"%d\n" % os.getpid())
    return fd


def setup_logging(foreground=False):
    paths.ensure_dirs()
    handlers = [logging.handlers.RotatingFileHandler(paths.LOG_FILE, maxBytes=256 * 1024, backupCount=2)]
    if foreground:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class Actor:
    __slots__ = ("pet", "window", "acc", "hidden", "frames", "render_s", "fps", "cost_ms")

    def __init__(self, pet, window):
        self.pet = pet
        self.window = window
        self.acc = 1.0
        self.hidden = False
        self.frames = 0          # repaints since the last 10 s sample
        self.render_s = 0.0
        self.fps = 0.0
        self.cost_ms = 0.0


class App:
    def __init__(self):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gio, GLib, Gtk

        from .brain import World
        from .overlay import CardWindow
        from .registry import RegistryWatcher
        from .render.tokens import Theme
        from .store import Store
        from .tracker import SessionTracker
        from .transcript import TranscriptTailer

        self.Gdk, self.Gio, self.GLib, self.Gtk = Gdk, Gio, GLib, Gtk
        self.Theme = Theme
        self.cfg = config_mod.load()
        self.store = Store(cast=self.cfg.get("cast", "mixed"))
        self.tracker = SessionTracker()
        self.tracker.subscribe(self.on_session)
        self.registry = RegistryWatcher()
        self.tailer = TranscriptTailer()
        self.actors = {}
        self.started = time.time()
        self.empty_since = self.started
        self.hidden_until = 0.0
        self.locked = False
        self.overview = False
        self.last = time.monotonic()
        self.frame_ms = 0
        self.frame_source = 0
        self.seconds = 0
        self.menu = None
        self.demo = None
        self.clock_helper = self.clock_window = None
        self.last_focus = {}
        self.last_focus_result = []
        self.sock = None
        self.interface = None
        self._watch_desktop()
        self.theme = Theme(self._scheme())
        left, top, right, floor = self._measure()
        self.world = World(left, top, right, floor, self.cfg["scale"], self.cfg)
        self.card = CardWindow(self)
        screen = Gdk.Screen.get_default()
        if screen is not None:
            screen.connect("monitors-changed", self._on_monitors)
            screen.connect("size-changed", self._on_monitors)

    # ------------------------------------------------------------------
    # desktop environment
    # ------------------------------------------------------------------

    def _measure(self):
        display = self.Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo, work = monitor.get_geometry(), monitor.get_workarea()
        floor = work.y + work.height - 6 - int(self.cfg.get("floor_offset", 0))
        return geo.x, work.y, geo.x + geo.width, floor

    def _on_monitors(self, *_args):
        try:
            w = self.world
            w.left, w.top, w.right, w.floor = (float(v) for v in self._measure())
            for actor in self.actors.values():
                pet = actor.pet
                pet.home_x = w.clamp_x(pet.home_x)
                pet.x = w.clamp_x(pet.x)
                if not pet.held and not pet.airborne:
                    pet.y = pet._rest_y()
                actor.acc = 1.0
        except Exception:
            log.exception("monitor change failed")

    def _scheme(self):
        choice = self.cfg.get("theme", "auto")
        if choice in ("dark", "light"):
            return choice
        try:
            if self.interface is not None:
                return "dark" if self.interface.get_string("color-scheme") == "prefer-dark" else "light"
        except Exception:
            pass
        return "dark"

    def _watch_desktop(self):
        Gio = self.Gio
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source is not None and source.lookup("org.gnome.desktop.interface", True) is not None:
                self.interface = Gio.Settings.new("org.gnome.desktop.interface")
                self.interface.connect("changed::color-scheme", self._on_scheme)
        except Exception:
            log.info("no desktop interface settings")
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.bus.signal_subscribe(None, "org.gnome.ScreenSaver", "ActiveChanged", "/org/gnome/ScreenSaver",
                                      None, Gio.DBusSignalFlags.NONE, self._on_lock)
            self.bus.signal_subscribe("org.gnome.Shell", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                      "/org/gnome/Shell", None, Gio.DBusSignalFlags.NONE, self._on_shell_props)
        except Exception:
            self.bus = None
            log.info("no session bus; lock/overview hiding disabled")

    def _on_scheme(self, *_args):
        self.theme = self.Theme(self._scheme())
        self._wake_all()

    def _on_lock(self, _conn, _sender, _path, _iface, _signal, params):
        try:
            self.locked = bool(params.unpack()[0])
            self._apply_visibility()
        except Exception:
            log.exception("lock signal")

    def _on_shell_props(self, _conn, _sender, _path, _iface, _signal, params):
        try:
            iface, changed, _invalid = params.unpack()
            if iface == "org.gnome.Shell" and "OverviewActive" in changed:
                self.overview = bool(changed["OverviewActive"])
                self._apply_visibility()
        except Exception:
            log.exception("shell signal")

    def visible(self):
        return not self.locked and not self.overview and time.time() >= self.hidden_until

    def _apply_visibility(self):
        show = self.visible()
        for actor in self.actors.values():
            if show and not actor.hidden:
                actor.window.sync(force=True)
                actor.window.show()
                actor.acc = 1.0
            else:
                actor.window.hide()
        if not show:
            self.card.hide()
        self._schedule_frames(force=True)

    def _wake_all(self):
        for actor in self.actors.values():
            actor.acc = 1.0

    # ------------------------------------------------------------------
    # sessions -> pets
    # ------------------------------------------------------------------

    def _wanted(self, state):
        if state.headless and not self.cfg.get("headless", True):
            return False
        return len(self.actors) < int(self.cfg.get("max_pets", 12))

    def _spawn(self, state, signals):
        from .brain import Pet
        from .model import Signal
        from .overlay import PetWindow
        from .render.creature import SPECIES
        from .store import apply_changes, normalize_cwd, pet_key

        cwd = normalize_cwd(state.cwd)
        used = {a.pet.profile.index for a in self.actors.values()
                if normalize_cwd(a.pet.profile.cwd) == cwd and not a.pet.leaving}
        index = 1
        while index in used:
            index += 1
        fresh = self.store.load_key(pet_key(cwd, index)) is None
        demo = state.entrypoint == "demo"
        profile = self.store.get(cwd, index, persistent=not state.headless and not demo)
        if demo and os.path.basename(cwd) in SPECIES:      # demo sessions can ask for a character
            apply_changes(profile, {"species": os.path.basename(cwd), "accessory": "none"})
        entrance = "pop"
        now = time.time()
        if now - self.started > 2.5:
            for name, data in signals:
                if name == Signal.SESSION_START and (data or {}).get("source") in ("startup", "resume"):
                    entrance = "walk"
        if entrance == "pop" and fresh:
            entrance = "hatch"
        pet = Pet(state.session_id, profile, self.world, now, entrance=entrance)
        self.world.pets.append(pet)
        window = PetWindow(self, pet)
        actor = Actor(pet, window)
        self.actors[state.session_id] = actor
        if self.visible():
            window.show()
        log.info("pet %s (%s the %s) joined for %s [%s]", profile.key, profile.name, profile.design.species,
                 state.cwd, state.session_id[:8])
        self._schedule_frames()
        return actor

    def on_session(self, state, signals):
        from .model import Signal
        try:
            sid = state.session_id
            for name, data in signals:
                old = (data or {}).get("replaces") if name == Signal.SESSION_START else None
                if old and old in self.actors and sid not in self.actors:
                    actor = self.actors.pop(old)
                    actor.pet.key = sid
                    self.actors[sid] = actor
                    self.tailer.unwatch(old)
            actor = self.actors.get(sid)
            if actor is None:
                if state.ended or not self._wanted(state):
                    return
                actor = self._spawn(state, signals)
            actor.pet.on_session(state, signals)
            actor.acc = 1.0
            for name, _data in signals:
                if name == Signal.TURN_DONE and actor.pet.done_big:
                    self._friends_cheer(actor.pet)
            if not state.ended:
                self._watch_transcript(state)
            self._schedule_frames()
        except Exception:
            log.exception("session update failed")

    def _friends_cheer(self, pet):
        friends = [o for o in self.world.others(pet) if abs(o.x - pet.x) < 520 * self.world.scale]
        if friends:
            self.GLib.timeout_add(700, lambda: ([f.cheer_for(pet) for f in friends], False)[1])

    def _watch_transcript(self, state):
        from .transcript import transcript_path_for
        try:
            path = state.transcript_path or transcript_path_for(state.session_id, state.cwd)
            if path and self.tailer.watching(state.session_id) != path:
                self.tailer.watch(state.session_id, path)
        except Exception:
            log.exception("transcript watch failed")

    def _remove(self, sid):
        actor = self.actors.pop(sid, None)
        if actor is None:
            return
        pet = actor.pet
        if pet in self.world.pets:
            self.world.pets.remove(pet)
        self.card.hide(actor.window)
        actor.window.destroy()
        self.tailer.unwatch(sid)
        try:
            self.store.save(pet.profile)
        except OSError:
            log.exception("profile save failed")
        log.info("pet %s left", pet.profile.key)

    # ------------------------------------------------------------------
    # main loop pieces
    # ------------------------------------------------------------------

    def _schedule_frames(self, force=False):
        """Run the animation timer only as fast as the liveliest pet needs."""
        fps = 0
        if self.visible():
            for actor in self.actors.values():
                if not actor.hidden:
                    fps = max(fps, actor.pet.desired_fps())
        elif self.actors:
            fps = 2
        interval = 0 if fps == 0 else max(33, min(250, int(1000 / fps)))
        if interval == self.frame_ms and not force:
            return
        if self.frame_source:
            self.GLib.source_remove(self.frame_source)
            self.frame_source = 0
        self.frame_ms = interval
        if interval:
            self.last = time.monotonic()
            self.frame_source = self.GLib.timeout_add(interval, self.on_frame)

    def on_frame(self):
        try:
            mono = time.monotonic()
            dt = mono - self.last
            self.last = mono
            now = time.time()
            self.world.now = now
            show = self.visible()
            gone = []
            for sid, actor in self.actors.items():
                pet = actor.pet
                steps = max(1, min(6, int(round(dt / 0.034))))
                for _ in range(steps):
                    pet.update(dt / steps, now)
                if pet.gone:
                    gone.append(sid)
                    continue
                if not show or actor.hidden:
                    continue
                actor.acc += dt
                if actor.acc >= 1.0 / pet.desired_fps() - 0.006:
                    actor.acc = 0.0
                    began = time.perf_counter()
                    actor.window.sync()
                    actor.window.redraw()
                    actor.frames += 1
                    actor.render_s += time.perf_counter() - began
            for sid in gone:
                self._remove(sid)
            self._schedule_frames()
        except Exception:
            log.exception("frame failed")
        return True

    def on_second(self):
        try:
            self.seconds += 1
            now = time.time()
            if self.demo is not None:
                self.demo.step(now)
            self.tracker.tick(now)
            self.tracker.feed_registry(self.registry.poll())
            if self.seconds % 2 == 0:
                for sid, (records, initial) in self.tailer.poll().items():
                    if records:
                        self.tracker.feed_transcript(sid, records, initial=initial)
            self.card.refresh()
            if self.hidden_until and now >= self.hidden_until:
                self.hidden_until = 0.0
                self._apply_visibility()
            if self.seconds % 10 == 0:
                for actor in self.actors.values():
                    actor.fps = actor.frames / 10.0
                    actor.cost_ms = actor.render_s * 100.0      # ms of rendering per second
                    actor.frames, actor.render_s = 0, 0.0
                    if actor.pet.dirty_profile:
                        actor.pet.dirty_profile = False
                        self.store.save(actor.pet.profile)
            if self.actors:
                self.empty_since = now
            else:
                limit = int(self.cfg.get("exit_when_empty", 180))
                if limit and now - self.empty_since > limit and now - self.started > 20:
                    log.info("no sessions for %ds; going home", limit)
                    self.quit()
            self._schedule_frames()
        except Exception:
            log.exception("tick failed")
        return True

    # ------------------------------------------------------------------
    # pointer actions
    # ------------------------------------------------------------------

    def pet_clicked(self, pet, timestamp=0):
        """A plain click: go to the session's terminal (or pet it, if so configured)."""
        if self.cfg.get("click", "terminal") == "terminal":
            self.focus_session(pet, timestamp)
        else:
            self.pet_petted(pet)

    def pet_double_clicked(self, pet, timestamp=0):
        if self.cfg.get("click", "terminal") != "terminal":
            self.focus_session(pet, timestamp)

    def pet_petted(self, pet):
        if pet.petted(time.time()):
            self.tracker.nudge(pet.key, mood=0.04, stress=-0.04)

    def _server_time(self):
        """Current X server time (the clock activation timestamps are compared on)."""
        try:
            import gi
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            if self.clock_window is None:
                helper = self.Gtk.Invisible()
                helper.realize()
                window = helper.get_window()
                window.set_events(window.get_events() | self.Gdk.EventMask.PROPERTY_CHANGE_MASK)
                self.clock_helper, self.clock_window = helper, window
            return GdkX11.x11_get_server_time(self.clock_window)
        except Exception:
            log.exception("server time unavailable")
            return 0

    def make_token(self, desktop_id=None, timestamp=0):
        """Mint an activation token for "the user asked for this just now".

        It is an X11 startup-notification id; mutter treats those like
        xdg-activation tokens, which is what lets a Wayland terminal raise
        itself when a pet is clicked.
        """
        Gio, GLib = self.Gio, self.GLib
        display = self.Gdk.Display.get_default()
        if display is None:
            return ""
        context = display.get_app_launch_context()
        # "Now" on the X server's clock is never older than the click that got
        # us here, which is what the compositor checks the token against.
        stamp = int(self._server_time() or timestamp or 0)
        if stamp:
            context.set_timestamp(stamp)
        info = None
        if desktop_id:
            try:
                try:
                    import gi
                    gi.require_version("GioUnix", "2.0")
                    from gi.repository import GioUnix
                    info = GioUnix.DesktopAppInfo.new(desktop_id)
                except (ImportError, ValueError, AttributeError):
                    info = Gio.DesktopAppInfo.new(desktop_id)
            except TypeError:
                info = None
        if info is None:
            info = Gio.AppInfo.create_from_commandline("true", "Terminal",
                                                       Gio.AppInfoCreateFlags.SUPPORTS_STARTUP_NOTIFICATION)
        token = context.get_startup_notify_id(info, []) or ""
        if token:
            GLib.timeout_add(2500, lambda: (context.launch_failed(token), False)[1])
        return token

    def focus_session(self, pet, timestamp=0):
        """Bring the terminal that hosts this pet's session to the front."""
        from .focus import focus_terminal
        now = time.monotonic()
        if now - self.last_focus.get(pet.key, -10.0) < 0.6:
            return self.last_focus_result
        self.last_focus[pet.key] = now
        state = pet.session
        done = focus_terminal(
            state.term if state else {}, pid=state.pid if state else None,
            cwd=(state.cwd if state else "") or pet.profile.cwd,
            make_token=lambda desktop_id: self.make_token(desktop_id, timestamp))
        if any(how in done for how in ("kitty", "app", "x11")):
            pet.start_react("hop", 0.45)
            pet.say("This way!", "info", ttl=1.8, emoji="👉")
        elif done:
            pet.say("I rang my terminal's bell", "info", emoji="🔔")
        else:
            pet.say("I can't find my terminal", "say", emoji="🤷")
        log.info("focus %s -> %s", pet.profile.key, done)
        self.last_focus_result = done
        return done

    def open_studio(self, pet=None, key=None):
        env = dict(os.environ)
        env.pop("GDK_BACKEND", None)
        argv = [sys.executable, "-I", os.path.join(paths.APP_ROOT, "bin", "claude-pets"), "design"]
        target = key or (pet.profile.key if pet else None)
        if target:
            argv += ["--key", target]
        try:
            subprocess.Popen(argv, env=env, cwd="/", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            log.exception("could not open the studio")

    def show_menu(self, window, event):
        Gtk, GLib = self.Gtk, self.GLib
        pet = window.pet
        actor = next((a for a in self.actors.values() if a.pet is pet), None)
        menu = Gtk.Menu()

        def add(label, callback=None, sensitive=True):
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(sensitive)
            if callback is not None:
                item.connect("activate", lambda *_a: callback())
            menu.append(item)
            return item

        add("%s · %s · Lv %d" % (pet.name, pet.profile.project, pet.profile.level), sensitive=False)
        menu.append(Gtk.SeparatorMenuItem())
        add("Go to its terminal", lambda: self.focus_session(pet, getattr(event, "time", 0)))
        add(pet.trait.poke_label.format(name=pet.name), lambda: self.pet_petted(pet))
        add("Give a treat", pet.treat)
        add("Design %s…" % pet.name, lambda: self.open_studio(pet))
        menu.append(Gtk.SeparatorMenuItem())
        if actor is not None:
            add("Tuck this pet away", lambda: self.set_actor_hidden(actor, True))
        add("Hide all pets for an hour", lambda: self.hide_for(3600))
        bubbles = Gtk.MenuItem(label="Speech bubbles")
        sub = Gtk.Menu()
        group = None
        for value, label in (("all", "Everything"), ("important", "Only important"), ("off", "Off")):
            radio = Gtk.RadioMenuItem(label=label, group=group)
            group = group or radio
            radio.set_active(self.cfg.get("bubbles") == value)
            radio.connect("toggled", lambda item, v=value: item.get_active() and self.set_config("bubbles", v))
            sub.append(radio)
        bubbles.set_submenu(sub)
        menu.append(bubbles)
        menu.append(Gtk.SeparatorMenuItem())
        add("Quit Claude Pets", lambda: self.quit(stopped=True))
        menu.show_all()
        menu.attach_to_widget(window.win, None)
        self.menu = menu
        state = {"timer": 0}

        def close():
            state["timer"] = 0
            menu.popdown()
            return False

        def on_leave(*_a):
            if not state["timer"]:
                state["timer"] = GLib.timeout_add(2500, close)
            return False

        def on_enter(*_a):
            if state["timer"]:
                GLib.source_remove(state["timer"])
                state["timer"] = 0
            return False

        for widget in (menu, sub):
            widget.connect("leave-notify-event", on_leave)
            widget.connect("enter-notify-event", on_enter)
        menu.connect("hide", lambda *_a: on_enter())
        menu.popup_at_pointer(event)

    def set_actor_hidden(self, actor, hidden):
        actor.hidden = hidden
        self._apply_visibility()

    def hide_for(self, seconds):
        self.hidden_until = time.time() + min(seconds, 366 * 86400.0) if seconds > 0 else 0.0
        if seconds <= 0:
            for actor in self.actors.values():
                actor.hidden = False
        self._apply_visibility()

    def set_config(self, key, value):
        self.cfg[key] = value
        try:
            config_mod.save(self.cfg)
        except OSError:
            log.exception("config save failed")
        self.reload_config()

    def reload_config(self):
        from .overlay import PetWindow
        old_scale = self.world.scale
        self.cfg = config_mod.load()
        self.store.cast = self.cfg.get("cast", "mixed")
        self.world.config = self.cfg
        self.world.scale = self.cfg["scale"]
        self.theme = self.Theme(self._scheme())
        self._on_monitors()
        if abs(old_scale - self.world.scale) > 1e-6:
            show = self.visible()
            for actor in self.actors.values():
                actor.window.destroy()
                actor.window = PetWindow(self, actor.pet)
                if show and not actor.hidden:
                    actor.window.show()
        self._wake_all()

    # ------------------------------------------------------------------
    # control socket
    # ------------------------------------------------------------------

    def listen(self):
        paths.ensure_runtime_dir()
        try:
            os.unlink(paths.SOCKET_PATH)
        except OSError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(paths.SOCKET_PATH)
        os.chmod(paths.SOCKET_PATH, 0o600)
        sock.listen(64)
        sock.setblocking(False)
        self.sock = sock
        self.GLib.io_add_watch(sock.fileno(), self.GLib.PRIORITY_DEFAULT, self.GLib.IO_IN, self.on_incoming)

    def on_incoming(self, _fd, _condition):
        for _ in range(32):
            try:
                conn, _addr = self.sock.accept()
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                log.exception("accept failed")
                break
            try:
                self._serve(conn)
            except Exception:
                log.exception("request failed")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        return True

    def _serve(self, conn):
        conn.settimeout(0.25)
        chunks = []
        size = 0
        while size < 262144:
            try:
                data = conn.recv(65536)
            except (socket.timeout, OSError):
                break
            if not data:
                break
            chunks.append(data)
            size += len(data)
            if b"\n" in data:
                break
        line = b"".join(chunks).split(b"\n", 1)[0].strip()
        if not line:
            return
        try:
            msg = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("type")
        if kind == "hook":
            self.tracker.feed_hook(msg)
        elif kind == "cmd":
            try:
                reply = self.command(str(msg.get("cmd") or ""), msg.get("args") or {})
            except Exception as exc:
                log.exception("command failed")
                reply = {"ok": False, "error": str(exc)}
            try:
                conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            except OSError:
                pass

    # -- commands -----------------------------------------------------------

    def _find_actor(self, target):
        if not target:
            return None
        target = str(target)
        if target in self.actors:
            return self.actors[target]
        low = target.lower()
        for sid, actor in self.actors.items():
            prof = actor.pet.profile
            if low in (prof.key.lower(), prof.name.lower(), prof.project.lower()) or sid.startswith(target):
                return actor
        from .store import normalize_cwd
        for actor in self.actors.values():
            if normalize_cwd(actor.pet.profile.cwd) == normalize_cwd(target):
                return actor
        return None

    def describe(self, sid, actor):
        pet, s = actor.pet, actor.pet.session
        prof = pet.profile
        out = {
            "session_id": sid, "key": prof.key, "name": prof.name, "species": prof.design.species,
            "project": prof.project, "cwd": prof.cwd, "level": prof.level, "xp": prof.xp,
            "hidden": actor.hidden, "x": round(pet.x), "y": round(pet.y), "mode": pet.mode,
            "doing": pet.status_line(time.time()), "fps": actor.fps, "render_ms_per_s": round(actor.cost_ms, 1),
            "idle_action": pet.idle if pet.mode == "idle" else "",
        }
        try:
            out["xid"] = actor.window.win.get_window().get_xid() if actor.window.visible else None
        except Exception:
            out["xid"] = None
        if s is not None:
            out.update(activity=s.activity, emotion=s.emotion, energy=round(s.energy, 2), mood=round(s.mood, 2),
                       stress=round(s.stress, 2), focus=round(s.focus, 2), context_pct=s.context_pct,
                       has_hooks=s.has_hooks, headless=s.headless, session_name=s.name, pid=s.pid,
                       needs_user=s.needs_user)
        return out

    def command(self, cmd, args):
        from .store import apply_changes
        if cmd in ("status", "list"):
            return {
                "ok": True, "pid": os.getpid(), "uptime": round(time.time() - self.started),
                "visible": self.visible(), "hidden_for": max(0, round(self.hidden_until - time.time())),
                "scale": self.world.scale, "frame_ms": self.frame_ms,
                "pets": [self.describe(sid, a) for sid, a in self.actors.items()],
            }
        if cmd == "quit":
            self.GLib.idle_add(lambda: (self.quit(stopped=bool(args.get("stopped"))), False)[1])
            return {"ok": True}
        if cmd == "hide":
            self.hide_for(float(args.get("minutes", 60)) * 60.0)
            return {"ok": True, "hidden_for": round(self.hidden_until - time.time())}
        if cmd == "show":
            self.hide_for(0)
            return {"ok": True}
        if cmd == "toggle":
            self.hide_for(0 if not self.visible() else 3600 * 12)
            return {"ok": True, "visible": self.visible()}
        if cmd == "reload":
            self.reload_config()
            return {"ok": True}
        if cmd == "design":
            target = args.get("target") or args.get("session_id") or args.get("key")
            actor = self._find_actor(target)
            profile = actor.pet.profile if actor else self.store.find(str(target or ""))
            if profile is None:
                return {"ok": False, "error": "no pet matches %r" % (target,)}
            changed, errors = apply_changes(profile, args.get("set") or {})
            if changed:
                profile.persistent = True if actor is None else profile.persistent
                self.store.save(profile)
                if actor is not None and not args.get("quiet"):
                    actor.pet.fx.sparkles(8, 0, -44, 40)
                    actor.pet.say("New look!", "info", emoji="✨")
                    actor.acc = 1.0
                    self._schedule_frames()
            return {"ok": not errors or bool(changed), "changed": changed, "errors": errors,
                    "profile": profile.to_json(), "live": actor is not None}
        if cmd == "studio":
            actor = self._find_actor(args.get("target"))
            self.open_studio(actor.pet if actor else None, key=None if actor else args.get("target"))
            return {"ok": True}
        if cmd == "poke":
            cmd = "pet"
        if cmd in ("say", "treat", "pet", "focus"):
            actor = self._find_actor(args.get("target")) or next(iter(self.actors.values()), None)
            if actor is None:
                return {"ok": False, "error": "no pets are out right now"}
            if cmd == "say":
                actor.pet.say(str(args.get("text") or "…")[:120], str(args.get("style") or "say"),
                              ttl=float(args.get("ttl", 5.0)), important=True)
            elif cmd == "treat":
                actor.pet.treat()
            elif cmd == "pet":
                self.pet_petted(actor.pet)
            else:
                how = self.focus_session(actor.pet)
                actor.acc = 1.0
                self._schedule_frames()
                return {"ok": bool(how), "name": actor.pet.name, "how": how,
                        "error": "%s could not find its terminal" % actor.pet.name}
            actor.acc = 1.0
            self._schedule_frames()
            return {"ok": True, "name": actor.pet.name}
        if cmd == "demo":
            from .demo import Demo
            if args.get("stop"):
                if self.demo is not None:
                    self.demo.stop()
                    self.demo = None
                return {"ok": True}
            if self.demo is None:
                self.demo = Demo(self.tracker)
            self.demo.start(int(args.get("count", 3)), time.time(), cast=str(args.get("cast") or ""),
                            seconds=float(args.get("seconds") or 0))
            return {"ok": True, "sessions": self.demo.session_ids()}
        if cmd == "snapshot":
            from .render import scene
            out_dir = str(args.get("dir") or paths.STATE_DIR)
            os.makedirs(out_dir, exist_ok=True)
            files = []
            now = time.time()
            for sid, actor in self.actors.items():
                path = os.path.join(out_dir, "pet-%s.png" % actor.pet.profile.key)
                scene.render_png(path, actor.pet, self.theme, self.cfg, now, background=args.get("background"))
                files.append(path)
            return {"ok": True, "files": files}
        return {"ok": False, "error": "unknown command: %s" % cmd}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def run(self):
        GLib = self.GLib
        self.listen()
        GLib.timeout_add(1000, self.on_second)
        try:
            import gi
            gi.require_version("GLibUnix", "2.0")
            from gi.repository import GLibUnix
            add_signal = GLibUnix.signal_add
        except (ImportError, ValueError, AttributeError):
            add_signal = GLib.unix_signal_add
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            add_signal(GLib.PRIORITY_HIGH, signum, lambda *_a: (self.quit(), False)[1])
        try:
            self.tracker.feed_registry(self.registry.poll())
        except Exception:
            log.exception("initial registry poll failed")
        self._schedule_frames()
        log.info("claude-pets daemon up (pid %d, %d session(s))", os.getpid(), len(self.actors))
        self.Gtk.main()

    def quit(self, stopped=False):
        log.info("shutting down%s", " (stopped by user)" if stopped else "")
        for actor in list(self.actors.values()):
            try:
                self.store.save(actor.pet.profile)
            except OSError:
                pass
        if stopped:
            try:
                paths.ensure_runtime_dir()
                open(paths.STOPPED_FLAG, "w").close()
            except OSError:
                pass
        try:
            if self.sock is not None:
                self.sock.close()
            os.unlink(paths.SOCKET_PATH)
        except OSError:
            pass
        self.Gtk.main_quit()


def _note_crash():
    """Hooks restart a missing daemon; after repeated crashes, stop asking them to."""
    marker = os.path.join(paths.RUNTIME_DIR, "crashes")
    now = time.time()
    try:
        with open(marker, "a+", encoding="utf-8") as fh:
            fh.seek(0)
            recent = [float(x) for x in fh.read().split() if now - float(x) < 600]
            recent.append(now)
            fh.seek(0)
            fh.truncate()
            fh.write(" ".join("%.0f" % t for t in recent))
        if len(recent) >= 3:
            open(paths.STOPPED_FLAG, "w").close()
            log.error("crashed %d times in 10 minutes; staying down until `claude-pets start`", len(recent))
    except (OSError, ValueError):
        pass


def main(foreground=False):
    prepare_environment()
    lock = acquire_lock()
    if lock is None:
        return 0
    setup_logging(foreground)
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        ok = Gtk.init_check(sys.argv)
        if isinstance(ok, tuple):
            ok = ok[0]
        if not ok:
            log.error("no display available; not starting")
            return 1
        App().run()
    except Exception:
        log.exception("daemon crashed")
        _note_crash()
        return 1
    finally:
        try:
            os.unlink(paths.PID_FILE)
        except OSError:
            pass
        os.close(lock)
    return 0


if __name__ == "__main__":
    sys.exit(main(foreground=True))

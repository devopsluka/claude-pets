"""Bring a session's terminal app to the front ("click a pet, go to its terminal").

On Wayland one app may not raise another app's window — unless it can show
the compositor an *activation token* that proves the user just asked for it.
A click on a pet is exactly that, so:

1. the daemon mints a token from the click (an X11 startup-notification id,
   which mutter also accepts as an ``xdg-activation`` token), and
2. hands it to the terminal through whatever door that terminal has:

   * **kitty** — a tiny kitten run over remote control focuses the right
     kitty window/tab and activates its OS window with the token;
   * **GNOME Terminal, Ptyxis, Console, Ghostty…** — D-Bus application
     activation with the token;
   * **X11 / XWayland apps** (VS Code, JetBrains, xterm…) — plain EWMH
     activation of the window that owns the session;
   * **tmux / WezTerm** — their own pane selection first.

If nothing can raise the window, the terminal bell is rung on the session's
tty so the desktop at least flags it ("… is ready").
"""

import os
import shutil
import subprocess

KITTEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kitty_focus.py")

#: process name -> (D-Bus application id, desktop file id)
GAPPLICATIONS = {
    "ptyxis": ("org.gnome.Ptyxis", "org.gnome.Ptyxis.desktop"),
    "ptyxis-agent": ("org.gnome.Ptyxis", "org.gnome.Ptyxis.desktop"),
    "gnome-terminal-": ("org.gnome.Terminal", "org.gnome.Terminal.desktop"),
    "gnome-terminal-server": ("org.gnome.Terminal", "org.gnome.Terminal.desktop"),
    "kgx": ("org.gnome.Console", "org.gnome.Console.desktop"),
    "ghostty": ("com.mitchellh.ghostty", "com.mitchellh.ghostty.desktop"),
    "tilix": ("com.gexperts.Tilix", "com.gexperts.Tilix.desktop"),
    "xfce4-terminal": ("org.xfce.Terminal", "xfce4-terminal.desktop"),
}

_ENV_KEYS = {
    "KITTY_WINDOW_ID": "kitty_window_id", "KITTY_LISTEN_ON": "kitty_listen_on", "TMUX": "tmux",
    "TMUX_PANE": "tmux_pane", "WEZTERM_PANE": "wezterm_pane", "WINDOWID": "windowid",
    "TERM_PROGRAM": "term_program",
}


def _run(argv, timeout=1.5, capture=False):
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None if capture else False
    if capture:
        return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else None
    return proc.returncode == 0


def term_from_pid(pid):
    """Terminal details of a running session, read from its own process
    (covers sessions that started before the hooks were installed)."""
    term = {}
    if not pid:
        return term
    try:
        with open("/proc/%d/environ" % int(pid), "rb") as fh:
            for item in fh.read().split(b"\0"):
                key, _, value = item.partition(b"=")
                name = _ENV_KEYS.get(key.decode("ascii", "replace"))
                if name and value:
                    term[name] = value.decode("utf-8", "replace")
    except (OSError, ValueError):
        pass
    try:
        tty = os.readlink("/proc/%d/fd/0" % int(pid))
        if tty.startswith(("/dev/pts/", "/dev/tty")):
            term["tty"] = tty
    except (OSError, ValueError):
        pass
    return term


def ancestors(pid, limit=24):
    """``[(pid, name), …]`` from the process itself up towards init."""
    chain = []
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return chain
    while pid > 1 and len(chain) < limit:
        try:
            with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as fh:
                stat = fh.read()
        except OSError:
            break
        name = stat[stat.find("(") + 1:stat.rfind(")")]
        fields = stat[stat.rfind(")") + 2:].split()
        chain.append((pid, name))
        try:
            pid = int(fields[1])
        except (IndexError, ValueError):
            break
    return chain


def tmux_client_pid(term):
    """Pid of a tmux client showing the session's pane (its terminal is what we raise)."""
    sock = (term.get("tmux") or "").split(",")[0]
    base = ["tmux"] + (["-S", sock] if sock else [])
    out = _run(base + ["list-clients", "-F", "#{client_pid}"], capture=True)
    for line in (out or "").split():
        if line.isdigit():
            return int(line)
    return None


def x11_window_for(pids, hint=""):
    """An X11 window owned by one of ``pids`` (prefer one whose title mentions ``hint``)."""
    if not os.environ.get("DISPLAY") or not shutil.which("wmctrl"):
        return None
    out = _run(["wmctrl", "-l", "-p"], capture=True)
    wanted = set(pids)
    best = None
    for line in (out or "").splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4 or not parts[2].isdigit() or int(parts[2]) not in wanted:
            continue
        title = parts[4] if len(parts) > 4 else ""
        if hint and hint.lower() in title.lower():
            return parts[0]
        best = best or parts[0]
    return best


def activate_gapplication(app_id, token):
    """Ask a D-Bus activatable app to present itself, with our activation token."""
    try:
        import gi
        from gi.repository import Gio, GLib
    except Exception:
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        owner = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "NameHasOwner", GLib.Variant("(s)", (app_id,)), GLib.VariantType("(b)"),
                              Gio.DBusCallFlags.NONE, 800, None)
        if not owner.unpack()[0]:
            return False
        data = {"desktop-startup-id": GLib.Variant("s", token), "activation-token": GLib.Variant("s", token)} \
            if token else {}
        bus.call_sync(app_id, "/" + app_id.replace(".", "/"), "org.freedesktop.Application", "Activate",
                      GLib.Variant("(a{sv})", (data,)), None, Gio.DBusCallFlags.NONE, 1500, None)
        return True
    except Exception:
        return False


def desktop_id_for(term, chain):
    """Desktop file of the terminal app (lets the shell tie the token to it)."""
    if term.get("kitty_listen_on"):
        return "kitty.desktop"
    for _pid, name in chain:
        if name in GAPPLICATIONS:
            return GAPPLICATIONS[name][1]
    return None


def focus_terminal(term, pid=None, cwd="", make_token=None):
    """Bring the terminal that hosts a session forward.

    ``term`` is ``SessionState.term`` (may be empty), ``pid`` the session's
    process, ``make_token(desktop_id)`` returns a fresh activation token (or
    ""). Returns the list of things that worked, e.g. ``["kitty"]``.
    """
    done = []
    term = dict(term or {})
    for key, value in term_from_pid(pid).items():
        term.setdefault(key, value)
    host_pid = pid
    hint = os.path.basename(os.path.normpath(cwd)) if cwd else ""

    tmux_pane = term.get("tmux_pane")
    if tmux_pane and shutil.which("tmux"):
        sock = (term.get("tmux") or "").split(",")[0]
        base = ["tmux"] + (["-S", sock] if sock else [])
        if _run(base + ["select-window", "-t", tmux_pane]) | _run(base + ["select-pane", "-t", tmux_pane]):
            done.append("tmux")
        client = tmux_client_pid(term)
        if client:
            host_pid = client
            for key in ("kitty_window_id", "kitty_listen_on", "wezterm_pane", "windowid", "tty"):
                term.pop(key, None)
            term.update(term_from_pid(client))

    chain = ancestors(host_pid)
    token = ""
    if make_token is not None:
        try:
            token = make_token(desktop_id_for(term, chain)) or ""
        except Exception:
            token = ""
    raised = False

    kitty_id, listen = term.get("kitty_window_id"), term.get("kitty_listen_on")
    if kitty_id and listen and shutil.which("kitty"):
        out = _run(["kitty", "@", "--to", listen, "kitten", "--match", "id:%s" % kitty_id, KITTEN, token],
                   capture=True)
        if out is not None and "ok" in out:
            done.append("kitty")
            raised = True
        elif _run(["kitty", "@", "--to", listen, "focus-window", "--match", "id:%s" % kitty_id]):
            done.append("kitty-tab")

    wez = term.get("wezterm_pane")
    if wez and shutil.which("wezterm") and _run(["wezterm", "cli", "activate-pane", "--pane-id", str(wez)]):
        done.append("wezterm")

    if not raised:
        for _pid, name in chain:
            if name in GAPPLICATIONS and activate_gapplication(GAPPLICATIONS[name][0], token):
                done.append("app")
                raised = True
                break

    if not raised:
        window = term.get("windowid") if os.environ.get("DISPLAY") else None
        if not (window and str(window).isdigit() and int(window) > 0):
            window = x11_window_for([p for p, _name in chain], hint)
        if window:
            if (shutil.which("wmctrl") and _run(["wmctrl", "-i", "-a", str(window)])) or (
                    shutil.which("xdotool") and _run(["xdotool", "windowactivate", str(window)])):
                done.append("x11")
                raised = True

    tty = term.get("tty")
    if not raised and tty and tty.startswith("/dev/"):
        try:
            fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                os.write(fd, b"\a")
            finally:
                os.close(fd)
            done.append("bell")
        except OSError:
            pass
    return done

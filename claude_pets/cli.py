"""``claude-pets`` command line."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time

from . import __version__, paths
from . import config as config_mod

SKILLS = ("pet", "pet-design")
SKILL_MARKER = ".claude-pets"


# ----------------------------------------------------------------------------
# talking to the daemon
# ----------------------------------------------------------------------------

def request(cmd, args=None, timeout=3.0):
    """Send one command to the daemon; returns its reply dict or None if it is not running."""
    msg = json.dumps({"type": "cmd", "v": 1, "cmd": cmd, "args": args or {}}) + "\n"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(paths.SOCKET_PATH)
        sock.sendall(msg.encode("utf-8"))
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode("utf-8")) if data.strip() else {"ok": True}
    except (OSError, ValueError):
        return None
    finally:
        sock.close()


def daemon_running():
    return request("status", timeout=1.0) is not None


def spawn_daemon(wait=4.0):
    env = dict(os.environ)
    env["GDK_BACKEND"] = "x11"
    subprocess.Popen(
        [sys.executable, "-I", os.path.join(paths.APP_ROOT, "bin", "claude-pets"), "daemon"],
        env=env, cwd="/", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    deadline = time.time() + wait
    while time.time() < deadline:
        if daemon_running():
            return True
        time.sleep(0.15)
    return False


def default_target():
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or os.getcwd()


# ----------------------------------------------------------------------------
# commands
# ----------------------------------------------------------------------------

def cmd_daemon(args):
    from .daemon import main
    return main(foreground=args.foreground)


def cmd_start(_args):
    try:
        os.unlink(paths.STOPPED_FLAG)
    except OSError:
        pass
    if daemon_running():
        print("Claude Pets is already running.")
        return 0
    if spawn_daemon():
        reply = request("status") or {}
        print("Claude Pets started — %d pet(s) out." % len(reply.get("pets", [])))
        return 0
    print("Could not start the daemon; see %s" % paths.LOG_FILE, file=sys.stderr)
    return 1


def cmd_stop(_args):
    reply = request("quit", {"stopped": True})
    paths.ensure_runtime_dir()
    open(paths.STOPPED_FLAG, "w").close()
    print("Claude Pets stopped." if reply else "Claude Pets was not running.")
    print("They stay away until `claude-pets start` (or your next login).")
    return 0


def cmd_restart(args):
    request("quit", {})
    for _ in range(40):
        if not daemon_running():
            break
        time.sleep(0.1)
    return cmd_start(args)


def _bar(value, width=8):
    filled = int(round(max(0.0, min(1.0, value or 0.0)) * width))
    return "█" * filled + "·" * (width - filled)


def cmd_status(args):
    from . import hooks_install
    reply = request("status")
    if args.json:
        print(json.dumps({"daemon": reply, "hooks": hooks_install.status()}, indent=2))
        return 0
    hooks = hooks_install.status()
    installed = hooks.get("installed")
    print("Hooks:   %s" % ("installed in %s" % paths.CLAUDE_SETTINGS if installed else "NOT installed — run `claude-pets install`"))
    if reply is None:
        stopped = os.path.exists(paths.STOPPED_FLAG)
        print("Daemon:  not running%s" % (" (stopped by you; `claude-pets start` to bring the pets back)" if stopped else
                                          " (it starts with your next Claude Code session, or `claude-pets start`)"))
        return 0
    print("Daemon:  running (pid %s, up %ss)%s" % (
        reply.get("pid"), reply.get("uptime"), "" if reply.get("visible") else " — pets are hidden"))
    pets = reply.get("pets", [])
    if not pets:
        print("No Claude Code sessions are open, so no pets are out.")
        return 0
    print()
    for pet in pets:
        print("%s the %s  ·  Lv %s  ·  %s%s" % (
            pet["name"], pet["species"], pet["level"], pet["project"],
            "  (tucked away)" if pet.get("hidden") else ""))
        print("   doing:   %s" % pet.get("doing", ""))
        if "emotion" in pet:
            ctx = pet.get("context_pct")
            print("   feeling: %-12s energy %s  mood %s  focus %s  context %s" % (
                pet["emotion"], _bar(pet.get("energy")), _bar(pet.get("mood")), _bar(pet.get("focus")),
                "%d%%" % round(ctx * 100) if ctx is not None else "–"))
            print("   session: %s%s%s" % (
                pet["session_id"][:8], " · %s" % pet["session_name"] if pet.get("session_name") else "",
                "" if pet.get("has_hooks") else " · no hooks yet (restart that session for full detail)"))
    return 0


def cmd_list(args):
    from .store import Store
    profiles = Store().all()
    if args.json:
        print(json.dumps([p.to_json() for p in profiles], indent=2))
        return 0
    if not profiles:
        print("No pets yet — open a Claude Code session and one will hatch.")
        return 0
    for p in profiles:
        print("%-10s %-8s Lv %-3d %-28s %s" % (p.name, p.design.species, p.level, p.project, p.key))
    return 0


def _parse_sets(pairs):
    changes = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit("--set expects key=value, got %r" % pair)
        key, value = pair.split("=", 1)
        changes[key.strip().lower()] = value.strip()
    return changes


def cmd_design(args):
    from .store import Store, apply_changes
    changes = _parse_sets(args.set)
    if args.random:
        changes["random"] = True
    target = args.key or args.session or args.target or default_target()
    if args.options:
        from .render.creature import ACCESSORIES, ALL_SPECIES, COATS, LEGENDS, PATTERNS, SPECIES
        from .store import PERSONALITIES
        print(json.dumps({
            "note": "legends are human characters: fur = outfit, belly = skin, extra = hair, accent = "
                    "signature colour; poking one triggers its signature move instead of petting",
            "legends": list(LEGENDS),
            "species": {name: {"label": SPECIES[name]["label"], "patterns": list(SPECIES[name]["patterns"]),
                               "coats": [dict(zip(("fur", "belly", "extra"), c)) for c in COATS[name]]}
                        for name in ALL_SPECIES},
            "patterns": list(PATTERNS), "accessories": list(ACCESSORIES),
            "personalities": list(PERSONALITIES),
            "fields": ["name", "species", "coat", "fur", "belly", "accent", "extra", "eye", "cheek",
                       "pattern", "accessory", "personality"],
        }, indent=2))
        return 0
    if not changes and not args.show:
        from .studio import main as studio_main
        return studio_main(target)
    reply = request("design", {"target": target, "set": changes})
    if reply is None or (not reply.get("ok") and "no pet matches" in str(reply.get("error", ""))):
        store = Store()
        profile = store.find(target) or (store.get(target) if os.path.isdir(target) else None)
        if profile is None:
            print("No pet matches %r. Try `claude-pets list`." % target, file=sys.stderr)
            return 1
        changed, errors = apply_changes(profile, changes)
        if changed:
            store.save(profile)
        reply = {"ok": not errors or bool(changed), "changed": changed, "errors": errors,
                 "profile": profile.to_json(), "live": False}
    if args.json:
        print(json.dumps(reply, indent=2))
    else:
        prof = reply.get("profile", {})
        design = prof.get("design", {})
        print("%s the %s (%s)" % (prof.get("name"), design.get("species"), prof.get("key")))
        print("   fur %s  belly %s  accent %s%s  pattern %s  accessory %s  personality %s" % (
            design.get("fur"), design.get("belly"), design.get("accent"),
            "  extra %s" % design["extra"] if design.get("extra") else "", design.get("pattern"),
            design.get("accessory"), prof.get("personality")))
        if reply.get("changed"):
            print("   changed: %s%s" % (", ".join(reply["changed"]),
                                         " (live on your desktop now)" if reply.get("live") else ""))
        for err in reply.get("errors") or []:
            print("   ! %s" % err, file=sys.stderr)
    return 0 if reply.get("ok") else 1


def cmd_config(args):
    if not args.key:
        print(json.dumps(config_mod.load(), indent=2))
        return 0
    if args.key not in config_mod.DEFAULTS:
        print("Unknown setting %r. Known: %s" % (args.key, ", ".join(config_mod.DEFAULTS)), file=sys.stderr)
        return 1
    if args.value is None:
        print(config_mod.load()[args.key])
        return 0
    try:
        value = config_mod.set_value(args.key, args.value)
    except ValueError as exc:
        print("Bad value: %s" % exc, file=sys.stderr)
        return 1
    request("reload")
    print("%s = %s" % (args.key, value))
    return 0


def _simple(cmd, payload, ok_text):
    reply = request(cmd, payload)
    if reply is None:
        print("Claude Pets is not running (`claude-pets start`).", file=sys.stderr)
        return 1
    if not reply.get("ok"):
        print(reply.get("error", "failed"), file=sys.stderr)
        return 1
    print(ok_text.format(**reply) if ok_text else json.dumps(reply, indent=2))
    return 0


def cmd_hide(args):
    return _simple("hide", {"minutes": args.minutes}, "Pets hidden for %g minutes. `claude-pets show` brings them back." % args.minutes)


def cmd_show(_args):
    return _simple("show", {}, "Pets are back.")


def cmd_toggle(_args):
    return _simple("toggle", {}, "")


def cmd_say(args):
    return _simple("say", {"target": args.target or default_target(), "text": " ".join(args.text)}, "{name} says it.")


def cmd_treat(args):
    return _simple("treat", {"target": args.target or default_target()}, "{name} got a treat.")


def cmd_focus(args):
    return _simple("focus", {"target": args.target or default_target()}, "Asked {name}'s terminal to come forward (via {how}).")


def cmd_poke(args):
    return _simple("poke", {"target": args.target or default_target()}, "Poked {name}.")


def cmd_demo(args):
    if not daemon_running() and not args.stop:
        try:
            os.unlink(paths.STOPPED_FLAG)
        except OSError:
            pass
        if not spawn_daemon():
            print("Could not start the daemon; see %s" % paths.LOG_FILE, file=sys.stderr)
            return 1
    if args.stop:
        return _simple("demo", {"stop": True}, "Demo sessions ended.")
    legends = str(args.count).lower() == "legends"
    try:
        count = 5 if legends else int(args.count)
    except ValueError:
        print("demo takes a number of sessions or the word 'legends'", file=sys.stderr)
        return 1
    seconds = float(getattr(args, "seconds", 0) or 0)
    tail = " It ends by itself in %d s." % seconds if seconds else " `claude-pets demo --stop` ends it."
    return _simple("demo", {"count": count, "cast": "legends" if legends else "", "seconds": seconds},
                   ("The legends are in the building." if legends else
                    "Demo running with %d pretend session(s)." % count) + tail)


def cmd_snapshot(args):
    return _simple("snapshot", {"dir": os.path.abspath(args.dir), "background": args.background}, "")


def cmd_gallery(args):
    from .render import snapshot
    out = os.path.abspath(args.dir)
    os.makedirs(out, exist_ok=True)
    for name in ("species", "coats", "faces", "poses", "accessories"):
        print(getattr(snapshot, name + "_sheet")(os.path.join(out, name + ".png")))
    return 0


# -- install / uninstall -------------------------------------------------------

def _link(target, link):
    if os.path.islink(link):
        if os.path.realpath(link) == os.path.realpath(target):
            return "ok"
        os.unlink(link)
    elif os.path.exists(link):
        return "skipped (something else is already there)"
    os.makedirs(os.path.dirname(link), exist_ok=True)
    os.symlink(target, link)
    return "linked"


def install_skills():
    results = {}
    for name in SKILLS:
        src_dir = os.path.join(paths.APP_ROOT, "skills", name)
        dst_dir = os.path.join(paths.CLAUDE_SKILLS_DIR, name)
        if not os.path.isdir(src_dir):
            continue
        if os.path.exists(dst_dir) and not os.path.exists(os.path.join(dst_dir, SKILL_MARKER)):
            results[name] = "skipped (a different skill named %r already exists)" % name
            continue
        os.makedirs(dst_dir, exist_ok=True)
        for entry in os.listdir(src_dir):
            shutil.copy2(os.path.join(src_dir, entry), os.path.join(dst_dir, entry))
        with open(os.path.join(dst_dir, SKILL_MARKER), "w", encoding="utf-8") as fh:
            fh.write("Installed by claude-pets %s from %s\n" % (__version__, paths.APP_ROOT))
        results[name] = "installed"
    return results


def uninstall_skills():
    removed = []
    for name in SKILLS:
        dst_dir = os.path.join(paths.CLAUDE_SKILLS_DIR, name)
        if os.path.exists(os.path.join(dst_dir, SKILL_MARKER)):
            shutil.rmtree(dst_dir)
            removed.append(name)
    return removed


DESKTOP_FILE = os.path.join(os.path.expanduser("~"), ".local", "share", "applications", "claude-pets-studio.desktop")


def install_launcher():
    """App-grid entry for the design studio."""
    os.makedirs(os.path.dirname(DESKTOP_FILE), exist_ok=True)
    with open(DESKTOP_FILE, "w", encoding="utf-8") as fh:
        fh.write("[Desktop Entry]\nType=Application\nName=Claude Pets Studio\n"
                 "Comment=Design the desktop pets of your Claude Code sessions\n"
                 "Exec=%s design\nIcon=%s\nTerminal=false\nCategories=Utility;\n"
                 "StartupWMClass=claude-pets\nX-Claude-Pets=1\n" % (
                     os.path.join(paths.INSTALL_LINK, "bin", "claude-pets"),
                     os.path.join(paths.INSTALL_LINK, "assets", "icon.svg")))
    return DESKTOP_FILE


def cmd_install(args):
    from . import hooks_install
    paths.ensure_dirs()
    print("App link:  %s -> %s  [%s]" % (paths.INSTALL_LINK, paths.APP_ROOT, _link(paths.APP_ROOT, paths.INSTALL_LINK)))
    bin_link = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude-pets")
    print("Command:   %s  [%s]" % (bin_link, _link(os.path.join(paths.APP_ROOT, "bin", "claude-pets"), bin_link)))
    result = hooks_install.install()
    if result.get("changed"):
        print("Hooks:     added to %s (backup: %s)" % (paths.CLAUDE_SETTINGS, result.get("backup_path") or "none needed"))
    else:
        print("Hooks:     already installed in %s" % paths.CLAUDE_SETTINGS)
    for name, state in install_skills().items():
        print("Skill:     /%s  [%s]" % (name, state))
    print("Launcher:  %s" % install_launcher())
    if not args.no_start:
        cmd_start(args)
    print()
    print("Every Claude Code session you open from now on brings its pet along.")
    print("Sessions that were already open show up too; they get richer detail once restarted.")
    return 0


def cmd_uninstall(args):
    from . import hooks_install
    request("quit", {"stopped": True})
    result = hooks_install.uninstall()
    print("Hooks:     %s" % ("removed from %s" % paths.CLAUDE_SETTINGS if result.get("changed") else "none were installed"))
    for name in uninstall_skills():
        print("Skill:     /%s removed" % name)
    if os.path.exists(DESKTOP_FILE):
        os.unlink(DESKTOP_FILE)
        print("Removed:   %s" % DESKTOP_FILE)
    for link in (paths.INSTALL_LINK, os.path.join(os.path.expanduser("~"), ".local", "bin", "claude-pets")):
        if os.path.islink(link) and os.path.realpath(link).startswith(os.path.realpath(paths.APP_ROOT)):
            os.unlink(link)
            print("Removed:   %s" % link)
    if args.purge:
        for path in (paths.DATA_DIR, paths.CONFIG_DIR, paths.STATE_DIR):
            shutil.rmtree(path, ignore_errors=True)
            print("Removed:   %s" % path)
    else:
        print("Your pets' profiles are kept in %s (use --purge to delete them too)." % paths.PETS_DIR)
    return 0


def cmd_doctor(_args):
    from . import hooks_install
    ok = True

    def check(label, passed, detail=""):
        nonlocal ok
        ok = ok and passed
        print("%s %-26s %s" % ("✓" if passed else "✗", label, detail))

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
        import cairo  # noqa: F401
        check("GTK 3 + Cairo bindings", True, "PyGObject %s" % gi.__version__)
    except Exception as exc:  # pragma: no cover - environment dependent
        check("GTK 3 + Cairo bindings", False, str(exc))
    display = os.environ.get("DISPLAY")
    check("X display (XWayland)", bool(display), display or "DISPLAY is not set")
    check("Session type", True, "%s / %s" % (os.environ.get("XDG_SESSION_TYPE", "?"), os.environ.get("XDG_CURRENT_DESKTOP", "?")))
    hooks = hooks_install.status()
    check("Claude Code hooks", bool(hooks.get("installed")), "%d event(s) registered" % len(hooks.get("events", [])))
    check("Hook entry point", os.access(os.path.join(paths.INSTALL_LINK, "bin", "claude-pets-hook"), os.X_OK), paths.INSTALL_LINK)
    reply = request("status", timeout=1.0)
    stopped = os.path.exists(paths.STOPPED_FLAG)
    check("Daemon", reply is not None or stopped,
          "pid %s, %d pet(s)" % (reply.get("pid"), len(reply.get("pets", []))) if reply else
          ("stopped by you" if stopped else "not running — `claude-pets start`"))
    sessions = [n for n in os.listdir(paths.CLAUDE_SESSIONS_DIR) if n.endswith(".json")] if os.path.isdir(paths.CLAUDE_SESSIONS_DIR) else []
    check("Claude session registry", os.path.isdir(paths.CLAUDE_SESSIONS_DIR), "%d session file(s)" % len(sessions))
    print("\nLog: %s" % paths.LOG_FILE)
    return 0 if ok else 1


# ----------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="claude-pets", description="Desktop pet friends for your Claude Code sessions.")
    parser.add_argument("--version", action="version", version="claude-pets %s" % __version__)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("status", help="what every pet is doing and feeling")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)
    sub.add_parser("start", help="bring the pets out").set_defaults(fn=cmd_start)
    sub.add_parser("stop", help="send the pets home until you start them again").set_defaults(fn=cmd_stop)
    sub.add_parser("restart", help="restart the daemon").set_defaults(fn=cmd_restart)
    p = sub.add_parser("hide", help="hide all pets for a while")
    p.add_argument("minutes", nargs="?", type=float, default=60.0)
    p.set_defaults(fn=cmd_hide)
    sub.add_parser("show", help="show hidden pets again").set_defaults(fn=cmd_show)
    sub.add_parser("toggle", help="hide or show all pets").set_defaults(fn=cmd_toggle)

    p = sub.add_parser("design", help="open the design studio, or restyle a pet with --set")
    p.add_argument("target", nargs="?", help="pet name, project, directory or session id (default: this session's pet)")
    p.add_argument("--set", action="append", metavar="FIELD=VALUE", help="e.g. species=dragon fur=#8B5CF6 name=Ember")
    p.add_argument("--random", action="store_true", help="roll a random look")
    p.add_argument("--show", action="store_true", help="print the current design")
    p.add_argument("--options", action="store_true", help="print every species, coat, pattern and accessory")
    p.add_argument("--key", help=argparse.SUPPRESS)
    p.add_argument("--session", help=argparse.SUPPRESS)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_design)

    p = sub.add_parser("list", help="every pet you have met")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("config", help="show or change settings")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)
    p = sub.add_parser("say", help="make a pet say something")
    p.add_argument("text", nargs="+")
    p.add_argument("--target")
    p.set_defaults(fn=cmd_say)
    p = sub.add_parser("treat", help="give a pet a treat")
    p.add_argument("target", nargs="?")
    p.set_defaults(fn=cmd_treat)
    p = sub.add_parser("focus", help="bring a pet's terminal forward")
    p.add_argument("target", nargs="?")
    p.set_defaults(fn=cmd_focus)
    p = sub.add_parser("demo", help="pretend sessions, to watch the pets work (`demo legends` for the legends)")
    p.add_argument("count", nargs="?", default="3", help="how many sessions, or 'legends'")
    p.add_argument("--for", dest="seconds", type=float, default=0, help="end by itself after this many seconds")
    p.add_argument("--stop", action="store_true")
    p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("poke", help="poke a pet: animals get petted, legends do their signature move")
    p.add_argument("target", nargs="?")
    p.set_defaults(fn=cmd_poke)
    p = sub.add_parser("gallery", help="render every species, face and pose to PNG sheets")
    p.add_argument("dir", nargs="?", default="claude-pets-gallery")
    p.set_defaults(fn=cmd_gallery)
    p = sub.add_parser("snapshot", help=argparse.SUPPRESS)
    p.add_argument("dir")
    p.add_argument("--background")
    p.set_defaults(fn=cmd_snapshot)

    p = sub.add_parser("install", help="hook into Claude Code and start")
    p.add_argument("--no-start", action="store_true")
    p.set_defaults(fn=cmd_install)
    p = sub.add_parser("uninstall", help="remove the hooks and skills")
    p.add_argument("--purge", action="store_true", help="also delete pet profiles and settings")
    p.set_defaults(fn=cmd_uninstall)
    sub.add_parser("doctor", help="check that everything is wired up").set_defaults(fn=cmd_doctor)
    p = sub.add_parser("daemon", help=argparse.SUPPRESS)
    p.add_argument("--foreground", action="store_true")
    p.set_defaults(fn=cmd_daemon)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        args = parser.parse_args(["status"])
    try:
        return args.fn(args) or 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

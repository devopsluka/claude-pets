"""Register / remove the Claude Pets hooks in a Claude Code ``settings.json``.

The merge is surgical: only hook entries whose command mentions
``claude-pets-hook`` are ever added, replaced or removed; every other key and
hook in the file — and its key order and indentation — is left alone.  A
timestamped backup is written next to the file whenever it changes.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import tempfile
import time

from . import paths

MARKER = "claude-pets-hook"
TIMEOUT = 5

#: (event, async?) — tool-level events run async so they never slow a tool
#: call down; the few turn-boundary events run sync (≈30 ms) so that they
#: reach the daemon in order.
EVENTS = (
    ("SessionStart", False),
    ("SessionEnd", False),
    ("UserPromptSubmit", False),
    ("Stop", False),
    ("PreToolUse", True),
    ("PostToolUse", True),
    ("PostToolUseFailure", True),
    ("PostToolBatch", True),
    ("PermissionRequest", True),
    ("PermissionDenied", True),
    ("Notification", True),
    ("StopFailure", True),
    ("SubagentStart", True),
    ("SubagentStop", True),
    ("PreCompact", True),
    ("PostCompact", True),
    ("TaskCompleted", True),
    ("Elicitation", True),
    ("ElicitationResult", True),
)
EVENT_NAMES = tuple(name for name, _ in EVENTS)

_SAFE_REL = re.compile(r"^[A-Za-z0-9_./+@:-]+$")


def hook_command(install_link: str | None = None) -> str:
    """Shell command for the hooks; a no-op if Claude Pets is not installed."""
    target = os.path.join(install_link or paths.INSTALL_LINK, "bin", MARKER)
    home = os.path.expanduser("~")
    if target.startswith(home + os.sep) and _SAFE_REL.match(target[len(home):]):
        shown = '"$HOME%s"' % target[len(home):]
    else:
        shown = shlex.quote(target)
    return "[ -x %s ] && %s || true" % (shown, shown)


def _desired_hook(command: str, is_async: bool) -> dict:
    hook = {"type": "command", "command": command, "timeout": TIMEOUT}
    if is_async:
        hook["async"] = True
    return hook


def build_hooks_block(command: str | None = None) -> dict:
    """The complete ``hooks`` mapping for a settings file that has no other hooks."""
    command = command or hook_command()
    return {name: [{"hooks": [_desired_hook(command, is_async)]}] for name, is_async in EVENTS}


def _is_ours(hook) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command", ""))


def _our_hooks(groups) -> list:
    found = []
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, dict) and isinstance(group.get("hooks"), list):
                found.extend(h for h in group["hooks"] if _is_ours(h))
    return found


def _strip_ours(groups) -> list:
    """``groups`` without our hook entries (groups we emptied are dropped)."""
    kept = []
    for group in groups:
        if isinstance(group, dict) and isinstance(group.get("hooks"), list):
            ours = [h for h in group["hooks"] if _is_ours(h)]
            if ours:
                rest = [h for h in group["hooks"] if not _is_ours(h)]
                if not rest:
                    continue
                group = dict(group)
                group["hooks"] = rest
        kept.append(group)
    return kept


def _load(settings_path: str):
    """Returns ``(settings, original_text)``; a missing file is an empty mapping."""
    try:
        with open(settings_path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return {}, None
    if not text.strip():
        return {}, text
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("%s does not contain a JSON object" % settings_path)
    if "hooks" in data and not isinstance(data["hooks"], dict):
        raise ValueError('"hooks" in %s is not an object' % settings_path)
    return data, text


def _indent_of(text):
    if text:
        match = re.search(r"^([ \t]+)\S", text, re.M)
        if match:
            lead = match.group(1)
            return lead if "\t" in lead else len(lead)
    return 2


def _write(settings_path: str, data: dict, original, backup: bool):
    backup_path = None
    directory = os.path.dirname(settings_path) or "."
    os.makedirs(directory, exist_ok=True)
    mode = 0o644
    if original is not None:
        mode = os.stat(settings_path).st_mode & 0o777
        if backup:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = "%s.bak-claude-pets-%s" % (settings_path, stamp)
            counter = 1
            while os.path.exists(backup_path):
                counter += 1
                backup_path = "%s.bak-claude-pets-%s-%d" % (settings_path, stamp, counter)
            shutil.copy2(settings_path, backup_path)
    text = json.dumps(data, indent=_indent_of(original), ensure_ascii=False)
    if original is None or original.endswith("\n") or not original.strip():
        text += "\n"
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, settings_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return backup_path


def install(settings_path: str | None = None, backup: bool = True, command: str | None = None) -> dict:
    """Idempotently register the hooks. Returns ``changed``, ``backup_path``, ``events``."""
    settings_path = os.path.realpath(settings_path or paths.CLAUDE_SETTINGS)
    command = command or hook_command()
    data, original = _load(settings_path)
    hooks = data.get("hooks")
    changed = False
    if hooks is None:
        hooks = {}
    for name, is_async in EVENTS:
        desired = _desired_hook(command, is_async)
        groups = hooks.get(name)
        if groups is None:
            groups = []
        if not isinstance(groups, list):
            raise ValueError('"hooks.%s" in %s is not a list' % (name, settings_path))
        if _our_hooks(groups) == [desired]:
            continue
        hooks[name] = _strip_ours(groups) + [{"hooks": [desired]}]
        changed = True
    for name in list(hooks):  # entries from an older version of ours
        if name not in EVENT_NAMES and _our_hooks(hooks[name]):
            rest = _strip_ours(hooks[name])
            if rest:
                hooks[name] = rest
            else:
                del hooks[name]
            changed = True
    backup_path = None
    if changed:
        data["hooks"] = hooks
        backup_path = _write(settings_path, data, original, backup)
    return {
        "changed": changed,
        "backup_path": backup_path,
        "events": list(EVENT_NAMES),
        "settings_path": settings_path,
        "command": command,
    }


def uninstall(settings_path: str | None = None, backup: bool = True) -> dict:
    """Remove only our hook entries; prune containers that become empty."""
    settings_path = os.path.realpath(settings_path or paths.CLAUDE_SETTINGS)
    data, original = _load(settings_path)
    hooks = data.get("hooks")
    removed = []
    if isinstance(hooks, dict):
        for name in list(hooks):
            if not _our_hooks(hooks[name]):
                continue
            removed.append(name)
            rest = _strip_ours(hooks[name])
            if rest:
                hooks[name] = rest
            else:
                del hooks[name]
        if removed and not hooks:
            del data["hooks"]
    backup_path = None
    if removed:
        backup_path = _write(settings_path, data, original, backup)
    return {
        "changed": bool(removed),
        "backup_path": backup_path,
        "events": removed,
        "settings_path": settings_path,
    }


def status(settings_path: str | None = None, command: str | None = None) -> dict:
    """What is registered right now (never writes)."""
    settings_path = os.path.realpath(settings_path or paths.CLAUDE_SETTINGS)
    command = command or hook_command()
    try:
        data, _ = _load(settings_path)
        error = None
    except (OSError, ValueError) as exc:
        data, error = {}, str(exc)
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    present, missing, outdated = [], [], []
    for name, is_async in EVENTS:
        ours = _our_hooks(hooks.get(name))
        if not ours:
            missing.append(name)
        elif ours == [_desired_hook(command, is_async)]:
            present.append(name)
        else:
            outdated.append(name)
    return {
        "installed": not missing and not outdated and error is None,
        "events": present,
        "missing": missing,
        "outdated": outdated,
        "settings_path": settings_path,
        "command": command,
        "error": error,
    }

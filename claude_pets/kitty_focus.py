"""kitty kitten used by Claude Pets: focus the matched kitty window (its tab,
and its OS window) with the activation token passed as the first argument.

Run over kitty's remote control, inside the kitty process::

    kitty @ --to <socket> kitten --match id:<window> /path/to/kitty_focus.py <token>

It lives in the same package but is only ever imported by kitty.
"""

from kittens.tui.handler import result_handler


def main(args):
    return ""


@result_handler(no_ui=True)
def handle_result(args, answer, target_window_id, boss):
    token = args[1] if len(args) > 1 else ""
    window = boss.window_id_map.get(target_window_id)
    if window is None:
        return "no-window"
    if token == "--probe":                       # plumbing check: change nothing
        return "ok"
    os_window = boss.set_active_window(window, switch_os_window_if_needed=True, activation_token=token)
    return "ok" if os_window else "not-found"

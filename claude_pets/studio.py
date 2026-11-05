"""Pet Design Studio — pick a species, coat, markings, accessory, colours,
name and personality for any of your pets, with a live animated preview.

Runs as its own little app (``claude-pets design``); saving talks to the
daemon so the pet on your desktop changes on the spot.
"""

import copy
import os
import random
import sys
import time

from . import config as config_mod
from . import paths


def main(target=None):
    import cairo
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

    from .brain import Pet, World
    from .cli import request
    from .model import Activity as A
    from .model import Emotion as E
    from .model import SessionState
    from .model import Signal as S
    from .render import scene
    from .render.color import rgb, src, to_hex
    from .render.creature import ACCENTS, ACCESSORIES, ALL_SPECIES, COATS, SPECIES
    from .render.tokens import Theme, gtk_css
    from .store import PERSONALITIES, Store, apply_changes

    GLib.set_prgname("claude-pets")
    GLib.set_application_name("Claude Pets Studio")
    ready = Gtk.init_check(sys.argv)
    if isinstance(ready, tuple):
        ready = ready[0]
    if not ready:
        print("No display available.", file=sys.stderr)
        return 1

    cfg = config_mod.load()
    scheme = cfg.get("theme", "auto")
    if scheme == "auto":
        scheme = "dark"
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source is not None and source.lookup("org.gnome.desktop.interface", True) is not None:
                if Gio.Settings.new("org.gnome.desktop.interface").get_string("color-scheme") != "prefer-dark":
                    scheme = "light"
        except Exception:
            pass
    theme = Theme(scheme)
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", scheme == "dark")
    provider = Gtk.CssProvider()
    provider.load_from_data(gtk_css(scheme).encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    store = Store()
    status = request("status", timeout=1.0) or {}
    live = {p["key"]: p for p in status.get("pets", [])}
    profiles = {p.key: p for p in store.all()}
    for key, info in live.items():                      # live pets of headless sessions are not on disk
        if key not in profiles:
            reply = request("design", {"target": key, "set": {}}) or {}
            data = reply.get("profile")
            if data:
                prof = store.fresh(data.get("cwd", ""), int(data.get("index", 1)))
                prof.key, prof.name = key, data.get("name", prof.name)
                apply_changes(prof, {k: v for k, v in (data.get("design") or {}).items() if k != "extra" or v})
                prof.persistent = False
                profiles[key] = prof

    def resolve(query):
        if not query:
            return None
        for key, info in live.items():
            if query in (key, info.get("session_id"), info.get("name")) or info.get("cwd") == query:
                return key
        found = store.find(query)
        return found.key if found else None

    current_key = resolve(target) or next(iter(live), None) or next(iter(profiles), None)
    if current_key is None:
        prof = store.get(os.getcwd() if not target or not os.path.isdir(target) else target)
        profiles[prof.key] = prof
        current_key = prof.key

    state = {"key": current_key, "work": None, "saved": None, "building": False, "pet": None,
             "last": time.monotonic(), "mood": "idle"}

    # ------------------------------------------------------------------ preview
    preview_cfg = dict(cfg, wander=False, social=False, bubbles="all", gravity=True)
    world = World(0, 0, 420, 400, 2.3, preview_cfg, random.Random(7))

    def fake(activity, emotion=E.CONTENT, **kw):
        now = time.time()
        s = SessionState(session_id="studio", cwd="/", project="studio", activity=activity, activity_since=now,
                         started_at=now - 600, emotion=emotion, mood=0.7, energy=0.8)
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def set_mood(name):
        pet = state["pet"]
        if pet is None:
            return
        state["mood"] = name
        now = time.time()
        pet.asleep = False
        pet.bubble = None
        if name == "idle":
            pet.on_session(fake(A.IDLE, E.HAPPY), [])
        elif name == "thinking":
            pet.on_session(fake(A.THINKING), [])
        elif name == "coding":
            pet.on_session(fake(A.WRITING, E.FOCUSED, detail="Editing main.py"),
                           [(S.TOOL_START, {"detail": "Editing main.py"})])
        elif name == "running":
            pet.on_session(fake(A.TESTING, E.CONTENT, detail="Running tests"),
                           [(S.TOOL_START, {"detail": "Running tests"})])
        elif name == "needs you":
            pet.on_session(fake(A.WAITING, needs_user=True, needs_reason="permission",
                                needs_detail="Bash: make deploy", needs_since=now),
                           [(S.NEEDS_USER, {"reason": "permission"})])
        elif name == "done":
            pet.on_session(fake(A.DONE, E.JOYFUL, last_turn_duration=134),
                           [(S.TURN_DONE, {"duration": 134, "tools": 12, "errors": 0})])
        elif name == "oops":
            pet.on_session(fake(A.THINKING, E.FRUSTRATED, error_streak=3),
                           [(S.TOOL_ERROR, {"tool": "Bash", "streak": 3})])
        elif name == "sleepy":
            sleepy = fake(A.IDLE, E.SLEEPY)
            sleepy.activity_since = now - 1200
            pet.on_session(sleepy, [])
            pet.idle, pet.idle_t, pet.idle_dur = "yawn", 0.0, 1.8
        elif name == "loved":
            pet.on_session(fake(A.IDLE, E.JOYFUL), [(S.PROMPT, {"sentiment": "praise"})])
        elif name == "poke":
            pet.on_session(fake(A.IDLE, E.HAPPY), [])
            pet.idle, pet.idle_t, pet.idle_dur = "stand", 0.0, 8.0
            pet.petted(now)

    def rebuild_pet():
        prof = state["work"]
        world.pets[:] = []
        pet = Pet("studio", prof, world, time.time(), entrance="pop")
        pet.x = pet.home_x = (world.left + world.right) / 2.0
        world.pets.append(pet)
        state["pet"] = pet
        set_mood(state["mood"])

    area = Gtk.DrawingArea()
    area.set_size_request(420, 400)

    def on_draw(_widget, cr):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        src(cr, theme.color("surface"))
        cr.paint()
        glow = cairo.RadialGradient(w / 2, h - 60, 10, w / 2, h - 60, w * 0.55)
        accent = rgb(state["work"].design.accent) if state["work"] else theme.color("accent")
        glow.add_color_stop_rgba(0, accent[0], accent[1], accent[2], 0.20)
        glow.add_color_stop_rgba(1, accent[0], accent[1], accent[2], 0.0)
        cr.set_source(glow)
        cr.paint()
        cr.save()
        cr.translate(w / 2, h - 44)
        cr.scale(1, 0.22)
        cr.arc(0, 0, w * 0.34, 0, 6.2832)
        cr.restore()
        src(cr, theme.color("surface-sunken"), 0.9)
        cr.fill()
        pet = state["pet"]
        if pet is not None:
            scene.draw_scene(cr, pet, w, h, theme, preview_cfg, time.time(), clear=False)
        return True

    area.connect("draw", on_draw)

    def on_tick():
        mono = time.monotonic()
        dt = min(0.1, mono - state["last"])
        state["last"] = mono
        pet = state["pet"]
        if pet is not None:
            w, h = area.get_allocated_width(), area.get_allocated_height()
            world.right, world.floor = float(max(w, 200)), float(max(h, 200))
            pet.x = pet.home_x = world.right / 2.0
            now = time.time()
            world.now = now
            pet.update(dt, now)
            area.queue_draw()
        return True

    # ------------------------------------------------------------------ controls
    def section(text):
        label = Gtk.Label(label=text.upper(), xalign=0)
        label.get_style_context().add_class("cp-section")
        return label

    def flow():
        box = Gtk.FlowBox()
        box.set_selection_mode(Gtk.SelectionMode.NONE)
        box.set_max_children_per_line(12)
        box.set_row_spacing(6)
        box.set_column_spacing(6)
        box.set_homogeneous(False)
        return box

    groups = {}

    def chips(field, options, labels=None):
        box = flow()
        first = None
        buttons = {}
        for option in options:
            text = (labels or {}).get(option, option.replace("_", " ").title())
            button = Gtk.RadioButton.new_with_label_from_widget(first, text)
            first = first or button
            button.set_mode(False)
            button.get_style_context().add_class("cp-chip")
            button.connect("toggled", lambda b, f=field, o=option: b.get_active() and change({f: o}))
            box.add(button)
            buttons[option] = button
        groups[field] = buttons
        return box

    swatch_providers = []

    def swatch(color, tooltip, callback, group):
        button = Gtk.RadioButton.new_from_widget(group)
        button.set_mode(False)
        button.set_tooltip_text(tooltip)
        ctx = button.get_style_context()
        ctx.add_class("cp-swatch")
        css = Gtk.CssProvider()
        css.load_from_data((".cp-swatch { background-color: %s; }" % color).encode("utf-8"))
        ctx.add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        swatch_providers.append(css)
        button.connect("toggled", lambda b: b.get_active() and callback())
        button.set_size_request(30, 30)
        button.set_halign(Gtk.Align.START)
        button.set_valign(Gtk.Align.CENTER)
        return button

    coat_box = flow()
    accent_box = flow()
    pattern_holder = Gtk.Box()
    color_buttons = {}
    captions = {}
    ANIMAL_CAPTIONS = {"fur": "Fur", "belly": "Belly", "accent": "Accent", "extra": "Detail"}
    LEGEND_CAPTIONS = {"fur": "Outfit", "belly": "Skin", "accent": "Signature", "extra": "Hair"}

    def rebuild_species_dependent():
        """Coats and patterns depend on the species."""
        prof = state["work"]
        design = prof.design
        for child in coat_box.get_children():
            coat_box.remove(child)
        group = None
        hidden = Gtk.RadioButton.new_from_widget(None)       # "custom" (nothing highlighted)
        group = hidden
        active = None
        for i, (fur, belly, extra) in enumerate(COATS[design.species]):
            button = swatch(fur, "%s / %s" % (fur, belly), lambda i=i: change({"coat": i}), group)
            coat_box.add(button)
            if (fur, belly) == (design.fur, design.belly):
                active = button
        state["building"] = True
        (active or hidden).set_active(True)
        state["building"] = False
        coat_box.show_all()
        for child in pattern_holder.get_children():
            pattern_holder.remove(child)
        pats = chips("pattern", SPECIES[design.species]["patterns"])
        pattern_holder.pack_start(pats, True, True, 0)
        state["building"] = True
        if design.pattern in groups["pattern"]:
            groups["pattern"][design.pattern].set_active(True)
        state["building"] = False
        pattern_holder.show_all()

    def sync_controls():
        prof = state["work"]
        design = prof.design
        state["building"] = True
        name_entry.set_text(prof.name)
        groups["species"][design.species].set_active(True)
        groups["accessory"][design.accessory].set_active(True)
        groups["personality"][prof.personality].set_active(True)
        for field, button in color_buttons.items():
            value = getattr(design, field) or to_hex(rgb(design.fur))
            rgba = Gdk.RGBA()
            rgba.parse(value)
            button.set_rgba(rgba)
        state["building"] = False
        rebuild_species_dependent()
        names = LEGEND_CAPTIONS if SPECIES[design.species].get("human") else ANIMAL_CAPTIONS
        for field, text in names.items():
            if field in captions:
                captions[field].set_text(text)
        stats = prof.stats
        stat_label.set_text("Level %d · %d XP · %d sessions · %d turns · petted %d times" % (
            prof.level, prof.xp, int(stats.get("sessions", 0)), int(stats.get("turns", 0)),
            int(stats.get("pets", 0))))
        title.set_text(prof.name)
        subtitle.set_text("%s · %s%s" % (SPECIES[design.species]["label"], prof.project,
                                          " · on your desktop now" if prof.key in live else ""))

    def change(changes):
        if state["building"]:
            return
        prof = state["work"]
        species_before = prof.design.species
        _changed, errors = apply_changes(prof, changes)
        if errors:
            hint.set_text(errors[0])
        else:
            hint.set_text("Unsaved changes" if dirty() else "")
        if prof.design.species != species_before or "random" in changes or "coat" in changes:
            sync_controls()
            if state["pet"] is not None:
                set_mood(state["mood"])
        elif any(k in changes for k in ("fur", "belly")):
            rebuild_species_dependent()
        title.set_text(prof.name)
        pet = state["pet"]
        if pet is not None:
            pet._rim = None
            if "random" in changes or "species" in changes:
                pet.fx.sparkles(8, 0, -44, 40)
        save_button.set_sensitive(dirty())

    def dirty():
        return state["saved"] is None or state["work"].to_json() != state["saved"]

    def load(key):
        prof = profiles[key]
        state["key"] = key
        work = copy.deepcopy(prof)
        work.home = -1.0
        state["work"] = work
        state["saved"] = work.to_json()
        sync_controls()
        rebuild_pet()
        hint.set_text("")
        save_button.set_sensitive(False)

    def save(*_args):
        work = state["work"]
        original = profiles[state["key"]]
        design = work.design
        changes = {"name": work.name, "personality": work.personality, "species": design.species,
                   "fur": design.fur, "belly": design.belly, "accent": design.accent, "extra": design.extra,
                   "eye": design.eye, "cheek": design.cheek, "pattern": design.pattern,
                   "accessory": design.accessory}
        reply = request("design", {"target": original.key, "set": changes})
        if reply is None or not reply.get("ok"):
            apply_changes(original, changes)
            original.persistent = True
            store.save(original)
            hint.set_text("Saved. %s will wear it next time it visits." % work.name)
        else:
            apply_changes(original, changes)
            hint.set_text("Saved — %s." % ("look at your desktop" if reply.get("live") else "ready for its next visit"))
        state["saved"] = work.to_json()
        save_button.set_sensitive(False)
        pet = state["pet"]
        if pet is not None:
            pet.start_react("cheer", 1.2)
            pet.fx.hearts(3)

    # ------------------------------------------------------------------ layout
    window = Gtk.Window(title="Claude Pets Studio")
    window.set_default_size(980, 640)
    window.get_style_context().add_class("cp-window")
    window.set_wmclass("claude-pets", "claude-pets")
    icon = os.path.join(paths.APP_ROOT, "assets", "icon.svg")
    if os.path.exists(icon):
        try:
            window.set_icon(GdkPixbuf.Pixbuf.new_from_file_at_size(icon, 256, 256))
        except GLib.Error:
            pass

    root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    root.set_border_width(18)
    window.add(root)

    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    root.pack_start(left, False, False, 0)
    title = Gtk.Label(xalign=0)
    title.get_style_context().add_class("cp-title")
    subtitle = Gtk.Label(xalign=0)
    subtitle.get_style_context().add_class("cp-subtitle")
    left.pack_start(title, False, False, 0)
    left.pack_start(subtitle, False, False, 0)
    stage = Gtk.Frame()
    stage.set_shadow_type(Gtk.ShadowType.NONE)
    stage.get_style_context().add_class("cp-stage")
    stage.add(area)
    left.pack_start(stage, True, True, 0)
    moods = flow()
    mood_group = None
    for name in ("idle", "thinking", "coding", "running", "needs you", "done", "oops", "sleepy", "loved", "poke"):
        button = Gtk.RadioButton.new_with_label_from_widget(mood_group, name.title())
        mood_group = mood_group or button
        button.set_mode(False)
        button.get_style_context().add_class("cp-chip")
        button.connect("toggled", lambda b, n=name: b.get_active() and set_mood(n))
        moods.add(button)
    left.pack_start(section("See how it feels when…"), False, False, 0)
    left.pack_start(moods, False, False, 0)
    stat_label = Gtk.Label(xalign=0)
    stat_label.get_style_context().add_class("cp-stat")
    left.pack_start(stat_label, False, False, 0)

    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    panel.get_style_context().add_class("cp-panel")
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.add(panel)
    root.pack_start(scroller, True, True, 0)

    top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    picker = Gtk.ComboBoxText()
    ordered = sorted(profiles.values(), key=lambda p: (p.key not in live, p.name.lower()))
    for prof in ordered:
        picker.append(prof.key, "%s%s  —  %s" % ("● " if prof.key in live else "", prof.name, prof.project))
    picker.set_active_id(current_key)
    picker.connect("changed", lambda c: c.get_active_id() and c.get_active_id() != state["key"]
                   and load(c.get_active_id()))
    top.pack_start(picker, True, True, 0)
    dice = Gtk.Button(label="Surprise me")
    dice.get_style_context().add_class("cp-ghost")
    dice.connect("clicked", lambda *_a: change({"random": True}))
    top.pack_start(dice, False, False, 0)
    panel.pack_start(top, False, False, 0)

    panel.pack_start(section("Name"), False, False, 0)
    name_entry = Gtk.Entry()
    name_entry.set_max_length(24)
    name_entry.get_style_context().add_class("cp-entry")
    name_entry.connect("changed", lambda e: e.get_text().strip() and change({"name": e.get_text().strip()}))
    panel.pack_start(name_entry, False, False, 0)

    panel.pack_start(section("Who"), False, False, 0)
    panel.pack_start(chips("species", ALL_SPECIES, {k: SPECIES[k]["label"] for k in ALL_SPECIES}), False, False, 0)
    panel.pack_start(section("Coat"), False, False, 0)
    panel.pack_start(coat_box, False, False, 0)
    panel.pack_start(section("Markings"), False, False, 0)
    panel.pack_start(pattern_holder, False, False, 0)
    panel.pack_start(section("Accessory"), False, False, 0)
    panel.pack_start(chips("accessory", ACCESSORIES), False, False, 0)

    panel.pack_start(section("Accent colour"), False, False, 0)
    accent_group = Gtk.RadioButton.new_from_widget(None)
    for color in ACCENTS:
        accent_box.add(swatch(color, color, lambda c=color: change({"accent": c}), accent_group))
    panel.pack_start(accent_box, False, False, 0)

    panel.pack_start(section("Custom colours"), False, False, 0)
    custom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    for field, label in (("fur", "Fur"), ("belly", "Belly"), ("accent", "Accent"), ("extra", "Detail"),
                         ("eye", "Eyes"), ("cheek", "Cheeks")):
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        button = Gtk.ColorButton()
        button.set_use_alpha(False)
        button.set_title("%s colour" % label)

        def picked(b, f=field):
            c = b.get_rgba()
            change({f: to_hex((c.red, c.green, c.blue))})

        button.connect("color-set", picked)
        color_buttons[field] = button
        caption = Gtk.Label(label=label)
        captions[field] = caption
        caption.get_style_context().add_class("cp-stat")
        cell.pack_start(button, False, False, 0)
        cell.pack_start(caption, False, False, 0)
        custom.pack_start(cell, False, False, 0)
    panel.pack_start(custom, False, False, 0)

    panel.pack_start(section("Personality"), False, False, 0)
    panel.pack_start(chips("personality", PERSONALITIES), False, False, 0)

    footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    footer.set_margin_top(10)
    hint = Gtk.Label(xalign=0)
    hint.get_style_context().add_class("cp-subtitle")
    hint.set_line_wrap(True)
    footer.pack_start(hint, True, True, 0)
    revert = Gtk.Button(label="Revert")
    revert.get_style_context().add_class("cp-ghost")
    revert.connect("clicked", lambda *_a: load(state["key"]))
    footer.pack_start(revert, False, False, 0)
    save_button = Gtk.Button(label="Save look")
    save_button.get_style_context().add_class("cp-primary")
    save_button.connect("clicked", save)
    footer.pack_start(save_button, False, False, 0)
    panel.pack_end(footer, False, False, 0)

    load(current_key)
    window.connect("destroy", lambda *_a: Gtk.main_quit())
    window.show_all()
    GLib.timeout_add(33, on_tick)
    auto_close = os.environ.get("CLAUDE_PETS_STUDIO_SNAPSHOT")
    if auto_close:                                   # test hook: render one frame to PNG and quit
        def snap():
            w, h = window.get_allocated_width(), window.get_allocated_height()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
            window.draw(cairo.Context(surface))
            surface.write_to_png(auto_close)
            Gtk.main_quit()
            return False
        GLib.timeout_add(1800, snap)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))

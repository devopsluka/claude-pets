"""Compose one pet's window: helpers, the pet, particles and its bubble.

Pure Cairo/Pango (no GTK) so the same code renders live windows, the design
studio preview and off-screen snapshots.
"""

import math

import cairo

from .bubble import draw_bubble, ease_out_back
from .color import rgb, src
from .creature import Pose, draw_pet, draw_shadow, draw_silhouette

WIN_W, WIN_H = 340.0, 280.0     # window size at scale 1.0
GROUND = 20.0                   # distance from the window bottom to the ground line
RIM = (rgb("#FFFAF0"), 1.7)
MINI_SLOTS = (-64.0, 64.0, -94.0, 94.0)
MINI_SCALE = 0.42


def window_size(scale):
    return int(math.ceil(WIN_W * scale)), int(math.ceil(WIN_H * scale))


def anchor(scale):
    """Where the pet's ground point sits inside its window."""
    w, h = window_size(scale)
    return w / 2.0, h - GROUND * scale


def body_rect(scale):
    """Clickable part of the window (x, y, w, h): the pet itself."""
    ax, ay = anchor(scale)
    return (int(ax - 34 * scale), int(ay - 92 * scale), int(68 * scale), int(98 * scale))


def _mini_pose(pet, i):
    t = pet.t * 1.0 + i * 1.7
    ph = t * 9.0
    return Pose(
        t=t, facing=math.sin(t * 0.9) * 0.9, hat="hardhat", eye="happy", mouth="grin",
        foot_l=(math.cos(ph) * 3.0, -max(0.0, math.sin(ph)) * 3.2),
        foot_r=(math.cos(ph + math.pi) * 3.0, -max(0.0, math.sin(ph + math.pi)) * 3.2),
        bob=-abs(math.sin(ph)) * 1.5, arm_l=0.35 + math.sin(ph) * 0.5, arm_r=0.35 - math.sin(ph) * 0.5,
        tail=math.sin(t * 5.0), tail_side=-1.0 if math.sin(t * 0.9) >= 0 else 1.0,
    )


def bubble_anchor_y(pose):
    """Height (pet units above ground) the bubble's tail points at."""
    y = 99.0 - pose.lie * 26.0 - pose.sit * 3.0
    if pose.prop == "sign":
        y += 24.0
    elif pose.hat in ("party", "nightcap"):
        y += 6.0
    return y


# The sticker border follows the pet's outline, which barely changes while a
# pet is calm, so its mask is cached and only re-rendered when the pose's
# *shape* changes. That halves the cost of an ordinary frame.
_RIM_BOX = (-92.0, -150.0, 184.0, 172.0)      # x, y, w, h in pet units
_VOLATILE_MARKS = frozenset({"dizzy", "cloud"})


def _rim_key(pose):
    return (
        round(pose.facing, 1), round(pose.tail_side, 1), round(pose.bob * 2), round(pose.lift),
        round(pose.squash, 1), round(pose.lean * 40), round(pose.sit, 1), round(pose.lie, 1),
        round(pose.head_dx), round(pose.head_dy), round(pose.head_tilt * 25), round(pose.arm_l, 1),
        round(pose.arm_r, 1), round(pose.arm_fwd_l, 1), round(pose.arm_fwd_r, 1),
        round(pose.foot_l[0]), round(pose.foot_l[1]), round(pose.foot_r[0]), round(pose.foot_r[1]),
        round(pose.tail * 3), round(pose.ear * 3), pose.prop, pose.prop_side, pose.hat,
        round(pose.belly, 1), pose.shock,
        None if pose.hand_l is None else (round(pose.hand_l[0]), round(pose.hand_l[1])),
        None if pose.hand_r is None else (round(pose.hand_r[0]), round(pose.hand_r[1])),
    )


def _draw_pet_layer(cr, pet, pose, config, res):
    """Draw the pet (with its border) at the origin; ``res`` = device px per pet unit."""
    design = pet.design
    rim = config.get("sticker_rim", True)
    if pose.cache_key is not None:
        # A looping pose (sleep): replay the finished picture.
        frames = getattr(pet, "_frames", None)
        stamp = (design.key(), round(res, 3), rim)
        if frames is None or frames[0] != stamp:
            frames = pet._frames = (stamp, {})
        store = frames[1]
        layer = store.get(pose.cache_key)
        x, y, w, h = _RIM_BOX
        if layer is None:
            if len(store) >= 48:
                store.clear()
            layer = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(math.ceil(w * res)), int(math.ceil(h * res)))
            lcr = cairo.Context(layer)
            lcr.scale(res, res)
            lcr.translate(-x, -y)
            draw_pet(lcr, design, pose, rim=RIM if rim else None)
            layer.flush()
            store[pose.cache_key] = layer
        cr.save()
        cr.translate(x, y)
        cr.scale(1.0 / res, 1.0 / res)
        cr.set_source_surface(layer, 0, 0)
        cr.paint()
        cr.restore()
        return
    if not rim:
        draw_pet(cr, design, pose)
        return
    if pose.held or (pose.marks and not _VOLATILE_MARKS.isdisjoint(pose.marks)):
        draw_pet(cr, design, pose, rim=RIM)
        return
    key = (design.key(), round(res, 3), _rim_key(pose))
    cache = getattr(pet, "_rim", None)
    if cache is None or cache[0] != key:
        x, y, w, h = _RIM_BOX
        pw, ph = int(math.ceil(w * res)), int(math.ceil(h * res))
        surface = cache[1] if cache is not None and cache[1].get_width() == pw and cache[1].get_height() == ph \
            else cairo.ImageSurface(cairo.FORMAT_A8, pw, ph)
        mcr = cairo.Context(surface)
        mcr.set_operator(cairo.OPERATOR_CLEAR)
        mcr.paint()
        mcr.set_operator(cairo.OPERATOR_OVER)
        mcr.scale(res, res)
        mcr.translate(-x, -y)
        draw_silhouette(mcr, design, pose, RIM[1])
        surface.flush()
        cache = pet._rim = (key, surface)
    draw_shadow(cr, design, pose)
    cr.save()
    cr.translate(_RIM_BOX[0], _RIM_BOX[1])
    cr.scale(1.0 / res, 1.0 / res)
    src(cr, RIM[0])
    cr.mask_surface(cache[1], 0, 0)
    cr.restore()
    draw_pet(cr, design, pose, shadow=False)


def _bubble_layer(cr, pet, bubble, theme, tip_x, tip_y, alpha, max_width, width, factor):
    """Blit the bubble from a small cache (text layout is the slow part)."""
    key = (bubble["text"], bubble["style"], theme.scheme, max_width, factor)
    cache = getattr(pet, "_bubbles", None)
    if cache is None:
        cache = pet._bubbles = {}
    entry = cache.get(key)
    if entry is None:
        if len(cache) > 6:
            cache.clear()
        bw, bh = int(max_width + 40), 84
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, bw * factor, bh * factor)
        surface.set_device_scale(factor, factor)
        bcr = cairo.Context(surface)
        draw_bubble(bcr, bw / 2.0, bh - 4.0, bubble["text"], bubble["style"], theme, max_width=max_width,
                    min_x=2.0, max_x=bw - 2.0)
        surface.flush()
        entry = cache[key] = (surface, bw, bh)
    surface, bw, bh = entry
    cr.set_source_surface(surface, round(tip_x - bw / 2.0), round(tip_y - (bh - 4.0)))
    if alpha < 1.0:
        cr.paint_with_alpha(max(0.0, alpha))
    else:
        cr.paint()


def scene_extents(pet, width, height, frac=(0.0, 0.0)):
    """Loose bounding box (x0, y0, x1, y1 in window px) of everything
    ``draw_scene`` will paint this frame — the only part worth redrawing."""
    scale = pet.world.scale
    pose = pet.pose
    ox = width / 2.0 + frac[0]
    oy = height - GROUND * scale + frac[1]
    lift = max(0.0, pose.lift)
    if pose.held:
        x0, y0, x1, y1 = -80.0, -126.0, 80.0, 30.0
    else:
        x0, y0, x1, y1 = -54.0, -112.0 - lift, 54.0, 9.0
        if pose.prop in ("terminal", "globe", "gear", "chalkboard", "coil"):
            if pose.prop_side > 0:
                x1 = 78.0
            else:
                x0 = -78.0
            y0 = min(y0, -78.0)
        elif pose.prop == "sign":
            y0 = min(y0, -124.0 - lift)
        if "cloud" in pose.marks or pose.item_at == "over" and pose.item:
            y0 = min(y0, -134.0)
        if pose.shock:
            x0, x1, y0 = min(x0, -62.0), max(x1, 62.0), min(y0, -122.0)
        for hand in (pose.hand_l, pose.hand_r):
            if hand is not None:
                x0, x1 = min(x0, hand[0] - 12.0), max(x1, hand[0] + 12.0)
                y0 = min(y0, hand[1] - 12.0)
        if pose.item == "joint":
            y0 = min(y0, -70.0)
            x1 = max(x1, 60.0)
        if pet.minis:
            reach = max(abs(v) for v in MINI_SLOTS[:pet.minis]) + 24.0
            x0, x1 = min(x0, -reach), max(x1, reach)
    for part in pet.fx.items:
        pad = 14.0 if part.kind == "text" else 8.0 + part.sway
        x0, x1 = min(x0, part.x - pad), max(x1, part.x + pad)
        y0, y1 = min(y0, part.y - pad), max(y1, part.y + pad)
    box = [ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale]
    if pet.bubble and not pose.held:
        tip = oy - (getattr(pet, "_bubble_y", bubble_anchor_y(pose)) + lift * 0.5 + 6.0) * scale
        box[0], box[2] = 0.0, float(width)
        box[1] = min(box[1], tip - 64.0 * max(1.0, scale * 0.9))
        box[3] = max(box[3], tip + 16.0 * scale)
    return (max(0, int(box[0]) - 3), max(0, int(box[1]) - 3),
            min(int(width), int(box[2]) + 4), min(int(height), int(box[3]) + 4))


def draw_scene(cr, pet, width, height, theme, config, now, frac=(0.0, 0.0), clear=True, factor=1):
    scale = pet.world.scale
    if clear:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
    ox = width / 2.0 + frac[0]
    oy = height - GROUND * scale + frac[1]
    pop = ease_out_back(pet.appear) if pet.appear < 1.0 else 1.0
    if pop <= 0.01:
        return
    cr.save()
    cr.translate(ox, oy)
    cr.scale(scale * pop, scale * pop)
    pose = pet.pose
    if pet.minis and not pose.held:
        for i in range(pet.minis):
            cr.save()
            cr.translate(MINI_SLOTS[i % len(MINI_SLOTS)], 0)
            cr.scale(MINI_SCALE, MINI_SCALE)
            draw_pet(cr, pet.design, _mini_pose(pet, i))
            cr.restore()
    if pop == 1.0:
        _draw_pet_layer(cr, pet, pose, config, scale * factor)
    else:
        draw_pet(cr, pet.design, pose, rim=RIM if config.get("sticker_rim", True) else None)
    pet.fx.draw(cr)
    cr.restore()

    bubble = pet.bubble
    if bubble and not pose.held:
        age = now - bubble["t0"]
        left = bubble["until"] - now
        alpha = 1.0 if left > 0 else max(0.0, 1.0 + left / 0.25)
        grow = 0.6 + 0.4 * ease_out_back(min(1.0, age / 0.2)) if age < 0.2 else 1.0
        target = bubble_anchor_y(pose)
        current = getattr(pet, "_bubble_y", target)
        current += (target - current) * 0.25
        pet._bubble_y = current
        lift = max(0.0, pose.lift) * 0.5
        tip_y = oy - (current + lift) * scale
        max_width = 210.0 * max(1.0, scale * 0.9)
        if grow == 1.0 and max_width + 48 <= width:
            _bubble_layer(cr, pet, bubble, theme, ox, tip_y, alpha, max_width, width, factor)
        else:
            draw_bubble(cr, ox, tip_y, bubble["text"], bubble["style"], theme, alpha=alpha, pop=grow,
                        max_width=max_width, min_x=4.0, max_x=width - 4.0)


def render_png(path, pet, theme, config, now, background=None):
    """Off-screen render of one pet's window (for snapshots and tests)."""
    w, h = window_size(pet.world.scale)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    if background is not None:
        cr.set_source_rgb(*rgb(background))
        cr.paint()
    draw_scene(cr, pet, w, h, theme, config, now, clear=background is None)
    surface.write_to_png(path)
    return path

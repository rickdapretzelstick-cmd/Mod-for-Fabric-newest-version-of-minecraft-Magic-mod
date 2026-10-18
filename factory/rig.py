"""Procedural character rig + comedic action library. Draws the triangle-hat character per frame from a pose
(squash/stretch, rotation, arms, feet, floppy hat, expressive eyes, FX) so it can hop, slip, spin and double-take."""
import math, random
from PIL import Image, ImageDraw, ImageFilter
from . import util

R, CS, PIV = 3, 760, 380        # px per unit, canvas size, pivot (body centre) pixel
H_UNITS = 130.0                 # character height incl. hat, in units


def _hex(c, d):
    try:
        c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return d


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def default_pose():
    return dict(dx=0.0, dy=0.0, rot=0.0, sx=1.0, sy=1.0, hat_rot=0.0, hat_pop=0.0, look=(0.0, 0.0), wide=1.0, blink=0.0, wink=False,
                mouth=0.0, arm_l=15.0, arm_r=15.0, foot_l=0.0, foot_r=0.0, flip=1, fx=[], lantern=True, shadow=1.0)


def draw_rig(cloth, accent, pose, t=0.0, ghost=False):
    """Returns an RGBA canvas (CS x CS) with the pivot (body centre) at (PIV, PIV)."""
    im = Image.new("RGBA", (CS, CS), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    p = dict(default_pose(), **pose); sx, sy, fl = p["sx"], p["sy"], p["flip"]
    P = lambda x, y: (PIV + x * fl * sx * R, PIV + (y * sy + 60) * R)
    dark = _shade(cloth, .62); skin = (30, 24, 34); glove = accent
    # feet
    for side, lift in ((-1, p["foot_l"]), (1, p["foot_r"])):
        cx, cy = P(side * 11, -lift); d.ellipse([cx - 8 * sx * R, cy - 4 * sy * R, cx + 8 * sx * R, cy + 4 * sy * R], fill=(36, 28, 40, 255))
    # arms behind body
    def arm(side, ang):
        a = math.radians(ang); sh = (side * 13, -56); hand = (side * 13 + side * 21 * math.sin(a) * 1.0, -56 + 21 * math.cos(a))
        d.line([P(*sh), P(*hand)], fill=dark + (255,), width=int(7.5 * R)); hx, hy = P(*hand)
        d.ellipse([hx - 4.5 * R, hy - 4.5 * R, hx + 4.5 * R, hy + 4.5 * R], fill=glove + (255,)); return hand
    hl = arm(-1, p["arm_l"])
    # body
    d.polygon([P(-24, 0), P(24, 0), P(12, -66), P(-12, -66)], fill=cloth + (255,))
    d.polygon([P(-6, 0), P(24, 0), P(12, -66), P(4, -66)], fill=_shade(cloth, .82) + (255,))
    d.polygon([P(-13, -63), P(13, -63), P(12.5, -69), P(-12.5, -69)], fill=accent + (255,))
    hr_ = arm(1, p["arm_r"])
    if p["lantern"] and not ghost:
        lx, ly = P(hr_[0] * 1.0, hr_[1] + 9); g = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        ImageDraw.Draw(g).ellipse([lx - 16 * R, ly - 16 * R, lx + 16 * R, ly + 16 * R], fill=accent + (70,)); im.alpha_composite(g)
        d.rectangle([lx - 4 * R, ly - 4 * R, lx + 4 * R, ly + 5 * R], fill=(255, 226, 150, 255), outline=(90, 62, 30, 255), width=R)
    # head: faceless. A soft highlight crescent on the side it is "looking" toward keeps it readable.
    lx_, ly_ = p["look"]; hx, hy = P(lx_ * 1.2, -79 + ly_ * 1.0); rr = 14 * R * (sx + sy) / 2
    d.ellipse([hx - rr, hy - rr, hx + rr, hy + rr], fill=skin + (255,))
    d.arc([hx - rr * .8, hy - rr * .8, hx + rr * .8, hy + rr * .8], 200 if lx_ <= 0 else 290, 250 if lx_ <= 0 else 340, fill=(74, 62, 92, 255), width=int(1.6 * R))
    # hat (floppy tip)
    pop = p["hat_pop"]; hrot = p["hat_rot"]
    d.polygon([P(-17, -88 - pop), P(17, -88 - pop), P(hrot * 20 + 3, -123 - pop + abs(hrot) * 7)], fill=cloth + (255,))
    d.polygon([P(-17, -88 - pop), P(-2, -88 - pop), P(hrot * 20 + 3, -123 - pop + abs(hrot) * 7)], fill=_shade(cloth, .8) + (255,))
    bx0, by0 = P(-19.5, -90 - pop); bx1, by1 = P(19.5, -86 - pop); d.ellipse([bx0, by0, bx1, by1], fill=accent + (255,))
    # FX (drawn upright around the head)
    ftop = -128 - pop
    ages = p.get("fx_age", {})
    for fx in p["fx"]:
        lim = p.get("fx_lim", {}).get(fx, .5); age = ages.get(fx, .25); alpha = min(1.0, age / .07) * min(1.0, max(0.0, (lim - age) / .15))
        if alpha <= .02:
            continue
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        pop_s = .75 + .25 * min(1.0, age / .1)
        if fx == "stars":
            for k in range(3):
                a = t * 6 + k * 2.09; x, y = P(math.cos(a) * 15, ftop - 2 + math.sin(a) * 3); s_ = 2.8 * R * pop_s
                d.polygon([(x, y - s_), (x + s_ * .35, y - s_ * .35), (x + s_, y), (x + s_ * .35, y + s_ * .35), (x, y + s_), (x - s_ * .35, y + s_ * .35), (x - s_, y), (x - s_ * .35, y - s_ * .35)], fill=(255, 236, 120, 255))
        elif fx == "sweat":
            u = min(1.0, age / lim); x, y = P(21, -97 + u * 16); r_ = 2.9 * R * pop_s
            d.polygon([(x, y - r_ * 1.9), (x - r_, y), (x + r_, y)], fill=(150, 210, 255, 255)); d.ellipse([x - r_, y - r_, x + r_, y + r_], fill=(150, 210, 255, 255))
        elif fx == "exclaim":
            x, y = P(0, ftop - 5); f = util.font(int(19 * R * pop_s)); d.text((x, y), "!", font=f, fill=(255, 70, 60, 255), anchor="mm", stroke_width=int(R * .8), stroke_fill=(255, 255, 255, 255))
        elif fx == "question":
            x, y = P(0, ftop - 5); f = util.font(int(19 * R * pop_s)); d.text((x, y), "?", font=f, fill=(90, 170, 255, 255), anchor="mm", stroke_width=int(R * .8), stroke_fill=(255, 255, 255, 255))
        elif fx == "hearts":
            x, y = P(12, ftop + 4 - min(1.0, age / .5) * 10); s_ = 3.4 * R * pop_s
            d.ellipse([x - s_, y - s_, x, y], fill=(255, 100, 140, 255)); d.ellipse([x, y - s_, x + s_, y], fill=(255, 100, 140, 255)); d.polygon([(x - s_, y - s_ * .4), (x + s_, y - s_ * .4), (x, y + s_ * 1.1)], fill=(255, 100, 140, 255))
        elif fx == "sparkle":
            x, y = P(17, ftop + 8); s_ = 3.8 * R * pop_s
            d.polygon([(x, y - s_), (x + s_ * .25, y - s_ * .25), (x + s_, y), (x + s_ * .25, y + s_ * .25), (x, y + s_), (x - s_ * .25, y + s_ * .25), (x - s_, y), (x - s_ * .25, y - s_ * .25)], fill=(255, 255, 255, 255))
        layer.putalpha(layer.split()[3].point(lambda v, a_=alpha: int(v * a_))); im.alpha_composite(layer)
    if ghost:
        im.putalpha(im.split()[3].point(lambda v: int(v * .58)))
    rot = p["rot"]
    return im.rotate(rot, resample=Image.BICUBIC, center=(PIV, PIV)) if abs(rot) > .3 else im


# ---------------------------- actions ----------------------------
def lerp(a, b, u): return a + (b - a) * u
def clamp(u): return max(0.0, min(1.0, u))
def ease(u): u = clamp(u); return u * u * (3 - 2 * u)
def ease_out_back(u):
    u = clamp(u); c = 1.70158; return 1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2


def hop(t, period, height):
    """Looping hop: returns (dy, sx, sy). Airborne 75% with stretch, then a squash on landing."""
    tau = (t % period) / period
    if tau < .75:
        u = tau / .75; return height * 4 * u * (1 - u), 1 - .08 * math.sin(math.pi * u), 1 + .16 * math.sin(math.pi * u)
    v = (tau - .75) / .25; q = .24 * math.sin(math.pi * v); return 0.0, 1 + q * .9, 1 - q


def blink_for(t): return 1.0 if (t % 2.7) < .12 else 0.0


def idle(t, dur):
    p = default_pose(); p.update(sy=1 + .015 * math.sin(t * 5), look=(math.sin(t * 1.3) * .6, 0), hat_rot=.12 * math.sin(t * 2), arm_l=14 + 3 * math.sin(t * 3), arm_r=14 - 3 * math.sin(t * 3)); return p


def slip(t, dur):
    """Glides in upright and unbothered, freezes, topples like a plank, pops back up, tips hat, marches on."""
    p = default_pose(); u = t / dur
    if u < .34:
        q = u / .34; p.update(dx=lerp(-.95, -.1, ease(q)), rot=3 * math.sin(q * 5), arm_l=75, arm_r=75, hat_rot=.2, look=(1, 0), fx=["sweat"] if q > .55 else [])
    elif u < .5:
        q = (u - .34) / .16; fall = ease(clamp((q - .25) / .75)) ** 1.6
        p.update(dx=-.1 + .15 * fall, dy=-.34 * fall + .06 * math.sin(math.pi * clamp(q * 1.4)), rot=-92 * fall, arm_l=75 - 55 * fall, arm_r=75 - 55 * fall, hat_rot=.2, fx=(["exclaim"] if q < .45 else []) + (["sweat"] if q < .6 else []))
    elif u < .66:
        p.update(dx=.05, dy=-.34, rot=-92 + .8 * math.sin(t * 9), arm_l=20, arm_r=20, hat_rot=.1 + .1 * math.sin(t * 7), fx=["sweat"])
    elif u < .76:
        q = (u - .66) / .1; p.update(dx=.05, dy=lerp(-.34, 0, ease(q)) + .22 * 4 * q * (1 - q), rot=lerp(-92, 0, ease_out_back(q)), sy=1 + .12 * math.sin(math.pi * q), sx=1 - .05 * math.sin(math.pi * q), arm_l=25, arm_r=25)
    elif u < .88:
        q = (u - .76) / .12; p.update(dx=.05, arm_r=lerp(20, 165, ease(min(1, q * 2))) if q < .7 else 165, hat_rot=-.7 * math.sin(math.pi * clamp(q * 1.4)), look=(1, 0))
    else:
        q = (u - .88) / .12; dy, sx, sy = hop(q, .5, .07); p.update(dx=.05 + .45 * q, dy=dy, sx=sx, sy=sy, arm_l=35 * math.sin(t * 14), arm_r=-35 * math.sin(t * 14) + 20, look=(1, 0))
    return p


def stair_hop(t, dur):
    """Determined little hops up the stairs, a tired pause with one sweat drop, then a stiff little double-take."""
    p = default_pose(); u = t / dur
    if u < .55:
        prog = u / .55; dy, sx, sy = hop(t, lerp(.46, .6, prog), .1); p.update(dx=lerp(-.6, .5, prog), dy=dy + lerp(0, .9, prog), sx=sx, sy=sy, arm_l=40 + 22 * math.sin(t * 12), arm_r=40 - 22 * math.sin(t * 12), look=(.8, -.3), hat_rot=-.15 * math.sin(t * 12), fx=["sweat"] if (u > .3 and (t % 1.2) < .85) else [])
    elif u < .76:
        p.update(dx=.5, dy=.9, sy=.95 + .02 * math.sin(t * 7), sx=1.03, rot=2 * math.sin(t * 4), arm_l=8, arm_r=8, hat_rot=-.6, look=(0, 1), fx=["sweat"] if (t % 1.2) < .85 else [])
    else:
        q = (u - .76) / .24; j = clamp(q * 4); dy, _, _ = hop(max(0, q - .08), .5, .12)
        p.update(dx=.5 - .06 * ease(j), dy=.9 + dy, rot=-6 * math.sin(clamp(q * 3) * math.pi), arm_l=60, arm_r=60, hat_rot=.5 * math.sin(math.pi * clamp(q * 2)), hat_pop=5 * math.sin(math.pi * clamp(q * 2)), look=(-1, -.2), fx=["exclaim"] if q < .4 else [])
    return p


def startle_spin(t, dur):
    """Deadpan shielding eyes from the lens, then one clean quick spin-jump, lands, steadies, determined."""
    p = default_pose(); u = t / dur
    if u < .3:
        p.update(arm_r=160, arm_l=15, hat_rot=-.2, sy=1 - .015 * math.sin(t * 16), look=(.5, 0))
    elif u < .6:
        q = (u - .3) / .3; air = 4 * q * (1 - q); p.update(dy=.7 * air, sy=1 + .14 * math.sin(math.pi * q), sx=1 - .06 * math.sin(math.pi * q), rot=-360 * ease(q), arm_l=35, arm_r=35, hat_pop=9 * math.sin(math.pi * q), hat_rot=lerp(-.6, .6, q), fx=["exclaim"] if q < .3 else [])
    else:
        q = (u - .6) / .4; land = .18 * math.sin(math.pi * clamp(q * 4)) * (1 if q < .25 else 0); p.update(sy=1 - land, sx=1 + land, rot=5 * math.sin(t * 8) * max(0, 1 - q * 1.6), arm_l=20, arm_r=20, hat_rot=.3 * math.sin(t * 6) * (1 - q), fx=(["stars"] if q < .2 else []) + (["sweat"] if .15 < q < .85 else []))
    return p


def gawk(t, dur):
    """Looks down, a quiet question mark, two small excited hops, leans a bit too far, snaps upright with a thumbs up."""
    p = default_pose(); u = t / dur
    if u < .3:
        q = u / .3; p.update(look=(0, 1), rot=lerp(0, 6, ease(q)), arm_l=25, arm_r=25, hat_rot=-.2, fx=["question"] if q < .5 else [])
    elif u < .6:
        dy, sx, sy = hop(t, .42, .09); p.update(dy=dy, sx=sx, sy=sy, look=(0, 1), arm_l=60 + 18 * math.sin(t * 14), arm_r=60 - 18 * math.sin(t * 14), rot=6)
    elif u < .82:
        q = (u - .6) / .22; p.update(rot=lerp(6, 28, ease(q)), dx=lerp(0, .18, ease(q)), arm_l=lerp(60, 105, q), arm_r=lerp(60, 105, q), look=(0, 1), foot_l=lerp(0, 3, q), fx=["sweat"] if q > .3 else [])
    else:
        q = (u - .82) / .18; p.update(rot=lerp(28, 0, ease_out_back(q)), dx=lerp(.18, 0, ease(q)), sy=1 + .1 * math.sin(math.pi * q), sx=1 - .04 * math.sin(math.pi * q), arm_l=25, arm_r=165, fx=["sparkle"] if q > .5 else [], hat_rot=-.2)
    return p


def cry_hop(t, dur):
    """Stoic trembling (barely holding it together), then turns, opens arms and does two small happy hops."""
    p = default_pose(); u = t / dur
    if u < .5:
        sh = math.sin(t * 30); p.update(dx=.008 * sh, rot=1.4 * sh, sy=1 - .012 * abs(sh), arm_l=12, arm_r=12, hat_rot=-.4 + .05 * sh, look=(.7, .3), fx=["sweat"] if (u > .08 and (t % 1.2) < .85) else [])
    elif u < .62:
        q = (u - .5) / .12; p.update(arm_l=lerp(12, 100, ease(q)), arm_r=lerp(12, 100, ease(q)), sy=1 + .08 * math.sin(math.pi * q), hat_rot=lerp(-.4, .2, q), look=(1, 0), fx=["exclaim"] if q < .5 else [])
    else:
        q = (u - .62) / .38; dy, sx, sy = hop(t, .46, .13); p.update(dy=dy, sx=sx, sy=sy, dx=.2 * ease(q), arm_l=100 + 12 * math.sin(t * 9), arm_r=100 - 12 * math.sin(t * 9), hat_rot=.35 * math.sin(t * 9), look=(1, 0), fx=["hearts"] if q < .4 else [])
    return p


def victory(t, dur):
    """Quietly proud: hat tip with a small sparkle, then a compact arms-down backflip and a firm landing."""
    p = default_pose(); u = t / dur
    if u < .4:
        q = u / .4; p.update(arm_r=lerp(15, 160, ease(min(1, q * 1.6))), hat_rot=.5 * math.sin(clamp((q - .45) * 4) * math.pi), look=(1, -.2), fx=["sparkle"] if .5 < q < .9 else [])
    elif u < .78:
        q = (u - .4) / .38; air = 4 * q * (1 - q); crouch = .16 * math.sin(math.pi * clamp(q * 6)) * (1 if q < .17 else 0)
        p.update(dy=.85 * air, sy=1 - crouch + .1 * math.sin(math.pi * q), sx=1 + crouch * .8, rot=lerp(0, 360, ease(clamp((q - .12) / .7))), arm_l=30, arm_r=30, hat_pop=8 * math.sin(math.pi * q))
    else:
        q = (u - .78) / .22; land = .18 * math.sin(math.pi * clamp(q * 4)) * (1 if q < .25 else 0); p.update(sy=1 - land, sx=1 + land, arm_r=160, arm_l=20, hat_rot=.2, look=(1, 0), fx=["sparkle"] if .35 < q < .7 else [])
    return p


def _brief(fn):
    """Each symbol is shown only for its first ~0.5 s of continuous presence, then dropped (brief, not lingering)."""
    def wrapped(t, dur):
        p = fn(t, dur); ages = {}
        for f in p["fx"]:
            lim = 1.0 if f == "sweat" else .5; age = 0.0
            for k in range(1, 23):
                tt = t - .05 * k
                if tt < 0 or f not in fn(tt, dur)["fx"]:
                    break
                age = .05 * k
            else:
                age = lim + .1
            if age <= lim:
                ages[f] = age
        p["fx"] = list(ages); p["fx_age"] = ages; p["fx_lim"] = {f: (1.0 if f == "sweat" else .5) for f in ages}
        return p
    return wrapped


ACTIONS = {k: _brief(v) for k, v in {"idle": idle, "slip": slip, "stair_hop": stair_hop, "startle_spin": startle_spin, "gawk": gawk, "cry_hop": cry_hop, "victory": victory}.items()}


def ghost_pose(t, dur, action):
    """Golden second figure: floats, and drifts in to the hero on the 'cry_hop' scene."""
    p = default_pose(); u = t / dur
    p.update(dy=.08 + .05 * math.sin(t * 2.6), sy=1 + .02 * math.sin(t * 4), arm_l=40 + 20 * math.sin(t * 2), arm_r=60 + 25 * math.sin(t * 2.4), mouth=.1, hat_rot=.3 * math.sin(t * 2), flip=-1, lantern=False, shadow=.3, fx=[])
    p["dx"] = (.95 - .25 * ease(u * 1.6)) if action == "cry_hop" else .95
    if action == "cry_hop" and u > .6:
        p["dx"] = .7 + .05 * math.sin(t * 5); p["arm_l"] = 110; p["arm_r"] = 110
    return p

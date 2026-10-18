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
    fxs = list(p["fx"])
    if p["wide"] >= 1.7 and "shock" not in fxs:
        fxs.append("shock")          # surprise burst replaces wide eyes
    for fx in fxs:
        if fx == "stars":
            for k in range(3):
                a = t * 7 + k * 2.09; x, y = P(math.cos(a) * 20, ftop - 4 + math.sin(a) * 4); s = 4 * R
                d.polygon([(x, y - s), (x + s * .35, y - s * .35), (x + s, y), (x + s * .35, y + s * .35), (x, y + s), (x - s * .35, y + s * .35), (x - s, y), (x - s * .35, y - s * .35)], fill=(255, 236, 120, 255))
        elif fx == "sweat":
            for k, ph in enumerate((0, .5)):
                u = (t * 2.2 + ph) % 1; x, y = P(22 + k * 8, -98 + u * 20); r_ = 3.2 * R
                d.polygon([(x, y - r_ * 1.9), (x - r_, y), (x + r_, y)], fill=(150, 210, 255, int(255 * (1 - u * .6)))); d.ellipse([x - r_, y - r_, x + r_, y + r_], fill=(150, 210, 255, int(255 * (1 - u * .6))))
        elif fx == "shock":
            hx2, hy2 = P(0, -79); pul = 1 + .12 * math.sin(t * 22)
            for k in range(9):
                a = math.radians(-160 + k * 18); r0, r1 = 20 * pul, 31 * pul
                d.line([(hx2 + math.cos(a) * r0 * R, hy2 + math.sin(a) * r0 * R), (hx2 + math.cos(a) * r1 * R, hy2 + math.sin(a) * r1 * R)], fill=(255, 255, 255, 255), width=int(2.4 * R))
        elif fx == "question":
            x, y = P(0, ftop - 10 - abs(math.sin(t * 6)) * 4); f = util.font(int(26 * R)); d.text((x, y), "?", font=f, fill=(90, 170, 255, 255), anchor="mm", stroke_width=R, stroke_fill=(255, 255, 255, 255))
        elif fx == "anger":
            x, y = P(17, -92); s_ = 5 * R * (1 + .15 * math.sin(t * 20))
            for da in (0, 90):
                a = math.radians(da + 45); d.line([(x - math.cos(a) * s_, y - math.sin(a) * s_), (x + math.cos(a) * s_, y + math.sin(a) * s_)], fill=(255, 60, 50, 255), width=int(2.2 * R))
        elif fx == "speed":
            for k in range(4):
                x0, y0 = P(-34 - k * 6 - (t * 40 % 10), -50 + k * 14); d.line([(x0, y0), (x0 - 16 * R, y0)], fill=(255, 255, 255, 180), width=int(1.8 * R))
        elif fx == "tears":
            for side in (-1, 1):
                u = (t * 3 + (0 if side < 0 else .4)) % 1; x, y = P(side * 7, -76 + u * 20); d.ellipse([x - 2 * R, y - 2.8 * R, x + 2 * R, y + 2.8 * R], fill=(150, 205, 255, int(255 * (1 - u * .7))))
        elif fx == "exclaim":
            x, y = P(0, ftop - 8 - abs(math.sin(t * 12)) * 5); f = util.font(int(26 * R)); d.text((x, y), "!", font=f, fill=(255, 70, 60, 255), anchor="mm", stroke_width=R, stroke_fill=(255, 255, 255, 255))
        elif fx == "hearts":
            for k in range(3):
                u = (t * 1.1 + k / 3) % 1; x, y = P(-14 + k * 14 + math.sin(t * 5 + k) * 3, ftop + 8 - u * 24); s = (3.4 + k * .4) * R
                d.ellipse([x - s, y - s, x, y], fill=(255, 100, 140, int(255 * (1 - u)))); d.ellipse([x, y - s, x + s, y], fill=(255, 100, 140, int(255 * (1 - u))))
                d.polygon([(x - s, y - s * .4), (x + s, y - s * .4), (x, y + s * 1.1)], fill=(255, 100, 140, int(255 * (1 - u))))
        elif fx == "sparkle":
            for k in range(4):
                u = (t * 2 + k * .25) % 1; x, y = P(-22 + k * 15, ftop + 14 - (k % 2) * 16); s = (1 - abs(u - .5) * 2) * 4.5 * R
                d.polygon([(x, y - s), (x + s * .25, y - s * .25), (x + s, y), (x + s * .25, y + s * .25), (x, y + s), (x - s * .25, y + s * .25), (x - s, y), (x - s * .25, y - s * .25)], fill=(255, 255, 255, 255))
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
    p = default_pose(); p.update(sy=1 + .02 * math.sin(t * 5), blink=blink_for(t), look=(math.sin(t * 1.3) * .8, 0), hat_rot=.15 * math.sin(t * 2), arm_l=14 + 4 * math.sin(t * 3), arm_r=14 - 4 * math.sin(t * 3)); return p


def slip(t, dur):
    """Skates in on the ice, flails, slips onto their back, springs up, hops off. Hat floppy throughout."""
    p = default_pose(); u = t / dur; p["blink"] = blink_for(t)
    if u < .34:           # sliding in, windmilling
        q = u / .34; p.update(dx=lerp(-.95, -.1, ease(q)), rot=-12 * math.sin(q * 9), arm_l=100 + 70 * math.sin(t * 16), arm_r=100 - 70 * math.sin(t * 16),
                              foot_l=2 + 2 * math.sin(t * 14), foot_r=2 - 2 * math.sin(t * 14), wide=1.5, mouth=.8, hat_rot=-.9, look=(1, 0), fx=["sweat", "speed"])
    elif u < .52:         # the slip: flips onto back
        q = (u - .34) / .18; p.update(dx=lerp(-.1, .05, q), dy=.45 * 4 * q * (1 - q) - .36 * ease(q - .2) * 0, rot=lerp(0, -98, ease(q)), arm_l=170, arm_r=170, wide=1.8, mouth=1, hat_rot=1, hat_pop=10 * q, fx=["exclaim"])
        p["dy"] = .45 * 4 * q * (1 - q) - .34 * ease((q - .6) / .4)
    elif u < .68:         # lying there, dazed
        q = (u - .52) / .16; p.update(dx=.05, dy=-.34, rot=-98 + 3 * math.sin(t * 9), arm_l=140 + 20 * math.sin(t * 6), arm_r=40, wide=.8, mouth=.3, fx=["stars"], hat_pop=2, look=(math.sin(t * 8), 0), hat_rot=.2)
    elif u < .8:          # spring up with overshoot
        q = (u - .68) / .12; e = ease_out_back(q); p.update(dx=.05, dy=lerp(-.34, 0, ease(q)) + .55 * 4 * q * (1 - q), rot=lerp(-98, 0, e), sy=1 + .22 * math.sin(math.pi * q), sx=1 - .1 * math.sin(math.pi * q), arm_l=160, arm_r=160, wide=1.4, mouth=.7, hat_rot=-.8)
    else:                 # hop away, brushing off
        q = (u - .8) / .2; dy, sx, sy = hop(q, .5, .22); p.update(dx=.05 + .6 * q, dy=dy, sx=sx, sy=sy, arm_l=30 + 40 * math.sin(t * 20), arm_r=20, mouth=.2, wink=True, hat_rot=.4 * math.sin(t * 10))
    return p


def stair_hop(t, dur):
    """Bounces up the stairs, tires out, then does a huge double-take at the carved name."""
    p = default_pose(); u = t / dur; p["blink"] = blink_for(t)
    if u < .55:
        period = lerp(.42, .62, u / .55); dy, sx, sy = hop(t, period, .2 - .08 * u); prog = u / .55
        p.update(dx=lerp(-.6, .5, prog), dy=dy + lerp(0, .9, prog), sx=sx, sy=sy, arm_l=60 + 50 * math.sin(t * 14), arm_r=60 - 50 * math.sin(t * 14), foot_l=4 * max(0, math.sin(t * 14)), foot_r=4 * max(0, -math.sin(t * 14)),
                 mouth=.4, hat_rot=-.4 * math.sin(t * 14), look=(.8, -.3), fx=["sweat"] if u > .3 else [])
    elif u < .76:         # exhausted wobble
        q = (u - .55) / .21; p.update(dx=.5, dy=.9, sy=.92 + .04 * math.sin(t * 8), sx=1.06, rot=6 * math.sin(t * 5), arm_l=5, arm_r=5, mouth=.6 + .3 * math.sin(t * 10), wide=.7, hat_rot=-1, hat_pop=-3, fx=["sweat"], look=(0, 1))
    else:                 # sees name → double take
        q = (u - .76) / .24; j = ease_out_back(clamp(q * 3)); dy, _, _ = hop(max(0, q - .1), .5, .35)
        p.update(dx=.5 - .1 * j, dy=.9 + dy, sy=1 + .25 * math.sin(math.pi * clamp(q * 2.2)), sx=1 - .08 * math.sin(math.pi * clamp(q * 2.2)), rot=-14 * math.sin(clamp(q * 3) * math.pi), arm_l=170, arm_r=165,
                 wide=1.9, mouth=1, hat_pop=14 * math.sin(math.pi * clamp(q * 2)), hat_rot=1, fx=["exclaim"], look=(-1, -.2))
    return p


def startle_spin(t, dur):
    """Shields eyes from the blinding lens, then leaps in a 360 spin, hat flying off, lands dizzy."""
    p = default_pose(); u = t / dur; p["blink"] = 0.0
    if u < .3:            # squinting, arm up
        p.update(arm_r=165, arm_l=20, wide=.55, blink=1.0 if math.sin(t * 9) > .3 else 0.0, mouth=.1, hat_rot=-.2, sy=1 - .03 * math.sin(t * 20), look=(.5, 0))
    elif u < .72:
        q = (u - .3) / .42; air = 4 * q * (1 - q); p.update(dy=.95 * air, sy=1 + .2 * math.sin(math.pi * q), sx=1 - .1 * math.sin(math.pi * q), rot=-360 * ease(q), arm_l=160, arm_r=160, wide=1.8, mouth=1,
                                                            hat_pop=26 * math.sin(math.pi * q), hat_rot=lerp(-1, 1, q), fx=["exclaim"] if q < .4 else ["shock"], foot_l=6 * air, foot_r=6 * air)
    else:
        q = (u - .72) / .28; land = .26 * math.sin(math.pi * clamp(q * 3)) * (1 if q < .34 else 0)
        p.update(sy=1 - land, sx=1 + land, rot=9 * math.sin(t * 7) * (1 - q), arm_l=60 + 50 * math.sin(t * 6), arm_r=60 - 50 * math.sin(t * 6), wide=.9, mouth=.5, fx=["stars"], look=(math.sin(t * 9), math.cos(t * 9)), hat_rot=.7 * math.sin(t * 6))
    return p


def gawk(t, dur):
    """Peers down, jaw-drops, bounces excitedly, leans too far, windmills, recovers with sparkles."""
    p = default_pose(); u = t / dur; p["blink"] = blink_for(t)
    if u < .3:
        q = u / .3; p.update(dy=0, sy=1 + .05 * math.sin(q * 20), look=(0, 1), wide=lerp(1, 1.5, ease(q)), mouth=ease(q), hat_pop=lerp(0, 8, ease(q)), arm_l=30, arm_r=30, rot=lerp(0, 8, ease(q)), fx=["question"])
    elif u < .65:
        q = (u - .3) / .35; dy, sx, sy = hop(t, .36, .16); p.update(dy=dy, sx=sx, sy=sy, wide=2.0, mouth=.9, look=(math.sin(t * 6), 1), arm_l=100 + 60 * math.sin(t * 18), arm_r=100 - 60 * math.sin(t * 18), hat_rot=math.sin(t * 18), fx=["sparkle"], dx=.1 * math.sin(t * 5))
    elif u < .82:         # leans too far
        q = (u - .65) / .17; p.update(rot=lerp(8, 38, ease(q)), dx=lerp(0, .25, q), arm_l=lerp(90, 170, q), arm_r=lerp(90, 170, q) + 10 * math.sin(t * 30), wide=1.8, mouth=1, foot_l=lerp(0, 6, q), hat_rot=lerp(0, 1, q), fx=["exclaim"], look=(0, 1))
    else:                 # recover
        q = (u - .82) / .18; e = ease_out_back(q); p.update(rot=lerp(38, 0, e), dx=lerp(.25, 0, ease(q)), sy=1 + .18 * math.sin(math.pi * q), sx=1 - .08 * math.sin(math.pi * q), arm_l=40, arm_r=170, wide=1.3, mouth=.4, wink=q > .5, fx=["sparkle"], hat_rot=-.4)
    return p


def cry_hop(t, dur):
    """Sobs (comically shaking), then bursts into joyful hops and a spin of happiness."""
    p = default_pose(); u = t / dur
    if u < .45:
        sh = math.sin(t * 38); p.update(dx=.02 * sh, sy=1 - .03 * abs(sh), sx=1 + .03 * abs(sh), rot=3 * sh, arm_l=140, arm_r=140, wide=1.2, mouth=.8 + .2 * sh, fx=["tears", "sweat"], hat_rot=-.9, look=(0, .5), hat_pop=-2)
    elif u < .6:
        q = (u - .45) / .15; p.update(sy=1 + .22 * math.sin(math.pi * q), rot=0, arm_l=lerp(140, 170, q), arm_r=lerp(140, 170, q), wide=lerp(1.2, 1.8, q), mouth=.9, fx=["exclaim"], hat_rot=lerp(-.9, 1, q))
    else:
        q = (u - .6) / .4; dy, sx, sy = hop(t, .42, .3); spin = 360 * ease(clamp((q - .35) / .4)) if .35 < q < .75 else 0
        p.update(dy=dy, sx=sx, sy=sy, dx=.35 * ease(q) * .6, rot=-spin, arm_l=120 + 50 * math.sin(t * 12), arm_r=120 - 50 * math.sin(t * 12), wide=1.3, mouth=.7, fx=["hearts"], hat_rot=math.sin(t * 12), blink=0, wink=False)
    return p


def victory(t, dur):
    """Proud pose, hat tip and wink, then a full backflip and a hero landing."""
    p = default_pose(); u = t / dur; p["blink"] = blink_for(t)
    if u < .4:
        q = u / .4; p.update(sy=1 + .015 * math.sin(t * 6), arm_r=lerp(15, 150, ease(q)), arm_l=lerp(15, 40, q), hat_rot=.5 * math.sin(q * 6) * (1 - q * .5), wink=q > .55, mouth=.3, look=(1, -.2), rot=-4 * q, fx=["sparkle"] if q > .5 else [])
    elif u < .8:
        q = (u - .4) / .4; air = 4 * q * (1 - q); crouch = .22 * math.sin(math.pi * clamp(q * 5)) * (1 if q < .2 else 0)
        p.update(dy=1.1 * air, sy=1 - crouch + .15 * math.sin(math.pi * q), sx=1 + crouch * .8, rot=lerp(0, 360, ease(clamp((q - .12) / .7))), arm_l=150, arm_r=150, wide=1.5, mouth=1, hat_pop=18 * math.sin(math.pi * q), hat_rot=1 - 2 * q)
    else:
        q = (u - .8) / .2; land = .25 * math.sin(math.pi * clamp(q * 3)) * (1 if q < .34 else 0); p.update(sy=1 - land, sx=1 + land, arm_r=160, arm_l=160, wink=True, mouth=.7, fx=["sparkle", "hearts"] if q > .4 else ["sparkle"], hat_rot=.3, wide=1.2)
    return p


ACTIONS = {"idle": idle, "slip": slip, "stair_hop": stair_hop, "startle_spin": startle_spin, "gawk": gawk, "cry_hop": cry_hop, "victory": victory}


def ghost_pose(t, dur, action):
    """Golden second figure: floats, and drifts in to the hero on the 'cry_hop' scene."""
    p = default_pose(); u = t / dur
    p.update(dy=.08 + .05 * math.sin(t * 2.6), sy=1 + .02 * math.sin(t * 4), arm_l=40 + 20 * math.sin(t * 2), arm_r=60 + 25 * math.sin(t * 2.4), mouth=.1, hat_rot=.3 * math.sin(t * 2), flip=-1, lantern=False, shadow=.3)
    p["dx"] = (.95 - .25 * ease(u * 1.6)) if action == "cry_hop" else .95
    if action == "cry_hop" and u > .6:
        p["dx"] = .7 + .05 * math.sin(t * 5); p["arm_l"] = 150; p["arm_r"] = 150; p["fx"] = ["hearts"]
    return p

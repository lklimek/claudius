#!/usr/bin/env python3
"""Render spotlight-style annotated screenshots from a JSON spec.

usage: render.py SPEC.json --new-dir DIR [--old-dir DIR] --out-dir DIR [--scale 2]

SPEC: {"<image name>": [{"kind": "new|changed|removed|screen",
                         "rect": [x0, y0, x1, y1],          # capture pixels (1x)
                         "label": "Changed: profile name",  # 2-5 words
                         "pill": [x, y],                    # pill top-left, 1x
                         "inset": {"old": "<old image name>", # optional, removed items
                                   "crop": [x0, y0, x1, y1], "xy": [x, y]}}]}

Reads <new-dir>/<name>.png (and <old-dir>/<name>.png for the self-check and
insets); writes <out-dir>/<name>.png (labelled) and <out-dir>/clean/<name>.png.
Without --old-dir (NEW-only mode) the rect self-check is skipped and insets are
refused. Exit code 1 if a self-check fails (see selfcheck()); warnings do not
change it.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from common import capture, rect, screen_name

COL = {"new": (0, 168, 84), "changed": (123, 63, 242), "removed": (229, 57, 53)}
PAD = 5
FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans{}.ttf",
    "/Library/Fonts/DejaVuSans{}.ttf",
]
BAD = []
WARN = []
# A rect with fewer than NOISE_PIXELS pixels differing by more than NOISE_LEVEL
# (per channel, 0-255) gets a warning: check by eye that it marks the change.
NOISE_LEVEL = 24
NOISE_PIXELS = 20


def font(size, scale, bold=True):
    for pattern in FONTS:
        path = pattern.format("-Bold" if bold else "")
        if os.path.exists(path):
            return ImageFont.truetype(path, int(size * scale))
    return ImageFont.load_default()


def rr(d, r, rad, **k):
    d.rounded_rectangle(r, radius=rad, **k)


def build(name, els, a, labels):
    new_dir, old_dir, scale = a.new_dir, a.old_dir, a.scale
    s = scale
    base = capture(os.path.join(new_dir, name + ".png"))
    base = base.resize((base.width * s, base.height * s), Image.LANCZOS)
    if any(e["kind"] == "screen" for e in els):
        img = base.copy()  # a wholly new screen is not dimmed
    else:
        dim = base.convert("L").convert("RGB")
        dim = Image.blend(dim, Image.new("RGB", base.size, (150, 150, 150)), 0.5)
        mask = Image.new("L", base.size, 0)
        md = ImageDraw.Draw(mask)
        for e in els:
            if e["kind"] == "removed":
                continue  # nothing of it exists in the new capture
            r = e["rect"]
            rr(
                md,
                [
                    (r[0] - PAD) * s,
                    (r[1] - PAD) * s,
                    (r[2] + PAD) * s,
                    (r[3] + PAD) * s,
                ],
                10 * s,
                fill=255,
            )
        img = Image.composite(base, dim, mask.filter(ImageFilter.GaussianBlur(1)))
    d = ImageDraw.Draw(img)
    for e in els:
        k, r, lab = e["kind"], e["rect"], e["label"]
        c = COL["new" if k == "screen" else k]
        if k in ("screen", "removed"):
            box = [r[0] * s, r[1] * s, r[2] * s, r[3] * s]
        else:
            box = [
                (r[0] - PAD) * s,
                (r[1] - PAD) * s,
                (r[2] + PAD) * s,
                (r[3] + PAD) * s,
            ]
        if k == "removed":  # dashed outline
            x0, y0, x1, y1 = box
            dash = 18 * s // 2
            for x in range(int(x0), int(x1), dash * 2):
                d.line((x, y0, min(x + dash, x1), y0), fill=c, width=4 * s)
                d.line((x, y1, min(x + dash, x1), y1), fill=c, width=4 * s)
            for y in range(int(y0), int(y1), dash * 2):
                d.line((x0, y, x0, min(y + dash, y1)), fill=c, width=4 * s)
                d.line((x1, y, x1, min(y + dash, y1)), fill=c, width=4 * s)
        else:
            rr(d, box, 10 * s, outline=c, width=4 * s)
        px, py = e["pill"][0] * s, e["pill"][1] * s
        f = font(20, s)
        w, h = d.textlength(lab, font=f) + 28 * s, 36 * s
        if px < 0 or py < 0 or px + w > img.width or py + h > img.height:
            BAD.append((name, lab, "pill outside image"))
        if not labels:
            continue
        cx = min(max(px + w / 2, box[0]), box[2])
        cy = min(max(py + h / 2, box[1]), box[3])
        side = px > box[2] or px + w < box[0]
        sx = px if px > box[2] else (px + w if px + w < box[0] else px + w / 2)
        sy = py + h / 2 if side else (py if py > box[3] else py + h)
        tx = box[2] if px > box[2] else (box[0] if px + w < box[0] else cx)
        ty = cy if side else (box[3] if py > box[3] else box[1])
        if not (box[0] < px + w / 2 < box[2] and box[1] < py + h / 2 < box[3]):
            d.line((sx, sy, tx, ty), fill=c, width=3 * s)  # leader line
        rr(d, [px, py, px + w, py + h], 8 * s, fill=c)
        d.text((px + 14 * s, py + h / 2), lab, fill="white", font=f, anchor="lm")
        ins = e.get("inset")
        if ins and old_dir is None:
            BAD.append((name, lab, "inset needs --old-dir"))
        elif ins:
            o = capture(os.path.join(old_dir, ins["old"] + ".png")).crop(ins["crop"])
            o = o.resize((o.width * s, o.height * s), Image.LANCZOS)
            ix, iy = ins["xy"][0] * s, ins["xy"][1] * s
            img.paste(o, (ix, iy))
            d.rectangle(
                (ix - 2 * s, iy - 2 * s, ix + o.width + 2 * s, iy + o.height + 2 * s),
                outline=c,
                width=3 * s,
            )
            d.text(
                (ix, iy - 6 * s),
                "Before (previous build)" if a.lang == "en" else "Przed zmianą",
                fill=c,
                font=font(14, s),
                anchor="ld",
            )
    # corner key
    f = font(15, s)
    labels = {
        "en": ["New", "Changed", "Removed"],
        "pl": ["Nowe", "Zmienione", "Usunięte"],
    }[a.lang]
    items = list(zip(["new", "changed", "removed"], labels))
    kw = int(sum(d.textlength(t, font=f) + 60 * s for _, t in items)) + 10 * s
    kh = 34 * s
    if kw + 32 * s > img.width:
        return img
    kx, ky = img.width - kw - 16 * s, img.height - kh - 12 * s
    rr(
        d,
        [kx, ky, kx + kw, ky + kh],
        8 * s,
        fill=(255, 255, 255),
        outline=(120, 120, 120),
        width=s,
    )
    x = kx + 14 * s
    for kk, t in items:
        rr(
            d,
            [x, ky + 9 * s, x + 22 * s, ky + kh - 9 * s],
            4 * s,
            outline=COL[kk],
            width=3 * s,
        )
        d.text((x + 30 * s, ky + kh / 2), t, fill=(30, 30, 40), font=f, anchor="lm")
        x += d.textlength(t, font=f) + 60 * s
    return img


def selfcheck(name, els, a):
    """Every new/changed rect must differ between the NEW and OLD capture of the
    same screen; a highlight over identical pixels means a wrong rect.

    Compared in RGB, so a change of colour alone counts. Only a rect with no
    differing pixel at all fails; a rect that differs very little is reported
    as a warning, because a subtle restyle is a legitimate highlight."""
    if a.old_dir is None:
        return  # NEW-only mode: no OLD capture to compare against
    op = os.path.join(a.old_dir, name + ".png")
    if not os.path.exists(op):
        if els and all(el["kind"] == "screen" for el in els):
            return
        raise ValueError(
            f"{name}: OLD capture is missing; declare a new screen explicitly"
        )
    n = capture(os.path.join(a.new_dir, name + ".png"))
    o = capture(op)
    if n.size != o.size:
        raise ValueError(f"{name}: pair dimensions differ: {o.size} versus {n.size}")
    for e in els:
        if e["kind"] not in ("new", "changed"):
            continue
        ca = np.asarray(n.crop(e["rect"]), dtype=int)
        cb = np.asarray(o.crop(e["rect"]), dtype=int)
        delta = abs(ca - cb).max(axis=2)  # largest channel difference per pixel
        if not delta.any():
            BAD.append((name, e["label"], "rect identical in old and new"))
        elif int((delta > NOISE_LEVEL).sum()) < NOISE_PIXELS:
            WARN.append(
                (
                    name,
                    e["label"],
                    f"rect barely differs between old and new "
                    f"({int((delta > 0).sum())} px, largest difference {int(delta.max())} of 255)",
                )
            )


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("spec")
    p.add_argument("--new-dir", required=True)
    p.add_argument("--old-dir", help="OLD captures; omit for NEW-only mode")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--scale", type=int, default=2, choices=range(1, 5))
    p.add_argument("--lang", choices=["en", "pl"], default="en")
    a = p.parse_args()
    if a.old_dir and not Path(a.old_dir).is_dir():
        raise ValueError(f"OLD directory is missing: {a.old_dir}")
    output = Path(a.out_dir).resolve()
    sources = [Path(a.new_dir).resolve()] + (
        [Path(a.old_dir).resolve()] if a.old_dir else []
    )
    if any(path in sources for path in [output, (output / "clean").resolve()]):
        raise ValueError(
            "Output directory or its clean directory overlaps raw captures"
        )
    spec = json.load(open(a.spec))
    for name, els in spec.items():
        screen_name(name)
        with Image.open(os.path.join(a.new_dir, name + ".png")) as frame:
            for el in els:
                if el["kind"] not in (*COL, "screen"):
                    raise ValueError(f"{name}: unknown annotation kind {el['kind']!r}")
                rect(el["rect"], frame.size, f"{name} rect")
                inset = el.get("inset")
                if inset:
                    screen_name(inset["old"])
                    if a.old_dir is None:
                        raise ValueError(f"{name}: inset needs --old-dir")
                    with Image.open(
                        os.path.join(a.old_dir, inset["old"] + ".png")
                    ) as previous:
                        rect(inset["crop"], previous.size, f"{name} inset crop")
                    x, y = inset["xy"]
                    w, h = (
                        inset["crop"][2] - inset["crop"][0],
                        inset["crop"][3] - inset["crop"][1],
                    )
                    rect([x, y, x + w, y + h], frame.size, f"{name} inset destination")
    if a.old_dir is None:
        print("NEW-only mode: rect self-check skipped, check every rect by eye")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="visual-diff-", dir=output.parent) as stage:
        staged = Path(stage)
        (staged / "clean").mkdir()
        for name, els in spec.items():
            selfcheck(name, els, a)
            build(name, els, a, True).save(staged / f"{name}.png")
            build(name, els, a, False).save(staged / "clean" / f"{name}.png")
        if not BAD:
            (output / "clean").mkdir(parents=True, exist_ok=True)
            for name in spec:
                for sub in [Path(), Path("clean")]:
                    os.replace(
                        staged / sub / f"{name}.png", output / sub / f"{name}.png"
                    )
    if WARN:
        print("SELFCHECK WARNING (not a failure, check these rects by eye):")
        for w in sorted(set(WARN)):
            print("  ", *w)
    if BAD:
        print("SELFCHECK FAIL:")
        for b in sorted(set(BAD)):
            print("  ", *b)
        sys.exit(1)
    print("selfcheck ok,", len(spec), "images")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

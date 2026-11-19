#!/usr/bin/env python3
"""Build an annotated gallery with optional old/new comparison sliders.

usage: gallery.py --root DIR --meta meta.json [--title TITLE] [--lang en|pl]
DIR contains annotated/NAME.png and annotated/clean/NAME.png. Paired mode
also reads old/NAME.png and new/NAME.png with identical pixel dimensions.
"""

import argparse
import html
import json
import sys
from pathlib import Path

from PIL import Image
from common import screen_name

CSS = """:root{--bg:#fafaf7;--fg:#202a30;--mut:#617079;--line:#d8dcd7}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e6e8eb;--mut:#9aa0a6;--line:#3a3f46}}
*{box-sizing:border-box}body{background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif;margin:0;padding:clamp(16px,2.5vw,48px)}
img{display:block;max-width:100%;height:auto;border:1px solid var(--line)}
a{color:#427d73}h1,h2{letter-spacing:-.025em}section{margin:2rem 0 3rem}
table{border-collapse:collapse;width:100%}td,th{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
.table-wrap{overflow:auto}.mut{color:var(--mut)}.compare{position:relative;--split:50%;margin:1rem 0}
.compare img{width:100%;background:white}.compare .after{position:absolute;inset:0;clip-path:inset(0 calc(100% - var(--split)) 0 0)}
.compare .divider{position:absolute;top:0;bottom:0;left:var(--split);width:2px;background:#7b3ff2;pointer-events:none}
.compare .label{position:absolute;top:12px;background:#172d32;color:white;border-radius:5px;padding:4px 10px;font-size:.8rem}
.compare .label-new{left:12px}.compare .label-old{right:12px}.slider-label{display:flex;gap:1rem;align-items:center}
.slider-label input{flex:1;min-width:80px;accent-color:#7b3ff2}.slider-label output{min-width:3em}
details{margin:1rem 0}summary{cursor:pointer;font-weight:600}details img{margin-top:1rem}
@media print{.slider-label{display:none}.compare{display:none}details{display:block}details>img{display:block}}
"""
JS = """document.querySelectorAll('.compare-slider').forEach(slider=>{
  slider.addEventListener('input',()=>{
    document.getElementById(slider.dataset.target).style.setProperty('--split',slider.value+'%');
    slider.parentElement.querySelector('output').textContent=slider.value+'%';
  });
});"""
LABELS = {
    "en": [
        "New",
        "Old",
        "New version share",
        "Annotated changes",
        "Version without labels",
        "Change coverage",
        "Reference",
        "Subject",
        "Screen",
        "Image",
        "Note",
        "Not visible",
        "Not reached or not verified",
        "Presenter notes",
    ],
    "pl": [
        "Nowa",
        "Stara",
        "Udział nowej wersji",
        "Zaznaczone zmiany",
        "Wersja bez etykiet",
        "Pokrycie zmian",
        "Wersja / zmiana",
        "Temat",
        "Widok",
        "Obraz",
        "Uwagi",
        "Niewidoczne",
        "Nieosiągnięte lub niesprawdzone",
        "Uwagi do porównania",
    ],
}
e = html.escape


def comparison(root, name, mode, words, new_only=False):
    """Compare only matching captures; a wholly new view has no old image."""
    if mode != "paired":
        return ""
    old, new = root / "old" / f"{name}.png", root / "new" / f"{name}.png"
    if not new.is_file():
        raise ValueError(f"new capture is missing: {new}")
    if new_only:
        return ""
    if not old.is_file():
        raise ValueError(
            f"{name}: OLD capture is missing; declare new_only for a new view"
        )
    with Image.open(old) as before, Image.open(new) as after:
        if before.size != after.size:
            raise ValueError(
                f"{name}: comparison dimensions differ: {before.size} versus {after.size}"
            )
    n = e(name)
    return f'''<div class="compare" id="compare-{n}">
<img src="old/{n}.png" alt="{e(words[1])}: {n}" loading="lazy">
<img class="after" src="new/{n}.png" alt="{e(words[0])}: {n}" loading="lazy">
<span class="divider"></span><span class="label label-new">{e(words[0])}</span><span class="label label-old">{e(words[1])}</span>
</div><label class="slider-label">{e(words[2])}<input class="compare-slider" type="range" min="0" max="100" value="50" data-target="compare-{n}" aria-label="{e(words[2])}: {n}"><output>50%</output></label>
<p><a href="old/{n}.png">{e(words[1])}</a> · <a href="new/{n}.png">{e(words[0])}</a></p>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--meta", required=True, type=Path)
    parser.add_argument("--title", default="Visual diff")
    parser.add_argument("--lang", choices=LABELS, default="en")
    args = parser.parse_args()
    metadata = json.loads(args.meta.read_text(encoding="utf-8"))
    mode = metadata.get("mode", "new_only")
    if mode not in {"paired", "new_only"}:
        raise ValueError("mode must be paired or new_only")
    images = metadata.get("images", [])
    names = [screen_name(item["name"]) for item in images]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate screen name in gallery")
    for name in names:
        for subdir in [Path("annotated"), Path("annotated/clean")]:
            path = args.root / subdir / f"{name}.png"
            if not path.is_file():
                raise ValueError(f"image file is missing: {path}")
    for row in metadata.get("coverage", []):
        if not row.get("images") and not str(row.get("note", "")).strip():
            raise ValueError("coverage without images requires an explanatory note")
        for name in row.get("images", []):
            if name not in names:
                raise ValueError(f"coverage refers to an image not listed: {name}")
    words = LABELS[args.lang]
    output = [
        f'<!doctype html><html lang="{args.lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(args.title)}</title><style>{CSS}</style></head><body>',
        f"<h1>{e(args.title)}</h1><p>{e(metadata.get('intro', ''))}</p>",
    ]
    mode_texts = {
        "en": {
            "paired": "Paired OLD/NEW captures.",
            "new_only": "NEW-only. No old/new pixel comparison was performed.",
        },
        "pl": {
            "paired": "Zrzuty par STARA/NOWA.",
            "new_only": "Tylko NOWA wersja. Nie wykonano porównania pikseli ze STARĄ wersją.",
        },
    }[args.lang]
    key = {
        "en": "Green: new · Violet: changed · Red: removed",
        "pl": "Zielone: nowe · Fioletowe: zmienione · Czerwone: usunięte",
    }[args.lang]
    output.extend(
        [f'<p class="mut">{e(mode_texts[mode])}</p>', f'<p class="mut">{e(key)}</p>']
    )
    for item in images:
        name, title = e(item["name"]), e(item["title"])
        if "new_only" in item and type(item["new_only"]) is not bool:
            raise ValueError("new_only must be a boolean")
        pair = comparison(
            args.root, item["name"], mode, words, item.get("new_only", False)
        )
        output.append(f'<section id="{name}"><h2>{title}</h2>{pair}')
        if mode == "paired" and item.get("new_only", False):
            output.append(f'<p class="mut">{e(mode_texts["new_only"])}</p>')
        marked = f'<img src="annotated/{name}.png" alt="{title}" loading="lazy">'
        output.append(
            f"<details><summary>{e(words[3])}</summary>{marked}</details>"
            if pair
            else marked
        )
        output.append(
            f'<p><a href="annotated/clean/{name}.png">{e(words[4])}</a></p></section>'
        )
    output.append(f'<h2>{e(words[5])}</h2><div class="table-wrap"><table><thead><tr>')
    output.extend(f'<th scope="col">{e(label)}</th>' for label in words[6:11])
    output.append("</tr></thead><tbody>")
    for row in metadata.get("coverage", []):
        links = ", ".join(
            f'<a href="#{e(name)}">{e(name)}</a>' for name in row.get("images", [])
        )
        output.append(
            f"<tr><td><code>{e(row.get('reference', row.get('commit', '')))}</code></td><td>{e(row['subject'])}</td><td>{e(row.get('screen', ''))}</td><td>{links or e(words[11])}</td><td>{e(row.get('note', ''))}</td></tr>"
        )
    output.append("</tbody></table></div>")
    for key, title in [("not_reached", words[12]), ("presenter_notes", words[13])]:
        if metadata.get(key):
            output.append(
                f"<h2>{e(title)}</h2><ul>"
                + "".join(f"<li>{e(value)}</li>" for value in metadata[key])
                + "</ul>"
            )
    output.append(f"<script>{JS}</script></body></html>")
    destination = args.root / "index.html"
    destination.write_text("\n".join(output), encoding="utf-8")
    print(f"wrote {destination}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

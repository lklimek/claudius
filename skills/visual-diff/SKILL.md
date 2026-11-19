---
name: visual-diff
description: "This skill should be used when the user asks for a visual diff, annotated screenshots of UI changes, or a before/after gallery for web pages, reports, desktop apps, or supplied screenshots. It compares versions and presents evidence; it does not redesign the UI."
allowed-tools: Read, Write, Glob, Grep, Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/diff.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/render.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/gallery.py *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/selftest.py *)
---

# Visual Diff

Produce comparable captures, annotated images of the NEW version, clean spotlight variants, and an HTML gallery. Reuse supplied screenshots; otherwise capture with available browser or desktop tools. No application, repository, toolkit, network or build command is assumed.

Claude expands `${CLAUDE_PLUGIN_ROOT}` in commands below. Codex and other hosts resolve the installed absolute script paths from `allowed-tools`, or locate the plugin tree containing `scripts/visual-diff`. Never pass unresolved placeholders to a shell or resolve commands against the project checkout.

Requires Python 3, Pillow and NumPy (Debian/Ubuntu: `python3-pil`, `python3-numpy`). Scripts need no display; only capture needs browser/desktop tooling. Report missing dependencies without installing them implicitly.

## 1. Establish the comparison

Record OLD and NEW identities: commits, release tags, URLs, HTML files or screenshot directories. Choose an output directory outside source control. Read [references/artifact-contract.md](references/artifact-contract.md) for filenames and the spec/meta format.

- **Paired**: both versions are available. Use the same data, viewport/window size, zoom, pixel ratio, theme, locale, fonts, filters and navigation anchor. Match capture names. Record versions and capture settings in provenance; hash shared input when comparing generated reports.
- **NEW-only**: OLD cannot be captured. Annotate only changes supported by an inspected diff or other verifiable evidence. State that no old/new pixel comparison was performed; do not fabricate OLD captures. If neither OLD nor reliable change evidence exists, collect it before making change claims.

Use the documented project build/run procedure when a build is needed. When comparing repository revisions, apply `git-and-github` and map user-visible changes from the actual diff to the shot list. For supplied screenshots or generated files, use their identities and visible differences; no commit history is required.

## 2. Capture evidence

Store PNGs in `<OUT>/new/`; paired captures also go in `<OUT>/old/`. Screenshot coordinates are native image pixels, not CSS pixels unless capture uses device scale 1.

- Browser: use available browser automation; wait for fonts/data, disable animations and place both pages at the same element/anchor. A local HTTP server can expose generated files to browser tools that disallow `file:` URLs. Keep it limited to the requested artifacts.
- Desktop: use available desktop capture tooling; isolate each build's app data, match window geometry and capture the same state. Do not assume a display name, config directory or specific capture executable.
- Supplied captures: verify dimensions and provenance. Report mismatches; do not stretch images just to obtain a comparable pair.

Use isolated test data/profiles. Keep secrets out of every retained capture and caption. A request to compare screens does not authorize submitting forms or other external writes. Wait out loading banners, blinking cursors, clocks and transient notifications, or record unavoidable noise.

In paired mode run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/diff.py --new-dir <OUT>/new --old-dir <OUT>/old
```

Inspect differences rather than treating the changed-pixel count as proof of a defect. Newly added and removed views can lack a counterpart; describe that explicitly in coverage. Never silently resize, crop or replace the input to make a check pass.

## 3. Annotate the NEW captures

Write `<OUT>/spec.json`; every rectangle comes from its own capture. Preserve the spotlight style:

- Unchanged areas dimmed/desaturated; marked areas remain in full colour with tight rounded outlines.
- New = green, changed/moved/reworded/restyled = violet, removed = red. Name the verified change, not its unchanged surroundings.
- Short pill labels with leader lines; place them in free space, without hiding content or clipping labels. Use the user's language.
- Removed elements: dashed outline plus a crop from OLD labelled as previous, or the inset alone when an empty box would mislead. NEW-only cannot use OLD insets.
- Entirely new view: kind `screen`, no dimming and one outline. One annotated image per NEW view, rather than a combined before/after image.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/render.py <OUT>/spec.json --new-dir <OUT>/new --old-dir <OUT>/old --out-dir <OUT>/annotated --scale 2
```

Omit `--old-dir` in NEW-only mode. Use `--lang pl` for Polish inset/legend text; default `en`. Captions remain as supplied. Outputs include labelled images and `annotated/clean/` spotlight images without pills/insets.

## 4. Verify and present

The renderer rejects invalid rectangles, clipped pills, mismatched pair dimensions, and unchanged pixels inside a new/changed highlight. Subtle differences produce a warning: judge it visually. NEW-only has no pixel self-check. Fix the spec or recapture; never weaken checks to disguise a bad comparison.

Read every labelled image: correct state, accurate outline, legible label, no obscured content or secrets. Write `<OUT>/meta.json` mapping each user-visible change to images or an explicit reason it is not pictured. Record capture gaps and unavoidable data differences.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/gallery.py --root <OUT> --meta <OUT>/meta.json --title "Visual diff" --lang en
```

The gallery has comparison sliders for matched OLD/NEW captures and expandable annotations; NEW-only shows annotations directly. It works offline with relative image files and no external JS/CSS. Share the gallery and source versions, stating what was not verified. Keep generated artifacts out of the repository. After changing the bundled scripts, run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/visual-diff/selftest.py
```

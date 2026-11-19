# Visual diff artifacts

`OUT` is the chosen output directory:

```text
OUT/
  old/NAME.png                 paired mode; may lack a wholly new view
  new/NAME.png                 captured NEW views
  annotated/NAME.png           labelled spotlight images
  annotated/clean/NAME.png     spotlight images without pills/insets
  spec.json
  meta.json
  provenance.json              capture settings, identities, shared-input hash
  index.html
```

Names are filename stems such as `01-summary`, never paths. Coordinates are `[x0,y0,x1,y1]` in the native PNG, with exclusive end coordinates. All rectangles and inset destinations must fit their images. Paired images of one view must have identical dimensions.

Transparent PNGs are composited on white for pixel checks and annotations; the gallery uses the same background for raw comparisons. Annotation output and its `clean/` directory must differ from raw capture directories. Validation failures leave existing output images intact. Narrow images omit the embedded legend rather than clipping it; the gallery always explains the colours.

## spec.json

```json
{
  "01-summary": [
    {
      "kind": "changed",
      "rect": [40, 40, 200, 120],
      "label": "Changed: wider summary",
      "pill": [230, 40]
    }
  ]
}
```

Kinds: `new`, `changed`, `removed`, `screen`. The pill is a top-left point. For an OLD inset, add:

```json
{
  "inset": {
    "old": "01-summary",
    "crop": [40, 40, 180, 100],
    "xy": [230, 100]
  }
}
```

OLD name/crop identify the source; `xy` is the destination in NEW. Match coordinates to the actual screenshot, not this example. Render scale defaults to 2; accepted values are 1–4. The pixel diff reports all changed pixels, pixels above a small noise threshold and their bounding box. It does not auto-select semantic annotations.

## meta.json

```json
{
  "mode": "paired",
  "intro": "Version A and version B, same input and viewport.",
  "images": [{"name": "01-summary", "title": "Summary"}],
  "coverage": [{
    "reference": "A → B",
    "subject": "Wider summary layout",
    "screen": "Summary",
    "images": ["01-summary"]
  }],
  "not_reached": [],
  "presenter_notes": ["Capture: 1280 × 900 px; animations disabled."]
}
```

`mode`: `paired` or `new_only` (default, visibly disclosed). `reference` can name a commit, release, URL, file or change; `commit` is accepted as a legacy alias. A coverage row without images requires a nonempty `note` explaining why. Text is HTML-escaped. The gallery verifies both labelled/clean files and coverage references before writing `index.html`. Paired mode reads matching raw captures from `old/` and `new/` for the slider. A wholly new view without OLD must use `kind: "screen"` in its spec and `"new_only": true` on its image entry; otherwise missing OLD is an error.

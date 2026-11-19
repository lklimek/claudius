#!/usr/bin/env python3
"""Regression tests for render.py, diff.py and gallery.py on synthetic images.

usage: selftest.py
Needs no display, no application build and no captured data. Run it after
changing any script in this directory.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = (480, 240)
GREY = (128, 128, 128)
RECT = [40, 40, 120, 100]
PILL = [150, 40]


def image(path, *patches):
    """Grey image with (box, colour) patches painted on it."""
    img = Image.new("RGB", SIZE, GREY)
    d = ImageDraw.Draw(img)
    for box, colour in patches:
        d.rectangle(box, fill=colour)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


def run(script, *args):
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, script), *args],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout + r.stderr


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def path(self, *parts):
        return os.path.join(self.root, *parts)


class RenderSelfCheck(Case):
    def render(
        self,
        old_patch,
        new_patch,
        pill=PILL,
        old=True,
        inset=None,
        kind="changed",
        missing_old=False,
        output="out",
    ):
        image(self.path("old", "s.png"), *old_patch)
        image(self.path("new", "s.png"), *new_patch)
        if missing_old:
            os.unlink(self.path("old", "s.png"))
        el = {"kind": kind, "rect": RECT, "label": "Changed: x", "pill": pill}
        if inset:
            el["inset"] = inset
        with open(self.path("spec.json"), "w") as f:
            json.dump({"s": [el]}, f)
        old_args = ["--old-dir", self.path("old")] if old else []
        return run(
            "render.py",
            self.path("spec.json"),
            "--new-dir",
            self.path("new"),
            *old_args,
            "--out-dir",
            self.path(output),
        )

    def test_identical_rect_fails(self):
        code, out = self.render([], [])
        self.assertEqual(code, 1, out)
        self.assertIn("rect identical in old and new", out)

    def test_missing_old_is_not_silently_accepted(self):
        code, out = self.render([], [(RECT, (255, 255, 255))], missing_old=True)
        self.assertNotEqual(code, 0, out)
        self.assertIn("OLD capture is missing", out)

    def test_explicit_new_screen_needs_no_old_counterpart(self):
        code, out = self.render([], [], missing_old=True, kind="screen")
        self.assertEqual(code, 0, out)

    def test_failure_preserves_existing_output(self):
        image(self.path("out", "s.png"), (RECT, (255, 0, 0)))
        with open(self.path("out", "s.png"), "rb") as f:
            original = f.read()
        code, out = self.render([], [])
        self.assertNotEqual(code, 0, out)
        with open(self.path("out", "s.png"), "rb") as f:
            self.assertEqual(f.read(), original)

    def test_output_cannot_overwrite_raw_captures(self):
        code, out = self.render([], [(RECT, (255, 255, 255))], output="new")
        self.assertNotEqual(code, 0, out)
        self.assertIn("raw captures", out)

    def test_clean_symlink_cannot_overwrite_raw_captures(self):
        os.makedirs(self.path("out"))
        os.makedirs(self.path("new"))
        try:
            os.symlink(
                self.path("new"), self.path("out", "clean"), target_is_directory=True
            )
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        code, out = self.render([], [(RECT, (255, 255, 255))])
        self.assertNotEqual(code, 0, out)
        self.assertIn("raw captures", out)

    def test_colour_change_of_equal_brightness_passes_silently(self):
        # (255, 0, 0) and (0, 130, 0) have the same grey level.
        code, out = self.render([(RECT, (255, 0, 0))], [(RECT, (0, 130, 0))])
        self.assertEqual(code, 0, out)
        self.assertNotIn("WARNING", out)
        self.assertNotIn("FAIL", out)

    def test_low_contrast_change_warns_but_passes(self):
        code, out = self.render([], [(RECT, (140, 140, 140))])
        self.assertEqual(code, 0, out)
        self.assertIn("SELFCHECK WARNING", out)
        self.assertIn("rect barely differs", out)

    def test_small_changed_region_warns_but_passes(self):
        code, out = self.render([], [([50, 50, 52, 52], (255, 255, 255))])
        self.assertEqual(code, 0, out)
        self.assertIn("rect barely differs", out)

    def test_pill_outside_image_fails(self):
        code, out = self.render([], [(RECT, (255, 255, 255))], pill=[470, 40])
        self.assertEqual(code, 1, out)
        self.assertIn("pill outside image", out)

    def test_passing_run_writes_both_variants(self):
        code, out = self.render([], [(RECT, (255, 255, 255))])
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(self.path("out", "s.png")))
        self.assertTrue(os.path.exists(self.path("out", "clean", "s.png")))

    def test_new_only_mode_skips_the_selfcheck(self):
        code, out = self.render([], [], old=False)
        self.assertEqual(code, 0, out)
        self.assertIn("NEW-only mode", out)
        self.assertTrue(os.path.exists(self.path("out", "s.png")))
        self.assertTrue(os.path.exists(self.path("out", "clean", "s.png")))

    def test_new_only_mode_refuses_an_inset(self):
        inset = {"old": "s", "crop": [0, 0, 20, 20], "xy": [300, 150]}
        code, out = self.render([], [], old=False, inset=inset)
        self.assertEqual(code, 1, out)
        self.assertIn("inset needs --old-dir", out)

    def test_mismatched_pair_dimensions_fail(self):
        image(self.path("old", "s.png"))
        Image.new("RGB", (200, 200), "white").save(self.path("old", "s.png"))
        image(self.path("new", "s.png"))
        with open(self.path("spec.json"), "w") as f:
            json.dump(
                {
                    "s": [
                        {
                            "kind": "changed",
                            "rect": RECT,
                            "label": "Changed",
                            "pill": PILL,
                        }
                    ]
                },
                f,
            )
        code, out = run(
            "render.py",
            self.path("spec.json"),
            "--old-dir",
            self.path("old"),
            "--new-dir",
            self.path("new"),
            "--out-dir",
            self.path("out"),
        )
        self.assertNotEqual(code, 0, out)
        self.assertIn("dimensions", out)

    def test_outside_rect_fails_without_writing_images(self):
        image(self.path("new", "s.png"))
        with open(self.path("spec.json"), "w") as f:
            json.dump(
                {
                    "s": [
                        {
                            "kind": "changed",
                            "rect": [-10, 10, 100, 100],
                            "label": "Changed",
                            "pill": PILL,
                        }
                    ]
                },
                f,
            )
        code, out = run(
            "render.py",
            self.path("spec.json"),
            "--new-dir",
            self.path("new"),
            "--out-dir",
            self.path("out"),
        )
        self.assertNotEqual(code, 0, out)
        self.assertIn("rect", out)
        self.assertFalse(os.path.exists(self.path("out", "s.png")))

    def test_relative_path_screen_name_is_rejected(self):
        image(self.path("new", "s.png"))
        with open(self.path("spec.json"), "w") as f:
            json.dump({"../escape": []}, f)
        code, out = run(
            "render.py",
            self.path("spec.json"),
            "--new-dir",
            self.path("new"),
            "--out-dir",
            self.path("out"),
        )
        self.assertNotEqual(code, 0, out)
        self.assertIn("screen name", out)


class Diff(Case):
    def diff(self):
        code, out = run(
            "diff.py", "--new-dir", self.path("new"), "--old-dir", self.path("old")
        )
        self.assertEqual(code, 0, out)
        return out.splitlines()

    def test_reports_screens_of_one_build_only(self):
        image(self.path("old", "gone.png"))
        image(self.path("new", "added.png"))
        self.assertEqual(self.diff(), ["added.png NEW ONLY", "gone.png OLD ONLY"])

    def test_subtle_change_is_not_reported_as_identical(self):
        image(self.path("old", "s.png"), (RECT, (100, 100, 100)))
        image(self.path("new", "s.png"), (RECT, (112, 112, 112)))
        pixels = (RECT[2] - RECT[0] + 1) * (RECT[3] - RECT[1] + 1)
        self.assertEqual(
            self.diff(),
            [f"s.png changed={pixels} above_noise=0 bbox=(40, 40, 121, 101)"],
        )

    def test_box_follows_the_pixels_above_noise(self):
        image(self.path("old", "s.png"))
        image(
            self.path("new", "s.png"),
            (RECT, (130, 130, 130)),
            ([300, 150, 309, 159], (255, 255, 255)),
        )
        (line,) = self.diff()
        self.assertIn("above_noise=100 bbox=(300, 150, 310, 160)", line)

    def test_identical_captures(self):
        image(self.path("old", "s.png"))
        image(self.path("new", "s.png"))
        self.assertEqual(self.diff(), ["s.png identical"])

    def test_alpha_changes_are_visible_and_hidden_rgb_is_ignored(self):
        image(self.path("old", "s.png"))
        image(self.path("new", "s.png"))
        Image.new("RGBA", SIZE, (255, 0, 0, 0)).save(self.path("old", "s.png"))
        Image.new("RGBA", SIZE, (255, 0, 0, 255)).save(self.path("new", "s.png"))
        self.assertNotIn("identical", self.diff()[0])
        Image.new("RGBA", SIZE, (0, 255, 0, 0)).save(self.path("new", "s.png"))
        self.assertEqual(self.diff(), ["s.png identical"])

    def test_single_pixel_box_is_nonempty_with_exclusive_end(self):
        image(self.path("old", "s.png"))
        image(self.path("new", "s.png"), ([40, 40, 40, 40], (255, 255, 255)))
        self.assertIn("bbox=(40, 40, 41, 41)", self.diff()[0])


class Gallery(Case):
    def gallery(self, meta, files):
        for f in files:
            image(self.path(*f))
        with open(self.path("meta.json"), "w") as f:
            json.dump(meta, f)
        return run("gallery.py", "--root", self.root, "--meta", self.path("meta.json"))

    META = {"images": [{"name": "01-a", "title": "A"}], "coverage": []}
    BOTH = [("annotated", "01-a.png"), ("annotated", "clean", "01-a.png")]

    def test_complete_gallery_is_written(self):
        code, out = self.gallery(self.META, self.BOTH)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(self.path("index.html")))

    def test_missing_labelled_image_stops_the_gallery(self):
        code, out = self.gallery(self.META, self.BOTH[1:])
        self.assertNotEqual(code, 0, out)
        self.assertIn("image file is missing", out)
        self.assertFalse(os.path.exists(self.path("index.html")))

    def test_missing_clean_image_stops_the_gallery(self):
        code, out = self.gallery(self.META, self.BOTH[:1])
        self.assertNotEqual(code, 0, out)
        self.assertIn("image file is missing", out)
        self.assertFalse(os.path.exists(self.path("index.html")))

    def test_coverage_of_an_unlisted_image_stops_the_gallery(self):
        meta = dict(
            self.META, coverage=[{"commit": "abc", "subject": "s", "images": ["02-b"]}]
        )
        code, out = self.gallery(meta, self.BOTH)
        self.assertNotEqual(code, 0, out)
        self.assertIn("not listed", out)

    def test_paired_gallery_has_accessible_comparison_control(self):
        meta = dict(self.META, mode="paired")
        files = self.BOTH + [("old", "01-a.png"), ("new", "01-a.png")]
        code, out = self.gallery(meta, files)
        self.assertEqual(code, 0, out)

        class Controls(HTMLParser):
            def __init__(self):
                super().__init__()
                self.sliders = []
                self.sources = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "input" and attrs.get("type") == "range":
                    self.sliders.append(attrs)
                if tag == "img":
                    self.sources.append(attrs.get("src"))

        parser = Controls()
        with open(self.path("index.html")) as f:
            parser.feed(f.read())
        self.assertEqual(len(parser.sliders), 1)
        self.assertTrue(parser.sliders[0].get("aria-label"))
        self.assertIn("old/01-a.png", parser.sources)
        self.assertIn("new/01-a.png", parser.sources)

    def test_paired_gallery_requires_old_unless_view_is_explicitly_new(self):
        meta = dict(self.META, mode="paired")
        files = self.BOTH + [("new", "01-a.png")]
        code, out = self.gallery(meta, files)
        self.assertNotEqual(code, 0, out)
        self.assertIn("OLD capture is missing", out)
        meta = dict(meta, images=[dict(self.META["images"][0], new_only=True)])
        code, out = self.gallery(meta, files)
        self.assertEqual(code, 0, out)
        with open(self.path("index.html")) as f:
            self.assertIn("No old/new pixel comparison", f.read())

    def test_unpictured_coverage_requires_a_reason(self):
        meta = dict(
            self.META,
            coverage=[{"reference": "A → B", "subject": "Backend", "images": []}],
        )
        code, out = self.gallery(meta, self.BOTH)
        self.assertNotEqual(code, 0, out)
        self.assertIn("note", out)

    def test_new_only_gallery_discloses_absent_pixel_comparison(self):
        code, out = self.gallery(self.META, self.BOTH)
        self.assertEqual(code, 0, out)
        with open(self.path("index.html")) as f:
            self.assertIn("No old/new pixel comparison", f.read())

    def test_non_git_reference_and_labels_are_escaped(self):
        meta = dict(
            self.META,
            intro="<script>bad()</script>",
            coverage=[
                {"reference": "v1 → v2", "subject": "<b>theme</b>", "images": ["01-a"]}
            ],
        )
        code, out = self.gallery(meta, self.BOTH)
        self.assertEqual(code, 0, out)
        with open(self.path("index.html")) as f:
            html = f.read()
        self.assertIn("v1 → v2", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()", html)

    def test_unsafe_name_is_rejected_before_reading_assets(self):
        code, out = self.gallery({"images": [{"name": "../escape", "title": "x"}]}, [])
        self.assertNotEqual(code, 0, out)
        self.assertIn("screen name", out)

    def test_paired_gallery_refuses_different_dimensions(self):
        files = self.BOTH + [("old", "01-a.png"), ("new", "01-a.png")]
        for f in files:
            image(self.path(*f))
        Image.new("RGB", (240, 120), "white").save(self.path("old", "01-a.png"))
        with open(self.path("meta.json"), "w") as f:
            json.dump(dict(self.META, mode="paired"), f)
        code, out = run(
            "gallery.py", "--root", self.root, "--meta", self.path("meta.json")
        )
        self.assertNotEqual(code, 0, out)
        self.assertIn("dimensions", out)


if __name__ == "__main__":
    unittest.main()

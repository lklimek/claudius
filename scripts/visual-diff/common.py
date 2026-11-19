"""Input checks shared by the visual-diff command-line tools."""

import re
from PIL import Image


def capture(path):
    """Composite transparent captures on white for comparison and annotation."""
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        return background.convert("RGB")


def screen_name(name):
    """Require a filename stem, never an absolute or relative path."""
    if not isinstance(name, str) or not re.fullmatch(r"[\w][\w.-]*", name):
        raise ValueError(f"Invalid screen name: {name!r}; use a filename stem")
    return name


def rect(value, size, label="rect"):
    """Require a nonempty pixel rectangle inside its own source image."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(x) is not int for x in value)
    ):
        raise ValueError(f"{label}: expected four integer coordinates")
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
        raise ValueError(f"{label}: {value} is outside image dimensions {size}")
    return value

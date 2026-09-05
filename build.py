"""Static site generator for Carl's Comics.

Reads one JSON file per comic from comic/meta/, processes the matching source
image from comic/published/, and writes a complete static site into docs/.

Nothing in docs/ should ever be edited by hand -- every build overwrites it.

Run it with:    .venv/bin/python build.py
"""

import json
import shutil
from datetime import date, datetime
from pathlib import Path

from PIL import Image
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ── Paths ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent
META_DIR = ROOT / "comic" / "meta"
SOURCE_DIR = ROOT / "comic" / "published"
TEMPLATE_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"

OUT = ROOT / "docs"
OUT_IMAGES = OUT / "images"

DOMAIN = "carlscomics.com"

# ── Image settings ─────────────────────────────────────────────────────────

# Each comic gets three widths. The originals in comic/published/ are the
# master copies and are never modified.
FULL_WIDTH = 2400      # "view it big" version
DISPLAY_WIDTH = 1280   # what the comic page shows (2x the 640px CSS width)
THUMB_WIDTH = 560      # the cropped quadrant in the archive gallery

WEBP_QUALITY = 82
JPEG_QUALITY = 86

# The gap between panels is not always exactly at the halfway line, so a
# quadrant crop is pulled in slightly on the two edges that meet the divider.
# The other two edges are the border of the image itself and stay put, which
# keeps artwork and lettering near the outside of a panel intact.
QUADRANT_INSET = 0.015

QUADRANTS = ("top-left", "top-right", "bottom-left", "bottom-right")


def crop_quadrant(image, quadrant):
    """Return one quarter of a four-panel comic, inset slightly from its edges."""
    if quadrant not in QUADRANTS:
        raise ValueError(
            f"thumb_quadrant must be one of {QUADRANTS}, got {quadrant!r}"
        )

    width, height = image.size
    mid_x, mid_y = width // 2, height // 2

    is_left = quadrant.endswith("left")
    is_top = quadrant.startswith("top")

    left, right = (0, mid_x) if is_left else (mid_x, width)
    top, bottom = (0, mid_y) if is_top else (mid_y, height)

    inset_x = int((right - left) * QUADRANT_INSET)
    inset_y = int((bottom - top) * QUADRANT_INSET)

    return image.crop(
        (
            left + (0 if is_left else inset_x),
            top + (0 if is_top else inset_y),
            right - (inset_x if is_left else 0),
            bottom - (inset_y if is_top else 0),
        )
    )


def resize_to_width(image, target_width):
    """Shrink an image to target_width, keeping its proportions. Never enlarges."""
    if image.width <= target_width:
        return image.copy()
    target_height = round(image.height * target_width / image.width)
    return image.resize((target_width, target_height), Image.LANCZOS)


def write_variant(image, stem, source_mtime):
    """Write one image as both WebP and JPEG. Returns the info the templates need."""
    webp_path = OUT_IMAGES / f"{stem}.webp"
    jpg_path = OUT_IMAGES / f"{stem}.jpg"

    up_to_date = (
        webp_path.exists()
        and jpg_path.exists()
        and webp_path.stat().st_mtime >= source_mtime
        and jpg_path.stat().st_mtime >= source_mtime
    )

    if not up_to_date:
        image.save(webp_path, "WEBP", quality=WEBP_QUALITY, method=6)
        image.convert("RGB").save(
            jpg_path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True
        )
        print(f"    wrote {webp_path.name} and {jpg_path.name}")

    return {
        "webp": f"/images/{webp_path.name}",
        "jpg": f"/images/{jpg_path.name}",
        "width": image.width,
        "height": image.height,
    }


def process_images(meta):
    """Generate full, display and thumbnail variants for one comic."""
    source_path = SOURCE_DIR / meta["image"]
    if not source_path.exists():
        raise FileNotFoundError(
            f"{meta['image']} is listed in comic/meta/{meta['number']:04d}.json "
            f"but is not in comic/published/"
        )

    source_mtime = source_path.stat().st_mtime
    stem = f"{meta['number']:04d}"

    with Image.open(source_path) as original:
        original.load()
        return {
            "full": write_variant(
                resize_to_width(original, FULL_WIDTH), f"{stem}-full", source_mtime
            ),
            "display": write_variant(
                resize_to_width(original, DISPLAY_WIDTH),
                f"{stem}-display",
                source_mtime,
            ),
            "thumb": write_variant(
                resize_to_width(
                    crop_quadrant(original, meta["thumb_quadrant"]), THUMB_WIDTH
                ),
                f"{stem}-thumb",
                source_mtime,
            ),
        }


def load_comics():
    """Read every metadata file, process its images, and return them in order."""
    meta_files = sorted(META_DIR.glob("*.json"))
    if not meta_files:
        raise SystemExit("No comics found in comic/meta/ -- nothing to build.")

    comics = []
    for path in meta_files:
        meta = json.loads(path.read_text())
        print(f"  #{meta['number']:04d} {meta['title']}")

        published = datetime.strptime(meta["date"], "%Y-%m-%d").date()
        comic = dict(meta)
        comic["url"] = f"/comics/{meta['number']:04d}/"
        comic["date_display"] = published.strftime("%-d %B %Y")
        comic.update(process_images(meta))
        comics.append(comic)

    comics.sort(key=lambda c: c["number"])
    return comics


def write_page(path, html):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)


def main():
    OUT_IMAGES.mkdir(parents=True, exist_ok=True)

    print("Processing comics...")
    comics = load_comics()

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    shared = {"year": date.today().year}

    print("Rendering pages...")
    comic_template = env.get_template("comic.html")

    for index, comic in enumerate(comics):
        page = comic_template.render(
            comic=comic,
            prev=comics[index - 1] if index > 0 else None,
            next=comics[index + 1] if index < len(comics) - 1 else None,
            **shared,
        )
        write_page(OUT / "comics" / f"{comic['number']:04d}" / "index.html", page)

        # The homepage is the newest comic.
        if index == len(comics) - 1:
            write_page(OUT / "index.html", page)

    write_page(
        OUT / "archive" / "index.html",
        env.get_template("archive.html").render(comics=comics, **shared),
    )

    print("Copying static files...")
    shutil.copytree(STATIC_DIR, OUT / "static", dirs_exist_ok=True)

    # GitHub Pages needs CNAME in the folder it serves, and .nojekyll stops it
    # from running the files through Jekyll first.
    (OUT / "CNAME").write_text(DOMAIN + "\n")
    (OUT / ".nojekyll").write_text("")

    print(f"\nBuilt {len(comics)} comic(s) into {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()

# Carl's Comics

Source for [carlscomics.com](https://carlscomics.com) — a webcomic by Layla.

## Stack

- **HTML + CSS**: hand-written, no frameworks
- **Python + Jinja2 + Pillow**: static site generator (`build.py`)
- **GitHub Pages**: hosting, serving the `docs/` folder
- **Cloudflare**: DNS

Jinja2 and Pillow run locally at build time only. Nothing but static HTML, CSS and images is ever served to a visitor.

## Setup (once)

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Build and preview

```
.venv/bin/python build.py
cd docs && python3 -m http.server 8765
```

Then open <http://localhost:8765/>.

The site uses root-relative links (`/archive/`, `/static/style.css`), so it must be previewed locally.

## Repo structure

```
comic/
  drafts/          # new art lands here unprocessed
  published/       # source images, numbered and sequenced
  meta/            # one .json per comic
templates/         # Jinja2 HTML templates
static/            # CSS, JS
docs/              # BUILD OUTPUT
build.py           # the generator
tmp/               # scratch space for dropping files (e.g. logo art) — gitignored
```

## Adding a comic

1. Put the finished comic in `comic/published/` as `NNNN_slug.png`.
2. Copy an existing file in `comic/meta/` to `NNNN.json` and fill it in:

   | field            | what it is                                              |
   | ---------------- | ------------------------------------------------------- |
   | `number`         | comic number, matches the filename                       |
   | `slug`           | short url-safe name                                      |
   | `title`          | shown under the comic and on the archive plaque          |
   | `date`           | `YYYY-MM-DD`                                             |
   | `image`          | filename inside `comic/published/`                       |
   | `characters`     | list of names                                            |
   | `tags`           | list of tags                                             |
   | `alt`            | written description of all four panels — _(Optional)_   |

3. Run the build, preview it, then commit and push.

`build.py` skips reprocessing a comic's images if both the source image and its
metadata JSON are older than the last build output — editing a comic's title,
date, or which image it points to all correctly trigger a rebuild for that one
comic. At current comic counts a full rebuild from scratch takes well under ten
seconds either way.

## Updating an existing comic

Edit the fields in that comic's `comic/meta/NNNN.json` (see the table above),
then rebuild:

```
.venv/bin/python build.py
```

No other file needs to change for a title, date, tag, or alt-text edit.

**Renumbering or swapping a comic's image.** If you change a comic's `number`
or point it at a different file in `comic/published/`, keep the filenames in
sync so the project stays easy to navigate by eye:

- Rename `comic/meta/NNNN.json` itself to match the new number.
- Rename the file in `comic/published/` so its `NNNN_` prefix matches too.

Neither rename is required by the code — `build.py` always uses the `number`
field inside the JSON, never the filename, to decide what a comic is and
where its pages/images go. But mismatched filenames make the repo confusing
to work in later, so keep them matching by convention.

**If a page looks stale after an edit** — shows the wrong comic's art, or
looks unchanged after you changed something — force a full clean rebuild
rather than trying to figure out what didn't get regenerated:

```
rm -rf docs/images docs/comics
.venv/bin/python build.py
```

This is cheap (a few seconds even with a couple dozen comics) and guarantees
every page and image genuinely reflects current `comic/meta/` and
`comic/published/`, rather than a stale cached file with the same name.

## Updating the About page

The About page is `templates/about.html` — a plain Jinja2 template, not
generated from metadata, so edit it directly:

- **Text**: the `<h2>About</h2>` heading and the `<p>Coming soon.</p>`
  paragraph inside `<section class="archive-intro">`. Add more `<p>` tags for
  additional paragraphs.
- **Image**: replace `static/about-placeholder.png` with a real image (same
  filename, or update the `src` in the template to match a new one). Update
  the `width`/`height` attributes on the `<img>` tag to the new image's actual
  pixel dimensions, and write real `alt` text describing it — the current
  empty `alt=""` is correct only because the placeholder is purely decorative
  and redundant with the "Coming soon" text next to it.

Then rebuild and preview as usual.

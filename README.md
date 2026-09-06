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

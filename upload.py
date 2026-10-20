"""Local upload page for Carl's Comics.

Runs a small web server on this Mac only (127.0.0.1). It is never deployed --
nothing in docs/ links to it, and build.py never copies it anywhere.

    /upload        drag-and-drop form, plus every comic saved but not published
    everything     else is the built site from docs/, with a "Back to upload" bar

Save puts the image in comic/published/, writes comic/meta/NNNN.json, and runs
build.py. Publish commits that comic plus docs/ and pushes; Discard deletes it
and rebuilds. They are separate steps on purpose: look at the preview first.

Run it with:    .venv/bin/python upload.py
Then open:      http://127.0.0.1:8766/upload
"""

import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image
from jinja2 import Environment, FileSystemLoader, select_autoescape

# ── Paths and settings ─────────────────────────────────────────────────────

ROOT = Path(__file__).parent
META_DIR = ROOT / "comic" / "meta"
SOURCE_DIR = ROOT / "comic" / "published"
TEMPLATE_DIR = ROOT / "templates"
DOCS = ROOT / "docs"

HOST = "127.0.0.1"   # this machine only -- never change to 0.0.0.0
PORT = 8766
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
FORMATS = {"JPEG": ".jpg", "PNG": ".png"}

# Every existing comic follows these, so new ones do too.
SLUG_PREFIX = "carl-"
CHARACTERS = ["Carl"]
STANDING_TAGS = ["cockatiel"]

# Embedded image metadata that could identify the artist. CLAUDE.md: never
# commit original files containing personal metadata.
EXIF_ARTIST, EXIF_COPYRIGHT, EXIF_GPS = 0x013B, 0x8298, 0x8825
XMP_PERSONAL = ("dc:creator", "photoshop:AuthorsPosition", "xmpRights:Owner")


class UploadError(Exception):
    """A problem with the submitted comic, shown to the user as-is."""


# ── Comic logic ────────────────────────────────────────────────────────────

def existing_numbers():
    return sorted(json.loads(p.read_text())["number"] for p in META_DIR.glob("*.json"))


def make_slug(title):
    """'What's Up, Carl?' -> 'carl-whats-up-carl'. Empty if nothing usable."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    words = re.sub(r"['’]", "", ascii_title.lower())
    core = re.sub(r"[^a-z0-9]+", "-", words).strip("-")
    if not core:
        return ""
    # Don't double up when the title itself starts with "Carl".
    return core if core.startswith(SLUG_PREFIX) else SLUG_PREFIX + core


def parse_number(text):
    try:
        number = int(text)
    except ValueError:
        raise UploadError("Comic number must be a whole number.")
    if number < 1:
        raise UploadError("Comic number must be 1 or higher.")
    return number


def personal_metadata(image):
    """Return a list of identifying metadata fields found in the image."""
    found = []
    exif = image.getexif()
    if exif.get(EXIF_ARTIST):
        found.append(f"EXIF Artist ({exif[EXIF_ARTIST]!r})")
    if exif.get(EXIF_COPYRIGHT):
        found.append(f"EXIF Copyright ({exif[EXIF_COPYRIGHT]!r})")
    if EXIF_GPS in exif:
        found.append("EXIF GPS location")

    xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp") or ""
    if isinstance(xmp, bytes):
        xmp = xmp.decode("utf-8", "replace")
    found += [f"XMP {field}" for field in XMP_PERSONAL if field in xmp]
    return found


def save_comic(fields, data):
    """Validate one upload, write its image and metadata, and run the build."""
    number = parse_number(fields.get("number", ""))
    if number in existing_numbers():
        raise UploadError(f"Comic #{number} already exists.")

    title = fields.get("title", "").strip()
    if not title:
        raise UploadError("Title is required.")
    slug = make_slug(title)
    if not slug:
        raise UploadError("The title needs at least one letter or number.")

    # Go by what the file actually is, not what its name claims.
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            extension = FORMATS.get(image.format)
            found = personal_metadata(image)
    except Exception:
        raise UploadError("That file isn't a readable image.")
    if not extension:
        raise UploadError("Image must be a JPEG or PNG.")
    if found:
        raise UploadError(
            "This image has identifying metadata embedded in it: "
            + ", ".join(found)
            + ". Re-export it without metadata and try again."
        )

    image_name = f"{number:04d}_{slug}{extension}"
    image_path = SOURCE_DIR / image_name
    meta_path = META_DIR / f"{number:04d}.json"
    if image_path.exists() or meta_path.exists():
        raise UploadError(f"{image_name} or {meta_path.name} already exists.")

    meta = {
        "number": number,
        "slug": slug,
        "title": title,
        "date": date.today().isoformat(),
        "image": image_name,
        "characters": CHARACTERS,
        "tags": [title.lower(), *STANDING_TAGS],
    }

    image_path.write_bytes(data)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    build = run([sys.executable, "build.py"])
    if build.returncode != 0:
        # Undo, so a failed upload leaves comic/ exactly as it was.
        image_path.unlink()
        meta_path.unlink()
        raise UploadError("The build failed, so the upload was undone.\n\n" + build.stdout)

    return {"number": number, "url": f"/comics/{number:04d}/", "log": build.stdout}


def pending_comics():
    """Comics saved here but not committed yet, i.e. their meta file is untracked.

    Asking git rather than remembering in the browser means the list survives
    navigating away, refreshing, or restarting this server.
    """
    tracked = set(run(["git", "ls-files", "--", str(META_DIR.relative_to(ROOT))]).stdout.split())
    pending = []
    for path in sorted(META_DIR.glob("*.json")):
        if str(path.relative_to(ROOT)) not in tracked:
            meta = json.loads(path.read_text())
            meta["url"] = f"/comics/{meta['number']:04d}/"
            pending.append(meta)
    return pending


def find_pending(fields):
    number = parse_number(fields.get("number", ""))
    for meta in pending_comics():
        if meta["number"] == number:
            return meta
    raise UploadError(f"Comic #{number} isn't an unpublished comic.")


def discard_comic(fields):
    """Delete an unpublished comic's files and its generated pages, then rebuild."""
    meta = find_pending(fields)
    stem = f"{meta['number']:04d}"

    (META_DIR / f"{stem}.json").unlink()
    (SOURCE_DIR / meta["image"]).unlink(missing_ok=True)
    # build.py never deletes old output, so remove this comic's pages and images
    # by hand; the rebuild then fixes the homepage, archive and prev/next links.
    shutil.rmtree(DOCS / "comics" / stem, ignore_errors=True)
    for image in (DOCS / "images").glob(f"{stem}-*"):
        image.unlink()

    build = run([sys.executable, "build.py"])
    if build.returncode != 0:
        raise UploadError(f"Comic #{meta['number']} was removed, but the rebuild failed.\n\n"
                          + build.stdout)
    return {"number": meta["number"]}


def publish_comic(fields):
    """Commit one saved comic plus the rebuilt docs/, then push."""
    meta = find_pending(fields)
    number = meta["number"]
    others = [m["number"] for m in pending_comics() if m["number"] != number]
    if others:
        # docs/ is committed whole, so it would carry the other comics' pages
        # live without their source files.
        raise UploadError("Publish or discard the other unpublished comics first: "
                          + ", ".join(f"#{n}" for n in others))
    meta_path = META_DIR / f"{number:04d}.json"

    # Only this comic's files and the build output -- never `git add -A`,
    # which would sweep in whatever else happens to be lying around.
    paths = [str(meta_path.relative_to(ROOT)),
             str((SOURCE_DIR / meta["image"]).relative_to(ROOT)),
             "docs"]
    log = ""
    for command in (["git", "add", "--", *paths],
                    ["git", "commit", "-m", f"Add comic #{number}: {meta['title']}", "--", *paths],
                    ["git", "push"]):
        result = run(command)
        log += f"$ {' '.join(command)}\n{result.stdout}\n"
        if result.returncode != 0:
            raise UploadError("Publishing stopped at a failed step.\n\n" + log)
    return {"log": log}


def run(command):
    """Run a command in the repo, with its output and errors merged into one log."""
    return subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)


# ── Web server ─────────────────────────────────────────────────────────────

env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self.host_allowed():
            return self.send_error(403)
        url = urlparse(self.path)
        if url.path in ("/upload", "/upload/"):
            numbers = existing_numbers()
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            page = env.from_string(UPLOAD_PAGE).render(
                next_number=(max(numbers) + 1) if numbers else 1,
                pending=pending_comics(),
                done=query,
                year=date.today().year,
            )
            return self.send_body(200, "text/html; charset=utf-8", page.encode())
        if url.path == "/upload/api/slug":
            title = parse_qs(url.query).get("title", [""])[0]
            return self.send_json(200, {"slug": make_slug(title)})

        # The built site, from docs/. Site pages get a preview bar added on
        # the way out -- never written into docs/, so it can't go live.
        file = Path(self.translate_path(self.path))
        if file.is_dir() and url.path.endswith("/"):
            file = file / "index.html"
        if file.suffix == ".html" and file.is_file():
            html = file.read_text().replace("</body>", PREVIEW_BAR + "</body>", 1)
            return self.send_body(200, "text/html; charset=utf-8", html.encode())
        return super().do_GET()

    def do_POST(self):
        # Requests must come from this page, not from some other site open in
        # the browser -- browsers always send Origin on a cross-site POST.
        if not self.host_allowed() or self.headers.get("Origin") not in {
                f"http://{h}" for h in ALLOWED_HOSTS}:
            return self.send_error(403)

        url = urlparse(self.path)
        fields = {k: v[0] for k, v in parse_qs(url.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            return self.send_json(413, {"error": "File is too large."})
        body = self.rfile.read(length)

        try:
            if url.path == "/upload/api/save":
                return self.send_json(200, save_comic(fields, body))
            if url.path == "/upload/api/publish":
                return self.send_json(200, publish_comic(fields))
            if url.path == "/upload/api/discard":
                return self.send_json(200, discard_comic(fields))
        except UploadError as error:
            return self.send_json(400, {"error": str(error)})
        self.send_error(404)

    def host_allowed(self):
        # Blocks DNS-rebinding: a hostile domain pointed at 127.0.0.1 still
        # sends its own name in the Host header.
        return self.headers.get("Host") in ALLOWED_HOSTS

    def send_json(self, status, payload):
        self.send_body(status, "application/json", json.dumps(payload).encode())

    def send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


# Added to every site page this server previews, so there's always a way back.
# Inline styles only, reusing colours and fonts from style.css.
PREVIEW_BAR = """
  <div style="position: sticky; bottom: 0; z-index: 100; background: #2e2e2e;
              border-top: 2px solid #f5c200; padding: 10px 20px; text-align: center;
              font-family: 'Caveat', cursive; font-size: 1.3rem; color: #eeeeee;">
    Local preview &middot;
    <a href="/upload" style="color: #f07830; text-decoration: none;">&larr; Back to upload</a>
  </div>
"""


# Extends the site's own base.html, so header, nav, footer and style.css match
# the live site. Kept here rather than in templates/ so build.py can never
# publish it. The form rules below only reuse colours and fonts from style.css,
# which has no form styles of its own.
UPLOAD_PAGE = """{% extends "base.html" %}

{% block title %}Upload &mdash; Carl's Comics{% endblock %}

{% block content %}
  <style>
    .upload { width: 100%; max-width: 640px; display: flex; flex-direction: column; gap: 20px; }
    #drop {
      background: #f8f2e2; padding: 32px 20px; text-align: center; cursor: pointer;
      color: #333; outline: 2px dashed #8e8e8e; outline-offset: -12px;
      box-shadow: 0 2px 4px rgba(0, 0, 0, 0.4), 0 8px 16px rgba(0, 0, 0, 0.4);
    }
    #drop.over { outline-color: #f07830; }
    #preview { display: none; max-width: 100%; max-height: 360px; margin: 16px auto 0; }
    .upload label { display: flex; flex-direction: column; gap: 4px;
                    font-family: 'Caveat', cursive; font-size: 1.4rem; color: #2e2e2e; }
    .upload input { font: inherit; font-family: sans-serif; font-size: 1rem; padding: 8px 10px;
                    border: 2px solid #555; background: #eeeeee; color: #2e2e2e; }
    .upload input:focus { outline: none; border-color: #f07830; }
    .slug { font-size: 0.75rem; letter-spacing: 1px; text-transform: uppercase; color: #5a5a5a; }
    .slug code { text-transform: none; letter-spacing: 0; font-size: 0.9rem; color: #2e2e2e; }
    .buttons { display: flex; gap: 16px; justify-content: center; }
    .upload button, .upload .button {
      background-color: #2e2e2e; border: 2px solid #555; color: #eeeeee; cursor: pointer;
      font-family: 'Caveat', cursive; font-size: 1.4rem; padding: 6px 24px;
      text-decoration: none; transition: background-color 0.15s, border-color 0.15s;
    }
    .upload button:hover:not(:disabled), .upload .button:hover {
      background-color: #f07830; border-color: #f07830; color: white;
    }
    .pending { background: #f8f2e2; padding: 16px; display: flex; flex-direction: column;
               gap: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.4); }
    .done { background: #eeeeee; padding: 12px; text-align: center; color: #2e2e2e; }
    .upload button:disabled { opacity: 0.5; cursor: default; }
    #status pre { background: #eeeeee; padding: 12px; white-space: pre-wrap; font-size: 0.8rem;
                  max-height: 240px; overflow: auto; margin-top: 8px; }
    #status .error { color: #8a1c00; }
  </style>

  <main class="archive">
    <section class="archive-intro">
      <h2>Upload</h2>
      <p>Drop in a finished comic, give it a number and a title, then save to preview it.</p>
    </section>

    {% if done.saved %}
    <p class="upload done">Saved comic #{{ done.saved }}. Preview it below, then publish or discard it.</p>
    {% elif done.published %}
    <p class="upload done">Published comic #{{ done.published }}. The live site updates once GitHub Pages redeploys.</p>
    {% elif done.discarded %}
    <p class="upload done">Discarded comic #{{ done.discarded }}.</p>
    {% endif %}

    <form id="form" class="upload">
      <div id="drop">Drop the comic image here, or click to choose a file
        <input id="file" type="file" accept=".jpg,.jpeg,.png" hidden>
        <img id="preview" alt="">
      </div>

      <label>Number <input id="number" type="number" min="1" value="{{ next_number }}" required></label>
      <label>Title <input id="title" required></label>
      <p class="slug">Saves as <code id="slug">&mdash;</code></p>

      <div class="buttons">
        <button id="save" type="submit">Save and build</button>
      </div>

      <div id="status"></div>
    </form>

    {% if pending %}
    <section class="archive-intro"><h2>Not published yet</h2></section>
    <section class="upload">
      {% for comic in pending %}
      <div class="pending">
        <span class="plaque-title">#{{ comic.number }} &middot; {{ comic.title }}</span>
        <span class="slug"><code>{{ comic.image }}</code></span>
        <div class="buttons">
          <a class="button" href="{{ comic.url }}">Preview</a>
          <button type="button" data-action="publish" data-number="{{ comic.number }}">Publish</button>
          <button type="button" data-action="discard" data-number="{{ comic.number }}">Discard</button>
        </div>
      </div>
      {% endfor %}
    </section>
    {% endif %}
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    let file = null;

    // The server works out the slug, so what's shown here is exactly what
    // Save will write.
    async function updateSlug() {
      const number = String($('number').value || 0).padStart(4, '0');
      const response = await fetch('/upload/api/slug?' + new URLSearchParams({ title: $('title').value }));
      const { slug } = await response.json();
      $('slug').textContent = slug ? number + '_' + slug : '\\u2014';
    }
    $('title').addEventListener('input', updateSlug);
    $('number').addEventListener('input', updateSlug);

    function choose(chosen) {
      file = chosen;
      $('preview').src = URL.createObjectURL(file);
      $('preview').style.display = 'block';
    }
    $('drop').addEventListener('click', () => $('file').click());
    $('file').addEventListener('change', () => { if ($('file').files[0]) choose($('file').files[0]); });
    $('drop').addEventListener('dragover', (e) => { e.preventDefault(); $('drop').classList.add('over'); });
    $('drop').addEventListener('dragleave', () => $('drop').classList.remove('over'));
    $('drop').addEventListener('drop', (e) => {
      e.preventDefault();
      $('drop').classList.remove('over');
      if (e.dataTransfer.files[0]) choose(e.dataTransfer.files[0]);
    });

    function show(message, isError) {
      $('status').innerHTML = '';
      const pre = document.createElement('pre');
      pre.textContent = message;
      if (isError) pre.className = 'error';
      $('status').appendChild(pre);
    }

    async function post(path, params, body) {
      const response = await fetch(path + '?' + new URLSearchParams(params), { method: 'POST', body });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      return result;
    }

    $('form').addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!file) return show('Choose an image first.', true);
      $('save').disabled = true;
      show('Saving and building...');
      try {
        const result = await post('/upload/api/save',
          { number: $('number').value, title: $('title').value }, file);
        location.href = '/upload?saved=' + result.number;
      } catch (error) {
        show(error.message, true);
        $('save').disabled = false;
      }
    });

    // Publish and Discard on the unpublished list. Discard deletes files, so
    // it takes a second click to confirm.
    for (const button of document.querySelectorAll('[data-action]')) {
      button.addEventListener('click', async () => {
        const { action, number } = button.dataset;
        if (action === 'discard' && !button.dataset.armed) {
          button.dataset.armed = 'yes';
          button.textContent = 'Click again to discard';
          return;
        }
        button.disabled = true;
        show(action === 'publish' ? 'Committing and pushing...' : 'Discarding and rebuilding...');
        try {
          await post('/upload/api/' + action, { number });
          location.href = '/upload?' + (action === 'publish' ? 'published=' : 'discarded=') + number;
        } catch (error) {
          show(error.message, true);
          button.disabled = false;
        }
      });
    }
  </script>
{% endblock %}
"""


def main():
    handler = partial(Handler, directory=str(DOCS))
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"Upload page: http://{HOST}:{PORT}/upload   (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()

# Evidence Showcase

A self-contained static site that displays the harvested evidence (abusive
Facebook comments directed at Rafaella) as a carousel + per-person details
panel. Adapted from `../showcase-mockup/index.html`.

## Build

Run it through rafaella's uv env so Pillow is available (used to auto-crop the
comment screenshots to their content):

```bash
cd rafaella
uv run python ../showcase/build.py          # reads data/out/evidence/, writes ../showcase/dist/
uv run python ../showcase/build.py --open    # build + open in browser
```

(Plain `python3 ../showcase/build.py` also works but skips the auto-crop if
Pillow isn't installed for that interpreter.)

`build.py` reads each `../rafaella/data/out/evidence/<offender>/meta.json`,
copies the comment + profile screenshots into `dist/assets/`, and writes a
single `dist/index.html` with the data inlined (plus a `dist/data.json`).

**Re-run `build.py` whenever the harvest produces new evidence.**

## What `dist/` contains

```
dist/
  index.html        # the showcase (data inlined — opens standalone too)
  data.json         # same records, machine-readable
  .nojekyll         # tells GitHub Pages to serve files as-is
  assets/<person>/  # copied comment_*.png, profile.png, profile_thumb.jpg
```

Everything uses **relative paths**, so `dist/` works on any static host and
even when opened directly from disk (`file://`).

## Deploy

`dist/` is a plain static folder — no build step on the host. Pick one:

### GitHub Pages
Two common ways:

- **`/docs` on the default branch** (simplest): copy the built site to `docs/`
  and point Pages at it.
  ```bash
  rm -rf ../docs && cp -r dist ../docs
  # commit, push, then in repo Settings → Pages: Source = main branch, /docs
  ```
- **`gh-pages` branch** (keeps build artifacts off main):
  ```bash
  cd dist && git init -q && git add -A && git commit -qm "site"
  git branch -M gh-pages
  git remote add origin <your-repo-url>
  git push -f origin gh-pages
  # Settings → Pages: Source = gh-pages branch, / (root)
  ```

### Netlify / Vercel / Cloudflare Pages
Any of these host a static folder with zero config:

- **Netlify** — drag the `dist` folder onto <https://app.netlify.com/drop>, or
  `netlify deploy --dir=dist --prod`.
- **Vercel** — `vercel deploy dist --prod` (set the project's output dir to the
  uploaded folder).
- **Cloudflare Pages** — "Direct Upload" the `dist` folder.

### Local preview
```bash
cd dist && python3 -m http.server 8000   # http://localhost:8000
```

## Share to Instagram story

Each view has a **📤 שיתוף לסטורי** button. It renders a 9:16 (1080×1920)
story image of the current card (comment screenshot + profile photo + who-they-are
+ both links printed on it), copies the profile & comment links to the clipboard,
and opens the native share sheet (`navigator.share`) so the user can send it to
Instagram → Stories, then paste a link into IG's Link Sticker.

Instagram does not allow a shared image to carry clickable links automatically —
that is why the links are baked into the image and copied to the clipboard.

**Requires HTTPS** (a deployed URL or `localhost`). The Web Share API and
clipboard access do not work from a `file://` page; there it falls back to
downloading the PNG. So test sharing on the deployed site or via
`python3 -m http.server` over localhost.

## Notes
- The site is read-only and contains personal data (names, profile links,
  screenshots). Treat hosting/visibility accordingly.
- Entries are sorted worst-first by category severity, then by number of
  comments. The category labels/emoji live in `CATEGORY` in `build.py`.
# stop-the-bully

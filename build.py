"""Build a deployable static showcase from the rafaella evidence output.

Reads ../rafaella/data/out/evidence/<offender>/meta.json (+ the comment and
profile screenshots) and produces a self-contained static site under ./dist/:

    dist/
      index.html          # carousel + details panel (adapted from showcase-mockup)
      data.json           # the offender records (also inlined into index.html)
      .nojekyll           # let GitHub Pages serve as-is
      assets/<offender>/  # copied screenshots (comment_*.png, profile*.{png,jpg})

The dist/ folder uses only relative paths, so it works on GitHub Pages,
Netlify, Vercel, or opened directly from disk (file://).

    python build.py            # build into ./dist
    python build.py --open     # build and open dist/index.html
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE_DIR = (HERE / ".." / "rafaella" / "data" / "out" / "evidence").resolve()
POSTS_SRC = EVIDENCE_DIR / "posts"          # one screenshot per post_id
DIST = HERE / "dist"
ASSETS = DIST / "assets"

_POST_ID_RES = [
    re.compile(r"/posts/(\d+)"),
    re.compile(r"/permalink/(\d+)"),
    re.compile(r"story_fbid=(\d+)"),
    re.compile(r"/groups/[^/]+/posts/(\d+)"),
]


def post_id_from_url(url: str) -> str | None:
    for rx in _POST_ID_RES:
        m = rx.search(url or "")
        if m:
            return m.group(1)
    return None

# Worst-first ordering + (severity, Hebrew label, icon key) per category.
# Icon keys map to inline SVGs defined in the page template (ICONS).
CATEGORY = {
    "threat":              (9, "איום באלימות", "alert-triangle"),
    "sexual_harassment":   (8, "הטרדה מינית", "ban"),
    "slur":                (7, "כינוי גנאי", "message"),
    "dehumanizing":        (6, "השפלה ודה-הומניזציה", "trash"),
    "mental_health_attack":(5, "פגיעה על רקע נפשי", "alert-circle"),
    "degrading_insult":    (4, "עלבון משפיל", "zap"),
    "appearance_mockery":  (3, "לעג למראה", "eye-off"),
    "soldier_mockery":     (2, "לעג על היותה חיילת", "shield"),
    "disgust":             (1, "הבעת גועל", "frown"),
}
_CAT_DEFAULT = (0, "אחר", "alert-circle")

# Comment innerText is "<name>\n<message>\n<time>\nLike\nReply\nShare\n<n>".
# Strip the chrome so the displayed quote is just the message.
_UI_TOKENS = {
    "like", "reply", "share", "follow", "edited", "author",
    "אהבתי", "הגב", "שיתוף", "תגובה", "עקוב", "מחבר/ת", "מחבר",
}
_TIME_RE = re.compile(
    r"^\d+\s*(m|h|d|w|y|min|hr|hrs|day|days|week|weeks|"
    r"דק|דקות|שע|שעות|ימים|יום|שבוע|שבועות|ש|ד)\b", re.IGNORECASE
)


def clean_quote(text: str, name: str) -> str:
    if not text:
        return ""
    out = []
    for raw in text.splitlines():
        t = raw.strip()
        if not t:
            continue
        low = t.lower()
        if name and t == name:
            continue
        if low in _UI_TOKENS:
            continue
        if t.isdigit():
            continue
        if _TIME_RE.match(t):
            continue
        out.append(t)
    cleaned = " ".join(out).strip()
    return cleaned or (text.strip().splitlines()[0] if text.strip() else "")


try:
    from PIL import Image, ImageChops
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


def _copy(src: Path, dest: Path) -> str | None:
    if not src.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    return str(dest.relative_to(DIST)).replace("\\", "/")


def _copy_trimmed(src: Path, dest: Path, pad: int = 12) -> str | None:
    """Copy a comment screenshot auto-cropped to its content bounding box, so
    the comment fills the frame (the screenshots have lots of white margin
    when the comment is short). Per-image, so it never cuts long comments.
    Falls back to a plain copy if Pillow is unavailable or anything fails."""
    if not src.exists():
        return None
    if not _HAVE_PIL:
        return _copy(src, dest)
    try:
        im = Image.open(src).convert("RGB")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bbox = ImageChops.difference(im, bg).getbbox()
        if bbox:
            l, t, r, b = bbox
            box = (max(0, l - pad), max(0, t - pad),
                   min(im.width, r + pad), min(im.height, b + pad))
            im = im.crop(box)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest)
        return str(dest.relative_to(DIST)).replace("\\", "/")
    except Exception:
        return _copy(src, dest)


def build_items() -> list[dict]:
    if not EVIDENCE_DIR.exists():
        raise SystemExit(f"No evidence found at {EVIDENCE_DIR} — run the harvest first.")
    # Wipe dist first so stale assets from previous builds (e.g. full profile.png
    # screenshots that contained the logged-in user's avatar, or assets for
    # offenders pruned by reclassify) never linger in the published site.
    if DIST.exists():
        shutil.rmtree(DIST)
    items: list[dict] = []
    post_copied: dict[str, str | None] = {}   # post_id -> copied rel path (dedup)
    for meta_path in sorted(EVIDENCE_DIR.glob("*/meta.json")):
        folder = meta_path.parent
        slug = folder.name
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        comments = m.get("comments") or []
        if not comments:
            continue
        name = m.get("name") or "Unknown"
        profile = m.get("profile") or {}
        intro = profile.get("intro") or {}

        # Copy each comment screenshot + profile assets into dist/assets/<slug>/.
        rel_comments = []
        for c in comments:
            shot_rel = c.get("screenshot")
            shot_out = (
                _copy_trimmed(folder / shot_rel, ASSETS / slug / shot_rel)
                if shot_rel else None
            )
            rel_comments.append({
                "img": shot_out,
                "cid": c.get("comment_id"),
                "text": clean_quote(c.get("text", ""), name),
                "category": c.get("category"),
                "label": CATEGORY.get(c.get("category"), _CAT_DEFAULT)[1],
                "rationale": c.get("rationale"),
                "link": c.get("comment_permalink"),
            })
        thumb = _copy(folder / "profile_thumb.jpg", ASSETS / slug / "profile_thumb.jpg") \
            if m.get("profile_thumb") else None
        # full profile.png isn't shown in the showcase (we use the thumbnail) —
        # don't copy it, keeps dist/ small.
        prof_png = None

        top_cat = comments[0].get("category")
        cat_meta = CATEGORY.get(top_cat, _CAT_DEFAULT)

        # The post being commented on — one screenshot per post_id, shared.
        post_url = comments[0].get("post_url")
        pid = post_id_from_url(post_url)
        if pid and pid not in post_copied:
            post_copied[pid] = _copy(POSTS_SRC / f"{pid}.png", ASSETS / "posts" / f"{pid}.png")
        post_img = post_copied.get(pid) if pid else None

        items.append({
            "slug": slug,
            "name": name,
            "profile_url": m.get("author_url"),
            "fb_id": m.get("fb_id"),
            "profile_open": bool(m.get("profile_open")),
            "post_id": pid,
            "post_url": post_url,
            "post_img": post_img,
            "category": top_cat,
            "badge": cat_meta[1],
            "cat_icon": cat_meta[2],
            "severity": cat_meta[0],
            "n_comments": len(comments),
            "hero": rel_comments[0]["img"],
            "quote": rel_comments[0]["text"],
            "rationale": rel_comments[0]["rationale"],
            "comment_link": rel_comments[0]["link"],
            "avatar": thumb,
            "profile_png": prof_png,
            "lives_in": intro.get("lives_in"),
            "from": intro.get("from"),
            "works_at": intro.get("works_at"),
            "studied_at": intro.get("studied_at"),
            "studies_at": intro.get("studies_at"),
            "speaks": intro.get("speaks"),
            "friends": profile.get("friend_count"),
            "followers": profile.get("follower_count"),
            "mutual": profile.get("mutual_count"),
            "joined": profile.get("joined_text"),
            "warnings": "; ".join(profile.get("warnings") or []) or None,
            "comments": rel_comments,
        })

    # Worst first, then by how many comments, then name.
    items.sort(key=lambda x: (-x["severity"], -x["n_comments"], x["name"].lower()))
    return items


def write_site(items: list[dict]) -> None:
    (DIST).mkdir(parents=True, exist_ok=True)
    (DIST / ".nojekyll").write_text("")
    (DIST / "data.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for it in items:
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    total_comments = sum(it["n_comments"] for it in items)

    # One entry per post (the showcase groups/filters offenders by post).
    posts: list[dict] = []
    seen: set[str] = set()
    for it in items:
        pid = it.get("post_id")
        if pid and pid not in seen:
            seen.add(pid)
            posts.append({
                "id": pid,
                "img": it.get("post_img"),
                "url": it.get("post_url"),
                "offenders": sum(1 for x in items if x.get("post_id") == pid),
            })

    html = (TEMPLATE
        .replace("/*__DATA__*/", json.dumps(items, ensure_ascii=False))
        .replace("/*__POSTS__*/", json.dumps(posts, ensure_ascii=False))
        .replace("__N_OFFENDERS__", str(len(items)))
        .replace("__N_COMMENTS__", str(total_comments)))
    (DIST / "index.html").write_text(html, encoding="utf-8")
    print(f"built dist/ — {len(items)} offenders, {total_comments} comments")
    print("category breakdown:", json.dumps(counts, ensure_ascii=False))


# The page template. Data is injected at /*__DATA__*/ as a JSON array.
TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stop the bully · עצרו את הבריונות</title>
<style>
  :root {
    --bg:#0a0506; --bg-2:#120709; --surface:rgba(255,60,60,0.05);
    --surface-2:rgba(255,60,60,0.09); --border:rgba(255,70,70,0.18);
    --text:#f6eaea; --muted:#b08a8c; --red:#ff2e3f; --red-deep:#b3000f;
    --red-soft:#ff6b76; --glow:0 0 28px rgba(255,46,63,0.45);
    --radius:16px; --maxw:1100px;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  html { scroll-behavior:smooth; }
  body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
    background:radial-gradient(900px 500px at 50% -10%, rgba(179,0,15,0.25), transparent), var(--bg);
    color:var(--text); line-height:1.6; min-height:100vh; -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:var(--maxw); margin:0 auto; padding:0 24px; }
  header { text-align:center; padding:48px 0 14px; }
  .logo { font-weight:850; font-size:1.4rem; letter-spacing:-0.5px;
    display:inline-flex; align-items:center; gap:10px; color:var(--text); }
  .logo .spark { width:11px; height:11px; border-radius:50%;
    background:var(--red); box-shadow:0 0 14px var(--red),0 0 30px var(--red); }
  header h1 { margin-top:18px; font-size:clamp(1.8rem,5vw,3.2rem); line-height:1.08;
    letter-spacing:-1px; font-weight:850; }
  header h1 .grad { background:linear-gradient(100deg,var(--red-soft),var(--red) 50%,var(--red-deep));
    -webkit-background-clip:text; background-clip:text; color:transparent; }
  header p { color:var(--muted); margin-top:12px; font-size:clamp(.95rem,2vw,1.1rem); }
  .stats { display:flex; gap:14px; justify-content:center; margin-top:18px; flex-wrap:wrap; }
  .stats .s { background:var(--surface); border:1px solid var(--border); border-radius:999px;
    padding:8px 18px; font-size:.9rem; }
  .stats .s b { color:var(--red-soft); font-size:1.05rem; }

  /* post picker — the post being commented on (shown once, not per slide) */
  .postbar { display:flex; gap:16px; align-items:center; margin-top:18px;
    background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:14px; }
  .postbar-img { width:96px; height:96px; object-fit:cover; object-position:top;
    border-radius:12px; background:#fff; border:1px solid var(--border); flex:none; cursor:zoom-in; }
  .postbar-meta { display:flex; flex-direction:column; gap:7px; align-items:flex-start; }
  .postbar-title { font-size:.74rem; color:var(--red-soft); font-weight:700;
    letter-spacing:1.5px; text-transform:uppercase; }
  .postpick { background:var(--bg-2); border:1px solid var(--border); color:var(--text);
    border-radius:999px; padding:8px 14px; font-size:.9rem; max-width:70vw; }
  .postbar.single .postpick { pointer-events:none; }
  .postbar-link { font-size:.8rem; color:var(--red-soft); text-decoration:none; }
  .postbar-link:hover { text-decoration:underline; }

  /* keep the carousel mechanics LTR even though the page is RTL.
     side padding leaves gutters for the arrows so they never cover the
     comment screenshot. the hero follows the screenshot's wide/short shape. */
  .carousel-shell { position:relative; margin-top:26px; direction:ltr; padding:0 64px; }
  .viewport { overflow:hidden; border-radius:14px; direction:ltr; background:#fff; }
  .track { display:flex; direction:ltr; align-items:flex-start;
    transition:transform .5s cubic-bezier(.22,.8,.2,1); }
  .slide { flex:0 0 100%; min-width:0; max-width:100%; position:relative; background:#fff; }
  /* a thread card: [who] on top, the POST, then their COMMENT below it */
  .slide .card { width:100%; max-width:100%; background:#fff; color:#111; overflow:hidden; }
  .slide .postshot, .slide .shot { max-width:100%; }
  .slide .meta-bar { display:flex; align-items:center; gap:11px; padding:11px 14px;
    background:#f5f6f8; border-bottom:1px solid #e2e4e8; }
  .slide .meta-bar .av { width:46px; height:46px; border-radius:50%; object-fit:cover;
    border:2px solid var(--red); flex:none; background:#ddd; }
  .slide .meta-bar .nm { font-weight:800; font-size:1rem; color:#111; }
  .slide .meta-bar .bdg { font-size:.8rem; color:var(--red-deep); font-weight:700;
    display:flex; align-items:center; gap:5px; }
  .slide .meta-bar .bdg svg { stroke:var(--red-deep); width:15px; height:15px; }
  .slide .meta-bar .fct { font-size:.74rem; color:#666; margin-top:1px; }
  .slide .postshot { width:100%; height:auto; max-height:48vh; object-fit:cover;
    object-position:top; display:block; }
  .slide .shot { width:100%; height:auto; display:block; cursor:zoom-in;
    border-top:2px solid #e2e4e8; }
  .slide .nohero { color:#7a3b40; font-size:1.05rem; padding:34px; text-align:center;
    background:#fff; }
  .slide .cap {
    position:absolute; left:0; right:0; bottom:0; z-index:2;
    padding:18px 22px; display:flex; align-items:center; justify-content:space-between;
    gap:16px; flex-wrap:wrap;
    background:linear-gradient(180deg,transparent,rgba(0,0,0,0.85));
  }
  .slide .cap .who { display:flex; align-items:center; gap:12px; }
  .slide .cap .who img { width:42px; height:42px; border-radius:50%; border:2px solid var(--red);
    object-fit:cover; background:#2b0007; }
  .slide .cap .who .nm { font-weight:700; }
  .slide .cap .who .hd { font-size:.8rem; color:var(--muted); }
  .slide .cap .open-hint { font-size:.82rem; color:var(--red-soft); font-weight:600;
    border:1px solid var(--border); padding:7px 14px; border-radius:999px;
    background:rgba(0,0,0,0.45); text-decoration:none; }
  .slide .cap .open-hint:hover { background:var(--red-deep); color:#fff; }

  .arrow { position:absolute; top:50%; transform:translateY(-50%);
    width:50px; height:50px; border-radius:50%; border:1px solid var(--border);
    background:rgba(10,5,6,0.7); backdrop-filter:blur(8px); color:var(--text);
    font-size:1.4rem; cursor:pointer; z-index:5; display:grid; place-items:center;
    transition:background .2s, box-shadow .2s, transform .2s; }
  .arrow:hover { background:var(--red-deep); box-shadow:var(--glow); }
  .arrow:active { transform:translateY(-50%) scale(.92); }
  .arrow.prev { left:6px; } .arrow.next { right:6px; }

  .nav-row { display:flex; align-items:center; justify-content:center; gap:14px;
    margin-top:18px; flex-wrap:wrap; }
  .counter { font-size:.95rem; color:var(--muted); min-width:70px; text-align:center; direction:ltr; }
  .counter b { color:var(--red-soft); }
  .jump { background:var(--surface); border:1px solid var(--border); color:var(--text);
    border-radius:999px; padding:8px 14px; font-size:.85rem; }
  select.jump { max-width:50vw; }
  .actions { display:flex; gap:12px; justify-content:center; align-items:stretch;
    margin:22px auto 0; max-width:var(--maxw); padding:0 24px; flex-wrap:wrap; }
  .act { display:inline-flex; align-items:center; justify-content:center; gap:8px;
    cursor:pointer; text-decoration:none; border:1px solid var(--border);
    background:var(--surface); color:var(--text); border-radius:999px;
    padding:11px 20px; font-size:.92rem; font-weight:700; }
  .icn { width:1.05em; height:1.05em; display:inline-block; vertical-align:-0.16em;
    stroke:currentColor; fill:none; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
  .act .icn { width:20px; height:20px; }
  .pbadge .icn, .dlabel .icn { width:15px; height:15px; }
  .act:hover { background:var(--surface-2); }
  .act.act-share { background:var(--red-deep); color:#fff; box-shadow:var(--glow); }
  .act.act-share:hover { background:var(--red); }
  .act[hidden] { display:none; }
  .toast { position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
    background:var(--bg-2); color:var(--text); border:1px solid var(--border);
    padding:12px 20px; border-radius:999px; font-size:.9rem; z-index:60; opacity:0;
    transition:opacity .25s; pointer-events:none; box-shadow:0 0 30px rgba(0,0,0,.55);
    max-width:90vw; text-align:center; }
  .toast.show { opacity:1; }

  .details { margin-top:24px; }
  .panel { transition:opacity .3s ease, transform .3s ease; }
  .panel.swap { opacity:0; transform:translateY(10px); }
  .panel { background:linear-gradient(180deg,var(--bg-2),rgba(18,7,9,0.4));
    border:1px solid var(--border); border-radius:20px; padding:30px;
    display:grid; grid-template-columns:340px 1fr; gap:30px;
    box-shadow:0 0 50px rgba(255,46,63,0.08); }
  .pcol { text-align:center; }
  .pcol .ring { width:300px; height:300px; border-radius:50%; margin:0 auto 16px; padding:5px;
    background:conic-gradient(var(--red-soft),var(--red),var(--red-deep),var(--red-soft));
    box-shadow:var(--glow); }
  .pcol .ring img { width:100%; height:100%; border-radius:50%; border:3px solid var(--bg);
    display:block; object-fit:cover; background:#2b0007; }
  .pcol .pname { font-weight:800; font-size:1.15rem; }
  .pcol .phandle { color:var(--muted); font-size:.8rem; word-break:break-all; }
  .pcol .pbadge { display:inline-block; margin-top:12px; font-size:.74rem; font-weight:700;
    padding:6px 13px; border-radius:999px; color:var(--red-soft);
    background:rgba(255,46,63,0.1); border:1px solid var(--border); }
  .pcol .plink { display:block; margin-top:12px; font-size:.8rem; color:var(--red-soft);
    text-decoration:none; }
  .pcol .plink:hover { text-decoration:underline; }
  .dcol .dlabel { color:var(--red-soft); font-size:.76rem; font-weight:700; letter-spacing:2px;
    text-transform:uppercase; }
  .dcol h3 { font-size:1.3rem; margin:6px 0 14px; letter-spacing:-.5px; }
  .quote-full { font-size:1.05rem; line-height:1.6; padding:16px 20px; direction:rtl;
    border-right:3px solid var(--red); background:var(--surface); border-radius:8px; margin-bottom:14px; }
  .why { color:var(--muted); margin-bottom:16px; font-size:.92rem; }
  .meta-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:14px; }
  .meta-grid .m { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:14px; }
  .meta-grid .m .mk { color:var(--muted); font-size:.72rem; text-transform:uppercase; letter-spacing:.5px; }
  .meta-grid .m .mv { font-weight:750; font-size:1rem; margin-top:4px; word-break:break-word; }
  .meta-grid .m .mv.red { color:var(--red-soft); }
  .gallery { margin-top:18px; }
  .gallery .gt { color:var(--red-soft); font-size:.76rem; font-weight:700; letter-spacing:2px;
    text-transform:uppercase; margin-bottom:10px; }
  .gallery .gimgs { display:flex; gap:10px; overflow-x:auto; padding-bottom:6px; }
  .gallery .gimgs a { flex:0 0 auto; }
  .gallery .gimgs img { height:90px; border-radius:8px; border:1px solid var(--border);
    background:#fff; cursor:zoom-in; }

  /* lightbox */
  .lb[hidden] { display:none; }
  .lb { position:fixed; inset:0; z-index:50; display:grid; place-items:center; padding:24px; }
  .lb-bg { position:absolute; inset:0; background:rgba(5,2,3,0.86); backdrop-filter:blur(4px); }
  .lb-box { position:relative; z-index:1; max-width:min(900px,94vw); text-align:center; }
  .lb-img { max-width:100%; max-height:78vh; border-radius:10px; background:#fff;
    box-shadow:0 0 60px rgba(255,46,63,0.35); }
  .lb-meta { margin-top:14px; display:flex; align-items:center; justify-content:center;
    gap:16px; flex-wrap:wrap; }
  .lb-label { font-weight:700; color:var(--red-soft); }
  .lb-fb { color:var(--text); text-decoration:none; border:1px solid var(--border);
    padding:8px 16px; border-radius:999px; background:var(--surface); }
  .lb-fb:hover { background:var(--red-deep); }
  .lb-close { position:absolute; top:-14px; left:-14px; width:42px; height:42px; border-radius:50%;
    border:1px solid var(--border); background:var(--bg-2); color:var(--text); font-size:1.5rem;
    cursor:pointer; z-index:2; }
  .lb-close:hover { background:var(--red-deep); }

  footer { text-align:center; padding:40px 0; color:var(--muted); font-size:.82rem;
    border-top:1px solid var(--border); margin-top:50px; }

  /* ---- mobile: lock everything into one screen (no scroll) for screenshots ---- */
  @media (max-width:680px) {
    /* locked to one screen (no scroll): compact card + user details + action bar */
    body { height:100dvh; overflow:hidden; display:flex; flex-direction:column; }
    header { padding:6px 0 2px; flex:none; }
    .logo { font-size:1.05rem; }
    header h1 { margin-top:3px; font-size:1.05rem; }
    header p { display:none; }
    .stats { margin-top:5px; gap:8px; }
    .stats .s { padding:4px 11px; font-size:.72rem; }
    .stats .s b { font-size:.9rem; }

    .postbar { margin:5px 12px 0; padding:6px 9px; gap:9px; flex:none; }
    .postbar-img { width:38px; height:38px; border-radius:8px; }
    .postbar-title, .postbar-link { display:none; }
    .postpick { font-size:.76rem; padding:4px 10px; }

    main.wrap { flex:1; min-width:0; max-width:100%; min-height:0; margin:0;
      padding:0 12px; display:flex; flex-direction:column; gap:6px; overflow:hidden; }
    .carousel-shell { margin-top:4px; flex:none; min-width:0; padding:0 36px; }
    .viewport { border-radius:12px; min-width:0; }
    .slide .meta-bar { padding:5px 10px; gap:7px; }
    .slide .meta-bar .av { width:32px; height:32px; }
    .slide .meta-bar .nm { font-size:.82rem; }
    .slide .meta-bar .bdg { font-size:.68rem; }
    .slide .meta-bar .fct { display:none; }
    .slide .postshot { max-height:19dvh; }
    .slide .shot { max-height:13dvh; object-fit:cover; object-position:top; }
    .arrow { width:34px; height:34px; font-size:1.1rem; }
    .arrow.prev { left:3px; } .arrow.next { right:3px; }

    .nav-row { margin-top:0; gap:10px; flex:none; }
    .counter { font-size:.85rem; }
    .jump { display:none; }

    .details { margin-top:0; flex:1; min-height:0; overflow:hidden; }
    .panel { grid-template-columns:1fr; gap:7px; padding:10px; overflow:hidden;
      align-content:start; }
    .pcol { display:none; }                  /* avatar + name already on the card */
    .dcol .dlabel, .dcol h3 { display:none; }
    .quote-full, .why { display:none; }       /* the comment is shown on the card */
    /* compact data grid — all harvested fields */
    .meta-grid { grid-template-columns:repeat(3,1fr); gap:5px; }
    .meta-grid .m { padding:5px 7px; border-radius:9px; }
    .meta-grid .m .mk { font-size:.56rem; letter-spacing:0; }
    .meta-grid .m .mv { font-size:.72rem; margin-top:1px; line-height:1.2; }
    .gallery { display:none; }

    /* action buttons: static bottom bar inside the locked column */
    .actions { flex:none; margin:0; max-width:none; gap:6px;
      padding:6px 8px calc(6px + env(safe-area-inset-bottom));
      background:var(--bg-2); border-top:1px solid var(--border); }
    .act { flex:1; flex-direction:column; gap:2px; padding:7px 4px; font-size:.68rem;
      border-radius:12px; }
    .act .icn { width:20px; height:20px; }

    footer { display:none; }
  }
  @media (prefers-reduced-motion:reduce){ *,*::before,*::after{transition:none!important;} }
</style>
</head>
<body>
<header>
  <div class="wrap">
    <div class="logo"><span class="spark"></span>Stop the bully</div>
    <h1>עצרו את הבריונות נגד <span class="grad">רפאלה</span></h1>
    <p>תיעוד תגובות פוגעניות שהופנו אל רפאלה. כל פריט מקושר למקור בפייסבוק.</p>
    <div class="stats">
      <div class="s"><b>__N_OFFENDERS__</b> מתעללים</div>
      <div class="s"><b>__N_COMMENTS__</b> תגובות פוגעניות</div>
    </div>
  </div>
</header>

<div class="postbar wrap" id="postbar">
  <img class="postbar-img" id="postImg" alt="הפוסט">
  <div class="postbar-meta">
    <div class="postbar-title">הפוסט שעליו הגיבו</div>
    <select class="postpick" id="postpick" aria-label="בחירת פוסט"></select>
    <a class="postbar-link" id="postLink" target="_blank" rel="noopener">צפייה בפוסט בפייסבוק ↗</a>
  </div>
</div>

<main class="wrap">
  <div class="carousel-shell">
    <div class="viewport"><div class="track" id="track"></div></div>
    <button class="arrow prev" id="prev" aria-label="Previous">‹</button>
    <button class="arrow next" id="next" aria-label="Next">›</button>
  </div>
  <div class="nav-row">
    <span class="counter"><b id="cur">1</b> / <span id="total">0</span></span>
    <select class="jump" id="jump" aria-label="מעבר לאדם"></select>
  </div>
  <div class="details"><div class="panel" id="panel"></div></div>
</main>

<div class="actions" id="actions">
  <a class="act" id="actProfile" target="_blank" rel="noopener"><svg class="icn" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M5.5 21a8.5 8.5 0 0 1 13 0"/></svg>פרופיל בפייסבוק</a>
  <a class="act" id="actComment" target="_blank" rel="noopener"><svg class="icn" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>צפייה בתגובה</a>
  <button class="act act-share" id="actShare"><svg class="icn" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="m16 6-4-4-4 4"/><path d="M12 2v13"/></svg>שיתוף לסטורי</button>
</div>

<div class="lb" id="lb" hidden>
  <div class="lb-bg" id="lbbg"></div>
  <div class="lb-box">
    <button class="lb-close" id="lbclose" aria-label="סגירה">×</button>
    <img id="lbimg" class="lb-img" alt="">
    <div class="lb-meta">
      <span id="lblabel" class="lb-label"></span>
      <a id="lbfb" class="lb-fb" target="_blank" rel="noopener">צפייה בפייסבוק ↗</a>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<footer>תועד לצורך תיעוד הטרדה · הנתונים מתוך תגובות פומביות בפייסבוק</footer>

<script>
  const DATA = /*__DATA__*/;
  const esc = s => (s==null?'':String(s)).replace(/[&<>"]/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  const ICONS = {
    'alert-triangle':'<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    'ban':'<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    'message':'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    'trash':'<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    'alert-circle':'<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    'zap':'<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
    'eye-off':'<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.5 13.5 0 0 0 2 12s3 7 10 7a9.7 9.7 0 0 0 5.39-1.61"/><path d="m2 2 20 20"/>',
    'shield':'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    'frown':'<circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
  };
  function ico(name){ return `<svg class="icn" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]||ICONS['alert-circle']}</svg>`; }

  function initials(name){ return (name||'?').trim().charAt(0) || '?'; }
  function avatarFallback(name){
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>
      <defs><radialGradient id='g' cx='40%' cy='35%' r='80%'>
      <stop offset='0' stop-color='#ff6b76'/><stop offset='1' stop-color='#2b0007'/></radialGradient></defs>
      <rect width='100%' height='100%' fill='url(#g)'/>
      <text x='50%' y='54%' font-size='58' fill='rgba(255,255,255,0.92)' font-family='sans-serif'
        text-anchor='middle' dominant-baseline='middle' font-weight='800'>${esc(initials(name))}</text></svg>`;
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
  }

  const POSTS = /*__POSTS__*/;
  const track = document.getElementById('track');
  const viewport = document.querySelector('.viewport');
  const jump = document.getElementById('jump');
  const actProfile = document.getElementById('actProfile');
  const actComment = document.getElementById('actComment');
  const postpick = document.getElementById('postpick');
  const postImg = document.getElementById('postImg');
  const postLink = document.getElementById('postLink');

  // fit the viewport to the active slide so short comments don't leave a gap
  function fitHeight(){ const a = track.children[index]; if (a) viewport.style.height = a.offsetHeight + 'px'; }

  POSTS.forEach((p,i)=>{ const o=document.createElement('option');
    o.value=i; o.textContent=`פוסט ${i+1} — ${p.offenders} מתעללים`; postpick.appendChild(o); });
  if (POSTS.length <= 1) document.getElementById('postbar').classList.add('single');

  let ITEMS = [];     // offenders of the currently-selected post
  let postIdx = 0;
  let index = 0;

  // (re)build the carousel + jump list for the current post
  function buildCarousel(){
    track.innerHTML = ''; jump.innerHTML = '';
    ITEMS = DATA.filter(d => d.post_id === POSTS[postIdx].id);
    ITEMS.forEach((it, i) => {
      const av = it.avatar || avatarFallback(it.name);
      const facts = [it.lives_in, it.from].filter(Boolean).join(' · ');
      const meta = `<div class="meta-bar">
        <img class="av" src="${esc(av)}" alt="">
        <div class="meta-txt">
          <div class="nm">${esc(it.name)}</div>
          <div class="bdg">${ico(it.cat_icon)} ${esc(it.badge)}</div>
          ${facts ? `<div class="fct">${esc(facts)}</div>` : ''}
        </div></div>`;
      const post = it.post_img
        ? `<img class="postshot" src="${esc(it.post_img)}" alt="הפוסט">` : '';
      const hero = it.hero
        ? `<img class="shot" data-hero="${i}" src="${esc(it.hero)}" alt="תגובה של ${esc(it.name)}">`
        : `<div class="nohero">${esc(it.quote || '(לא נלכד צילום מסך)')}</div>`;
      const slide = document.createElement('div');
      slide.className = 'slide';
      slide.innerHTML = `<div class="card">${meta}${post}${hero}</div>`;
      slide.querySelectorAll('img').forEach(im =>
        im.addEventListener('load', () => { if (i === index) fitHeight(); }));
      track.appendChild(slide);
      const opt = document.createElement('option');
      opt.value = i; opt.textContent = `${i+1}. ${it.name} — ${it.badge}`;
      jump.appendChild(opt);
    });
    document.getElementById('total').textContent = ITEMS.length;
  }

  function selectPost(i){
    postIdx = (i + POSTS.length) % POSTS.length;
    const p = POSTS[postIdx];
    if (p.img){ postImg.src = p.img; postImg.style.display=''; } else postImg.style.display='none';
    if (p.url){ postLink.href = p.url; postLink.style.display=''; } else postLink.style.display='none';
    postpick.value = postIdx;
    buildCarousel();
    index = 0; render();
  }
  postpick.addEventListener('change', e => selectPost(parseInt(e.target.value,10)));
  postImg.addEventListener('click', () => { const u=POSTS[postIdx] && POSTS[postIdx].url; if(u) window.open(u,'_blank','noopener'); });

  // ---- lightbox + deep links ----
  const lb = document.getElementById('lb');
  const lbimg = document.getElementById('lbimg');
  const lblabel = document.getElementById('lblabel');
  const lbfb = document.getElementById('lbfb');
  function setURL(slug, cid){
    const p = new URLSearchParams();
    if (POSTS[postIdx]) p.set('post', POSTS[postIdx].id);
    if (slug) p.set('person', slug);
    if (cid) p.set('c', cid);
    const q = p.toString();
    history.replaceState(null, '', location.pathname + (q ? '?'+q : ''));
  }
  function openLightbox(cid){
    const it = ITEMS[index]; if (!it) return;
    let c = cid ? (it.comments||[]).find(x => String(x.cid)===String(cid)) : null;
    if (!c) c = (it.comments||[])[0];
    if (!c || !c.img) return;
    lbimg.src = c.img;
    lblabel.textContent = c.label || '';
    if (c.link){ lbfb.href = c.link; lbfb.style.display=''; } else { lbfb.style.display='none'; }
    lb.hidden = false;
    setURL(it.slug, c.cid);
  }
  function closeLightbox(){ lb.hidden = true; setURL(ITEMS[index].slug, null); }
  document.getElementById('lbclose').addEventListener('click', closeLightbox);
  document.getElementById('lbbg').addEventListener('click', closeLightbox);
  track.addEventListener('click', e => {
    const img = e.target.closest('img.shot[data-hero]');
    if (img) openLightbox(null);
  });

  function render(){
    const it = ITEMS[index]; if (!it) return;
    track.style.transform = `translateX(-${index*100}%)`;
    document.getElementById('cur').textContent = index+1;
    jump.value = index;
    if (it.profile_url){ actProfile.href = it.profile_url; actProfile.hidden = false; }
    else { actProfile.hidden = true; }
    if (it.comment_link){ actComment.href = it.comment_link; actComment.hidden = false; }
    else { actComment.hidden = true; }
    renderDetails(index);
    setURL(it.slug, null);
    requestAnimationFrame(fitHeight);
  }
  function goTo(i){ lb.hidden = true; index = (i + ITEMS.length) % ITEMS.length; render(); }
  window.addEventListener('resize', fitHeight);
  document.getElementById('next').addEventListener('click', ()=>goTo(index+1));
  document.getElementById('prev').addEventListener('click', ()=>goTo(index-1));
  jump.addEventListener('change', e => goTo(parseInt(e.target.value,10)));
  document.addEventListener('keydown', e => {
    if (e.key==='Escape' && !lb.hidden) { closeLightbox(); return; }
    if (!lb.hidden) return;
    if (e.key==='ArrowRight') goTo(index+1);
    if (e.key==='ArrowLeft') goTo(index-1);
  });

  // ---- share to Instagram story (9:16 image + links) ----
  const toast = document.getElementById('toast');
  let toastT = null;
  function showToast(msg, ms){
    toast.textContent = msg; toast.classList.add('show');
    clearTimeout(toastT); toastT = setTimeout(()=>toast.classList.remove('show'), ms||3500);
  }
  function loadImg(src){ return new Promise(res => {
    const im = new Image(); im.onload = ()=>res(im); im.onerror = ()=>res(null); im.src = src; }); }
  function roundRect(ctx,x,y,w,h,r){ ctx.beginPath();
    ctx.moveTo(x+r,y); ctx.arcTo(x+w,y,x+w,y+h,r); ctx.arcTo(x+w,y+h,x,y+h,r);
    ctx.arcTo(x,y+h,x,y,r); ctx.arcTo(x,y,x+w,y,r); ctx.closePath(); }
  function shortUrl(u){ return (u||'').replace(/^https?:\/\/(www\.)?/,'').slice(0,60); }
  const F = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif";
  function line(ctx,text,x,y,size,weight,color){
    ctx.fillStyle=color; ctx.font=`${weight} ${size}px ${F}`; ctx.fillText(text,x,y); }
  function wrap(ctx,text,x,y,maxw,lh,size,weight,color,maxlines){
    ctx.fillStyle=color; ctx.font=`${weight} ${size}px ${F}`;
    const words=(text||'').split(/\s+/); let cur='', lines=0;
    for(const w of words){ const t=cur?cur+' '+w:w;
      if(ctx.measureText(t).width>maxw && cur){ ctx.fillText(cur,x,y); y+=lh; cur=w; lines++;
        if(lines>=maxlines-1){ break; } } else cur=t; }
    ctx.fillText(cur,x,y); return y+lh; }

  async function shareStory(i){
    const it = ITEMS[i];
    showToast('מכין תמונה לשיתוף…', 8000);
    const W=1080, H=1920, cx=W/2;
    const cv=document.createElement('canvas'); cv.width=W; cv.height=H;
    const ctx=cv.getContext('2d'); ctx.direction='rtl'; ctx.textAlign='center';
    const g=ctx.createLinearGradient(0,0,0,H); g.addColorStop(0,'#1a0307'); g.addColorStop(1,'#0a0506');
    ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
    const rg=ctx.createRadialGradient(cx,-60,40,cx,-60,820);
    rg.addColorStop(0,'rgba(179,0,15,0.5)'); rg.addColorStop(1,'rgba(179,0,15,0)');
    ctx.fillStyle=rg; ctx.fillRect(0,0,W,760);
    line(ctx,'Stop the bully',cx,128,66,'800','#ffffff');
    line(ctx,'עצרו את הבריונות נגד רפאלה',cx,196,44,'800','#ff6b76');

    let y=255;
    const postim = it.post_img ? await loadImg(it.post_img) : null;
    if(postim && postim.width){
      const maxW=W-220; let scale=Math.min(maxW/postim.width,1.2);
      let dw=postim.width*scale, dh=postim.height*scale;
      const maxH=340; if(dh>maxH){ const k=maxH/dh; dh=maxH; dw*=k; }
      const dx=(W-dw)/2;
      ctx.save(); roundRect(ctx,dx-8,y-8,dw+16,dh+16,14); ctx.fillStyle='#fff'; ctx.fill();
      ctx.clip(); ctx.drawImage(postim,dx,y,dw,dh); ctx.restore();
      y+=dh+26; line(ctx,'הגיב/ה על הפוסט:',cx,y,30,'700','#ff6b76'); y+=42;
    }
    const hero = it.hero ? await loadImg(it.hero) : null;
    if(hero && hero.width){
      const maxW=W-110, scale=Math.min(maxW/hero.width,1.6);
      const dw=hero.width*scale, dh=hero.height*scale, dx=(W-dw)/2;
      ctx.save(); roundRect(ctx,dx-12,y-12,dw+24,dh+24,18); ctx.fillStyle='#fff'; ctx.fill();
      ctx.clip(); ctx.drawImage(hero,dx,y,dw,dh); ctx.restore();
      y+=dh+56;
    }
    const av = it.avatar ? await loadImg(it.avatar) : null;
    if(av && av.width){
      const r=96;
      ctx.save(); ctx.beginPath(); ctx.arc(cx,y+r,r,0,Math.PI*2); ctx.closePath(); ctx.clip();
      ctx.drawImage(av,cx-r,y,2*r,2*r); ctx.restore();
      ctx.lineWidth=6; ctx.strokeStyle='#ff2e3f'; ctx.beginPath(); ctx.arc(cx,y+r,r,0,Math.PI*2); ctx.stroke();
      y+=2*r+44;
    }
    line(ctx,it.name,cx,y,56,'800','#f6eaea'); y+=66;
    line(ctx,it.badge||'',cx,y,40,'700','#ff6b76'); y+=58;
    const fields=[['גר/ה ב',it.lives_in],['מ',it.from],['עובד/ת ב',it.works_at],
      ['שפות',it.speaks],['חברים',it.friends],['מזהה',it.fb_id]];
    for(const [k,v] of fields){ if(v){ line(ctx,k+': '+v,cx,y,33,'400','#d9c7c8'); y+=44; } }
    if(it.quote){ y+=12; y=wrap(ctx,'“'+it.quote+'”',cx,y,W-150,52,40,'600','#ffffff',3); }

    line(ctx,'הקישורים המלאים:',cx,H-250,30,'700','#ff6b76');
    let ly=H-202;
    if(it.profile_url){ line(ctx,'פרופיל · '+shortUrl(it.profile_url),cx,ly,27,'400','#c9b3b4'); ly+=40; }
    if(it.comment_link){ line(ctx,'תגובה · '+shortUrl(it.comment_link),cx,ly,27,'400','#c9b3b4'); ly+=40; }
    line(ctx,'Stop the bully · עצרו את הבריונות',cx,H-70,30,'700','#ff6b76');

    const links=[it.profile_url && ('פרופיל: '+it.profile_url),
                 it.comment_link && ('תגובה: '+it.comment_link)].filter(Boolean).join('\n');
    try { await navigator.clipboard.writeText(links); } catch(e) {}
    cv.toBlob(async (blob)=>{
      if(!blob){ showToast('לא ניתן ליצור תמונה (פתחו את האתר דרך כתובת https)'); return; }
      const file=new File([blob],`stop-the-bully-${it.slug}.png`,{type:'image/png'});
      if(navigator.canShare && navigator.canShare({files:[file]})){
        try{ await navigator.share({files:[file], title:'Stop the bully', text:links});
          showToast('הקישורים הועתקו — הדביקו ב-Link Sticker בסטורי'); return; }catch(e){ if(e&&e.name==='AbortError') return; }
      }
      const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
      a.download=file.name; document.body.appendChild(a); a.click(); a.remove();
      showToast('התמונה הורדה והקישורים הועתקו ללוח');
    }, 'image/png');
  }
  document.getElementById('actShare').addEventListener('click', ()=>shareStory(index));

  const panel = document.getElementById('panel');
  panel.addEventListener('click', e => {
    const a = e.target.closest('a.gthumb');
    if (a) { e.preventDefault(); openLightbox(a.dataset.cid); }
  });
  function metaCell(k,v,red){ return v ? `<div class="m"><div class="mk">${esc(k)}</div>
    <div class="mv${red?' red':''}">${esc(v)}</div></div>` : ''; }
  function panelHTML(i){
    const it = ITEMS[i];
    const av = it.avatar || avatarFallback(it.name);
    const gallery = (it.comments && it.comments.length)
      ? `<div class="gallery"><div class="gt">כל ${it.comments.length} התגובות שסומנו</div>
         <div class="gimgs">${it.comments.map(c => c.img
            ? `<a class="gthumb" data-cid="${esc(c.cid)}"
                 href="?person=${encodeURIComponent(it.slug)}&c=${encodeURIComponent(c.cid||'')}"
                 title="${esc(c.label||'')}"><img src="${esc(c.img)}" alt=""></a>` : '').join('')}</div></div>`
      : '';
    return `
      <div class="pcol">
        <div class="ring"><img src="${esc(av)}" alt=""></div>
        <div class="pmeta">
          <div class="pname">${esc(it.name)}</div>
          <div class="phandle">${esc(it.fb_id ? 'מזהה '+it.fb_id : (it.profile_url||''))}</div>
          <span class="pbadge">${ico(it.cat_icon)} ${esc(it.badge)}</span>
        </div>
      </div>
      <div class="dcol">
        <div class="dlabel">${ico(it.cat_icon)} ${esc(it.badge)}</div>
        <h3>מה הם כתבו</h3>
        <div class="quote-full">${esc(it.quote || '(ראו צילום מסך)')}</div>
        ${it.rationale ? `<div class="why">סיבת הסימון: ${esc(it.rationale)}</div>` : ''}
        <div class="meta-grid">
          ${metaCell('תגובות פוגעניות', it.n_comments, true)}
          ${metaCell('קטגוריה', it.badge)}
          ${metaCell('פרופיל', it.profile_open ? 'פתוח' : 'סגור/פרטי')}
          ${metaCell('גר/ה ב', it.lives_in)}
          ${metaCell('מ', it.from)}
          ${metaCell('עובד/ת ב', it.works_at)}
          ${metaCell('למד/ה ב', it.studied_at)}
          ${metaCell('לומד/ת ב', it.studies_at)}
          ${metaCell('שפות', it.speaks)}
          ${metaCell('חברים', it.friends)}
          ${metaCell('עוקבים', it.followers)}
          ${metaCell('חברים משותפים', it.mutual)}
          ${metaCell('הצטרפ/ה', it.joined)}
          ${metaCell('מזהה פייסבוק', it.fb_id)}
          ${metaCell('אזהרות פייסבוק', it.warnings)}
        </div>
        ${gallery}
      </div>`;
  }
  let firstRender = true;
  function renderDetails(i){
    if (firstRender){ panel.innerHTML = panelHTML(i); firstRender=false; return; }
    panel.classList.add('swap');
    setTimeout(()=>{ panel.innerHTML = panelHTML(i); panel.classList.remove('swap'); }, 180);
  }

  // ---- deep link on load: ?post=<id>&person=<slug>&c=<comment_id> ----
  const params = new URLSearchParams(location.search);
  let startPost = 0;
  const pq = params.get('post');
  const ps = params.get('person');
  if (pq){ const k = POSTS.findIndex(p => p.id === pq); if (k >= 0) startPost = k; }
  else if (ps){ const d = DATA.find(x => x.slug === ps);
    if (d){ const k = POSTS.findIndex(p => p.id === d.post_id); if (k >= 0) startPost = k; } }
  selectPost(startPost);
  if (ps){ const k = ITEMS.findIndex(d => d.slug === ps); if (k >= 0){ index = k; render(); } }
  const cstart = params.get('c');
  if (cstart) openLightbox(cstart);
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the static evidence showcase.")
    ap.add_argument("--open", action="store_true", help="open dist/index.html after building")
    args = ap.parse_args()
    items = build_items()
    write_site(items)
    if args.open:
        webbrowser.open((DIST / "index.html").as_uri())


if __name__ == "__main__":
    main()

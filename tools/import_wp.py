#!/usr/bin/env python3
"""One-time importer: WordPress public REST export -> Hugo content (allowlist-sanitized).

Usage:
  python3 -I tools/import_wp.py <export_dir> <repo_dir> <pdf_map.json>

<export_dir> holds posts.json / pages.json / media.json and site_mirror/ (produced from the
public REST API of the old site). Nothing from the export is copied unless it passes the
allowlist below. Any tag, attribute or URL that is not explicitly allowed makes the import
FAIL (the old site was compromised in 2025, so its HTML is treated as untrusted input).

Standard library only (no third-party packages).
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

SITE_HOSTS = {"okiyamasho.com", "www.okiyamasho.com"}
JETPACK_CDN = re.compile(r"^i[0-3]\.wp\.com$")

# WordPress post id -> new slug = first publication date (URL: /posts/<yyyymmdd>/, owner's choice
# 2026-11-08). Fixed on purpose: these are permanent URLs.
SLUGS = {
    473: "20171012",
    435: "20170929",
    404: "20170830",
    397: "20170819",
    359: "20170808",
    330: "20170728",
    302: "20170717",
    277: "20170626",
    264: "20170619",
    230: "20170621",
    122: "20170613",
    46: "20170610",
}
PAGE_SLUGS = {11: "profile"}

# Speaker Deck embeds -> static preview (no third-party script / iframe on our pages).
SPEAKERDECK = {
    "30c1e95d7ebf46fb8a25a8bf5b603a28": ("exponential-technologies-and-the-future",
        "https://speakerdeck.com/shookiyama/exponential-technologies-and-the-future",
        "エクスポネンシャル・テクノロジーと未来"),
    "4cbcea3a8212403fa7f4b1ff451090b1": ("understanding-ai-from-scratch",
        "https://speakerdeck.com/shookiyama/understanding-ai-from-scratch",
        "イメージで理解する人工知能 〜入門編〜"),
    "a06f391c1aa04fa2a553fcab1e492851": ("medicine-and-ai-qc-bc-and-more",
        "https://speakerdeck.com/shookiyama/medicine-and-ai-qc-bc-and-more",
        "医療 × AI, 量子コンピュータ, ブロックチェーン, ロボット, AR, VR, CRISPR, BCI"),
}

ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "sub", "sup", "h2", "h3", "h4", "h5", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "span", "div", "a", "img", "blockquote", "hr",
    "figure", "figcaption",
}
VOID_TAGS = {"br", "img", "hr"}
# Attributes that are silently dropped (harmless WordPress/Jetpack bookkeeping).
DROP_ATTRS = {
    "data-recalc-dims", "decoding", "data-attachment-id", "data-permalink", "data-orig-file",
    "data-orig-size", "data-comments-opened", "data-image-title", "data-image-description",
    "data-image-caption", "data-large-file", "data-medium-file", "data-image-meta", "srcset",
    "sizes", "loading", "data-wp-pid", "style", "target", "rel", "id",
}
KEEP_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "th": {"scope"},
    "td": set(),
    "p": {"class"}, "span": {"class"}, "div": {"class"}, "table": {"class"}, "figure": {"class"},
}
ALLOWED_CLASSES = {"box01", "box-title", "type01", "alignnone", "aligncenter", "alignleft",
                   "alignright", "has-text-align-center"}
STYLE_TO_CLASS = {"text-align: center;": "has-text-align-center"}


class ImportError_(Exception):
    pass


def inside(base: Path, rel: str) -> Path:
    """Join a URL path under base and refuse anything that escapes it ('..', symlinks)."""
    if any(seg in ("..", ".") for seg in rel.split("/")) or "\\" in rel or "\x00" in rel:
        raise ImportError_(f"suspicious path segment: {rel!r}")
    target = (base / rel.lstrip("/")).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ImportError_(f"path escapes {base}: {rel!r}")
    return target


# TeX in text nodes -> marker spans that layouts/partials/render-math.html turns into MathML.
# Marker classes are NOT in ALLOWED_CLASSES, so original content can never forge them.
TEX_DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.S)
TEX_INLINE = re.compile(r"\\\((.+?)\\\)", re.S)
TEX_FIX = {"\u2019": "'", "\u2026": "\\ldots "}  # WordPress smart quotes inside formulas


def tex_markup(text: str) -> str:
    def esc(tex: str) -> str:
        for k, v in TEX_FIX.items():
            tex = tex.replace(k, v)
        return html.escape(tex, quote=True)
    out, pos = [], 0
    pattern = re.compile(TEX_DISPLAY.pattern + "|" + TEX_INLINE.pattern, re.S)
    for m in pattern.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        if m.group(1) is not None:
            out.append(f'<span class="tex-display">{esc(m.group(1))}</span>')
        else:
            out.append(f'<span class="tex-inline">{esc(m.group(2))}</span>')
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def norm_site_path(url: str) -> str | None:
    """Return a root-relative path if url points to the old site (directly or via Jetpack CDN)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https", ""):
        return None
    host = parts.netloc.lower()
    path = parts.path
    if JETPACK_CDN.match(host):
        segs = path.lstrip("/").split("/", 1)
        if len(segs) == 2 and segs[0] in SITE_HOSTS:
            return "/" + segs[1]
        return None
    if host in SITE_HOSTS:
        return path or "/"
    return None


class Sanitizer(HTMLParser):
    def __init__(self, post_id: int, used_files: set[str], mirror: Path):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.post_id = post_id
        self.used = used_files
        self.mirror = mirror
        self.skip_depth = 0  # inside <script> that we replaced
        self.text_buf: list[str] = []

    def flush_text(self):
        if self.text_buf:
            self.out.append(tex_markup("".join(self.text_buf)))
            self.text_buf = []

    def fail(self, msg: str):
        raise ImportError_(f"post {self.post_id}: {msg}")

    def rewrite_href(self, href: str) -> str:
        href = href.strip()
        scheme = urllib.parse.urlsplit(href).scheme.lower()
        if scheme not in ("http", "https", "mailto"):
            self.fail(f"disallowed href scheme: {href!r}")
        path = norm_site_path(href)
        if path is None:
            return href  # external link, kept as-is
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
        if path in ("/", "/index.php") and "p" in q:
            pid = int(q["p"][0])
            if pid not in SLUGS:
                self.fail(f"link to unknown post id {pid}")
            return f"/posts/{SLUGS[pid]}/"
        if path.startswith("/uploads/") or path.startswith("/wp-content/uploads/"):
            self.used.add(urllib.parse.unquote(path))
            return path
        self.fail(f"unhandled internal link: {href!r}")
        return ""

    def rewrite_src(self, src: str) -> str:
        path = norm_site_path(src.strip())
        if path is None or not path.startswith("/wp-content/uploads/"):
            self.fail(f"image not from the old site's uploads: {src!r}")
        real = urllib.parse.unquote(path)
        if not inside(self.mirror, real).is_file():
            self.fail(f"image missing in mirror: {real}")
        self.used.add(real)
        return path

    def handle_starttag(self, tag, attrs):
        self.flush_text()
        if self.skip_depth:
            self.fail("nested tag inside replaced script")
        if tag == "script":
            a = dict(attrs)
            if "speakerdeck-embed" in (a.get("class") or "") and a.get("data-id") in SPEAKERDECK:
                name, url, title = SPEAKERDECK[a["data-id"]]
                img = f"/images/slides/{name}.jpg"
                self.out.append(
                    f'<figure class="slide-preview"><a href="{html.escape(url)}" rel="noopener noreferrer">'
                    f'<img src="{img}" alt="{html.escape(title)}（スライド表紙）" width="1024" height="731" loading="lazy"></a>'
                    f'<figcaption><a href="{html.escape(url)}" rel="noopener noreferrer">Speaker Deck で全スライドを見る</a></figcaption></figure>')
                self.skip_depth = 1
                return
            self.fail(f"script tag: {attrs!r}")
        if tag not in ALLOWED_TAGS:
            self.fail(f"disallowed tag <{tag}>")
        kept: list[tuple[str, str]] = []
        classes: list[str] = []
        for k, v in attrs:
            k = k.lower()
            v = v or ""
            if k.startswith("on"):
                self.fail(f"event handler attribute {k}")
            if k == "style":
                c = STYLE_TO_CLASS.get(v.strip())
                if c:
                    classes.append(c)
                continue
            if k in DROP_ATTRS:
                continue
            if k == "class":
                classes.extend(c for c in v.split() if c in ALLOWED_CLASSES)
                continue
            if k not in KEEP_ATTRS.get(tag, set()):
                self.fail(f"disallowed attribute <{tag} {k}>")
            if k == "href":
                v = self.rewrite_href(v)
            elif k == "src":
                v = self.rewrite_src(v)
            elif k in ("width", "height") and not v.isdigit():
                self.fail(f"non-numeric {k}={v!r}")
            elif k == "scope":
                v = {"cols": "col", "rows": "row"}.get(v, v)  # typo in the original posts
                if v not in ("row", "col"):
                    self.fail(f"bad scope {v!r}")
            kept.append((k, v))
        if tag == "span" and dict(attrs).get("id", "").startswith("more-"):
            self.out.append("<!--more-->")
            self.stack.append("__more__")
            return
        if classes:
            kept.insert(0, ("class", " ".join(dict.fromkeys(classes))))
        if tag == "img":
            kept.append(("loading", "lazy"))
        if tag == "a" and urllib.parse.urlsplit(dict(kept).get("href", "")).scheme in ("http", "https"):
            kept.append(("rel", "noopener noreferrer"))
        attr_s = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in kept)
        self.out.append(f"<{tag}{attr_s}>")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        self.flush_text()
        if self.skip_depth:
            if tag != "script":
                self.fail("unexpected end tag inside script")
            self.skip_depth = 0
            return
        if tag in VOID_TAGS:
            return
        if tag == "p" and "p" not in self.stack:
            return  # wpautop artifact: stray </p> with no open <p> (e.g. after .box-title) - harmless, dropped
        if not self.stack:
            self.fail(f"stray </{tag}>")
        top = self.stack.pop()
        if tag in ("td", "th") and top in ("td", "th"):
            tag = top  # original posts close <th> with </td>; browsers treat it as closing the cell
        if top == "__more__":
            if tag != "span":
                self.fail("bad more-span nesting")
            return
        if top != tag:
            self.fail(f"mismatched </{tag}> (open: {top})")
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.skip_depth:
            if data.strip():
                self.fail("inline script body")
            return
        self.text_buf.append(data)

    def handle_comment(self, data):
        self.flush_text()
        if data.strip() == "more":
            self.out.append("<!--more-->")
        # all other comments are dropped

    def handle_decl(self, decl):
        self.fail("doctype/declaration in content")

    def handle_pi(self, data):
        self.fail("processing instruction in content")

    def unknown_decl(self, data):
        self.fail("CDATA/unknown declaration in content")

    def result(self) -> str:
        self.flush_text()
        if self.stack:
            self.fail(f"unclosed tags: {self.stack}")
        return "".join(self.out)


def sanitize(content: str, post_id: int, used: set[str], mirror: Path) -> str:
    # The Speaker Deck <script> sits in <div style="width: 80%;"> - drop that wrapper div.
    content = re.sub(r'<div style="width: 80%;">(\s*<script[^>]*speakerdeck-embed[^>]*></script>\s*)</div>',
                     r"\1", content)
    # Two posts open <thead> inside <tbody>; restore the structure browsers infer anyway.
    if re.search(r"<tbody>\s*<thead>", content):
        content = re.sub(r"<tbody>\s*<thead>", "<thead>", content)
        content = content.replace("</thead>", "</thead>\n<tbody>")
    s = Sanitizer(post_id, used, mirror)
    s.feed(content)
    s.close()
    out = s.result()
    out = re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"
    return out


def toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def front_matter(**kv) -> str:
    lines = ["+++"]
    for k, v in kv.items():
        if v is None:
            continue
        lines.append(f"{k} = {v if isinstance(v, (int, bool)) and not isinstance(v, str) else toml_str(str(v))}")
    lines.append("+++")
    return "\n".join(lines) + "\n"


def main():
    export, repo, pdf_map_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    mirror = export / "site_mirror"
    posts = json.load(open(export / "posts.json", encoding="utf-8"))
    pages = json.load(open(export / "pages.json", encoding="utf-8"))
    pdf_map = json.load(open(pdf_map_file, encoding="utf-8"))
    used: set[str] = set()

    if {p["id"] for p in posts} != set(SLUGS):
        raise ImportError_("post id set changed; update SLUGS")

    out_posts = repo / "content" / "posts"
    out_posts.mkdir(parents=True, exist_ok=True)
    for p in posts:
        if p["status"] != "publish" or p["type"] != "post":
            raise ImportError_(f"unexpected post {p['id']} status/type")
        body = sanitize(p["content"]["rendered"], p["id"], used, mirror)
        fm = front_matter(
            title=html.unescape(p["title"]["rendered"]),
            date=p["date"] + "+09:00",
            lastmod=p["modified"] + "+09:00",
            slug=SLUGS[p["id"]],
            wp_id=p["id"],
        )
        (out_posts / f"{SLUGS[p['id']]}.html").write_text(fm + "\n" + body, encoding="utf-8")

    for pg in pages:
        body = sanitize(pg["content"]["rendered"], pg["id"], used, mirror)
        fm = front_matter(
            title=html.unescape(pg["title"]["rendered"]),
            date=pg["date"] + "+09:00",
            lastmod=pg["modified"] + "+09:00",
            url=f"/{PAGE_SLUGS[pg['id']]}/",
            wp_id=pg["id"],
        )
        (repo / "content" / f"{PAGE_SLUGS[pg['id']]}.html").write_text(fm + "\n" + body, encoding="utf-8")

    # Copy only referenced uploads (+ the original of each referenced image), strip metadata.
    static = repo / "static"
    media = json.load(open(export / "media.json", encoding="utf-8"))
    originals = {}
    for m in media:
        orig = norm_site_path(m["source_url"])
        for size in ((m.get("media_details") or {}).get("sizes") or {}).values():
            originals[urllib.parse.unquote(norm_site_path(size["source_url"]))] = urllib.parse.unquote(orig)
        originals[urllib.parse.unquote(orig)] = urllib.parse.unquote(orig)
    extra = {"/wp-content/uploads/2017/06/toppage_02.jpg", "/wp-content/uploads/2017/06/cropped-favicon0004.png"}
    to_copy = set()
    for path in used | extra:
        if path.startswith("/uploads/") and path.endswith(".pdf"):
            continue  # PDFs handled below
        to_copy.add(path)
        if path in originals:
            to_copy.add(originals[path])
    copied = []
    for path in sorted(to_copy):
        src = inside(mirror, path)
        if path.startswith("/uploads/"):  # old /uploads/ alias of /wp-content/uploads/
            src = inside(mirror, "/wp-content" + path)
        data = src.read_bytes()
        if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
            raise ImportError_(f"not a PNG/JPEG: {path}")
        dst = inside(static, path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied.append(dst)
    subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-all=", "--icc_profile:all", *map(str, copied)], check=True)

    # PDFs: restore from the owner's local originals (paths given in pdf_map: url path -> local file).
    for url_path, local in pdf_map.items():
        if url_path not in used:
            raise ImportError_(f"PDF not referenced by content: {url_path}")
        dst = inside(static, url_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, dst)
    missing_pdfs = {u for u in used if u.startswith("/uploads/") and u.endswith(".pdf")} - set(pdf_map)
    if missing_pdfs:
        raise ImportError_(f"referenced PDFs without a local original: {missing_pdfs}")

    # Slide previews: the cover image of each Speaker Deck (downloaded once into the export dir,
    # self-hosted so visitors never contact Speaker Deck unless they click through).
    slides = static / "images" / "slides"
    slides.mkdir(parents=True, exist_ok=True)
    thumbs = []
    for name, _url, _title in SPEAKERDECK.values():
        src = export / "speakerdeck_thumbs" / f"{name}.jpg"
        if not src.read_bytes().startswith(b"\xff\xd8\xff"):
            raise ImportError_(f"slide thumbnail is not a JPEG: {src}")
        dst = slides / f"{name}.jpg"
        shutil.copyfile(src, dst)
        thumbs.append(dst)
    subprocess.run(["exiftool", "-q", "-q", "-overwrite_original", "-all=", "--icc_profile:all", *map(str, thumbs)], check=True)

    # Legacy query-string redirect table (consumed by static/js/legacy-redirect.js).
    table = {str(pid): f"/posts/{slug}/" for pid, slug in sorted(SLUGS.items())}
    js = (repo / "assets" / "js" / "legacy-redirect.js")
    js.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(LEGACY_JS.replace("__TABLE__", json.dumps(table, indent=2)), encoding="utf-8")

    print(f"posts={len(posts)} pages={len(pages)} images={len(copied)} pdfs={len(pdf_map)} slides={len(thumbs)}")


LEGACY_JS = """// Redirects old WordPress query-string URLs (/?p=473, /?page_id=11, /?m=201710) to the new
// static URLs. Destinations come ONLY from the fixed table below; no part of the query string is
// ever used as a destination or written into the page.
(function () {
  "use strict";
  var POSTS = __TABLE__;
  var search = window.location.search;
  if (!search || window.location.pathname !== "/") { return; }
  var params = new URLSearchParams(search);
  var dest = null;
  var p = params.get("p");
  var pageId = params.get("page_id");
  var m = params.get("m");
  if (p !== null && Object.prototype.hasOwnProperty.call(POSTS, p)) {
    dest = POSTS[p];
  } else if (pageId === "11") {
    dest = "/profile/";
  } else if (m !== null && /^20[0-9]{4}$/.test(m)) {
    dest = "/archives/#m" + m;
  }
  if (dest !== null) { window.location.replace(dest); }
}());
"""

if __name__ == "__main__":
    try:
        main()
    except ImportError_ as e:
        print(f"IMPORT FAILED: {e}", file=sys.stderr)
        sys.exit(1)

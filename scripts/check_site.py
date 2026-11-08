#!/usr/bin/env python3
"""Post-build safety check for the generated site (run in CI before deploying).

Usage: python3 -I scripts/check_site.py public

Fails (exit 1) if the output contains anything this static site should never contain:
  - any <script> other than the single legacy-redirect script on the home page
  - event-handler attributes, inline styles, <style>, iframes/objects/forms/base, etc.
  - javascript:/data:/vbscript: URLs
  - sub-resources (img/script/stylesheet/icon) loaded from another origin
  - pages that do not START with <!doctype html><html><head><meta charset><meta CSP> (so the CSP
    is guaranteed to be inside the real <head> and to precede everything else), or that carry a
    second CSP / <head>
  - duplicate attributes (browsers use the first, a dict-based checker would see the last)
  - XML other than the RSS feed and sitemap, or with unexpected elements/attributes/markup
  - internal links that do not resolve to a generated file
  - file types that are not plain static content (e.g. .php, .htaccess, .svg, extra .js)
Standard library only.
"""
from __future__ import annotations

import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

SITE = "okiyamasho.com"
CSP_COMMON = "default-src 'none'; script-src {s}; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'"
ALLOWED_EXT = {".html", ".xml", ".css", ".js", ".png", ".jpg", ".jpeg", ".pdf", ".txt"}
FORBIDDEN_TAGS = {"iframe", "frame", "frameset", "object", "embed", "applet", "form", "input", "button",
                  "textarea", "select", "base", "style", "svg", "template", "portal", "video",
                  "audio", "source", "track", "noscript", "maction", "mglyph", "malignmark"}
# MathML produced at build time by Hugo's KaTeX (layouts/partials/render-math.html). Only these
# presentation elements/attributes are accepted inside <math>; anything else (href, xlink, etc.) fails.
MATHML_TAGS = {"math", "semantics", "annotation", "mrow", "mi", "mn", "mo", "ms", "mtext", "mspace",
               "msup", "msub", "msubsup", "mfrac", "msqrt", "mroot", "mover", "munder", "munderover",
               "mtable", "mtr", "mtd", "mstyle", "mpadded", "mphantom", "menclose"}
MATHML_ATTRS = {"xmlns", "display", "encoding", "fence", "lspace", "rspace", "mathvariant", "stretchy",
                "displaystyle", "scriptlevel", "columnalign", "columnspacing", "rowspacing", "separator",
                "width", "height", "depth", "linethickness", "accent", "accentunder", "notation",
                "minsize", "maxsize", "movablelimits", "symmetric", "largeop", "voffset", "class"}
URL_ATTRS = {"href", "src", "action", "formaction", "poster", "srcset", "data", "cite", "background", "xlink:href"}
BAD_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")
REDIRECT_JS = re.compile(r"^/js/legacy-redirect\.min\.[0-9a-f]{96}\.js$")
# Minified Hugo output: <!doctype html><html lang=ja><head><meta charset=utf-8><meta http-equiv=Content-Security-Policy content="...">
PREFIX = re.compile(
    r"""\A<!doctype html><html lang=["']?ja["']?><head><meta charset=["']?utf-8["']?>"""
    r"""<meta http-equiv=["']?Content-Security-Policy["']? content="(?P<csp>[^"<>]*)">""",
    re.IGNORECASE)
# XML: only these files, elements and attributes.
XML_RULES = {
    "/index.xml": {
        "elements": {"rss", "channel", "title", "link", "description", "language", "lastBuildDate",
                     "{http://www.w3.org/2005/Atom}link", "item", "pubDate", "guid"},
        "attrs": {("rss", "version"), ("{http://www.w3.org/2005/Atom}link", "href"),
                  ("{http://www.w3.org/2005/Atom}link", "rel"), ("{http://www.w3.org/2005/Atom}link", "type")},
        "root": "rss",
    },
    "/sitemap.xml": {
        "elements": {"{http://www.sitemaps.org/schemas/sitemap/0.9}" + t for t in ("urlset", "url", "loc", "lastmod")},
        "attrs": set(),
        "root": "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset",
    },
}

errors: list[str] = []


def err(path: Path, msg: str):
    errors.append(f"{path}: {msg}")


class PageChecker(HTMLParser):
    def __init__(self, root: Path, path: Path, is_home: bool):
        super().__init__(convert_charrefs=True)
        self.root, self.path, self.is_home = root, path, is_home
        self.in_head = False
        self.head_elems: list[tuple[str, dict]] = []
        self.scripts: list[dict] = []
        self.in_script = False
        self.internal_links: set[str] = set()
        self.math_depth = 0
        self.head_count = 0
        self.csp_count = 0

    def handle_starttag(self, tag, attrs):
        names = [k.lower() for k, _ in attrs]
        if len(names) != len(set(names)):
            err(self.path, f"duplicate attribute on <{tag}>: {sorted(n for n in set(names) if names.count(n) > 1)}")
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "head":
            self.head_count += 1
        if tag == "meta" and a.get("http-equiv", "").lower() == "content-security-policy":
            self.csp_count += 1
        if tag == "span" and a.get("class", "").startswith("tex-"):
            err(self.path, "unrendered TeX marker (render-math partial not applied)")
        if tag == "head":
            self.in_head = True
        if self.in_head and tag != "head":
            self.head_elems.append((tag, a))
        if tag in FORBIDDEN_TAGS:
            err(self.path, f"forbidden tag <{tag}>")
        if tag == "math":
            self.math_depth += 1
            if a.get("xmlns", "http://www.w3.org/1998/Math/MathML") != "http://www.w3.org/1998/Math/MathML":
                err(self.path, "unexpected MathML namespace")
        if self.math_depth:
            if tag not in MATHML_TAGS:
                err(self.path, f"unexpected element <{tag}> inside <math>")
            for k in a:
                if k not in MATHML_ATTRS:
                    err(self.path, f"unexpected attribute {k} on MathML <{tag}>")
            if tag == "annotation" and a.get("encoding") != "application/x-tex":
                err(self.path, "MathML annotation that is not TeX")
        elif tag in MATHML_TAGS:
            err(self.path, f"MathML element <{tag}> outside <math>")
        if tag == "meta" and a.get("http-equiv", "").lower() == "refresh":
            err(self.path, "meta refresh")
        for k, v in a.items():
            if k.startswith("on"):
                err(self.path, f"event handler attribute {k} on <{tag}>")
            if k == "style":
                err(self.path, f"inline style attribute on <{tag}>")
            if k in URL_ATTRS:
                vv = re.sub(r"\s+", "", v).lower()
                if vv.startswith(BAD_SCHEMES):
                    err(self.path, f"dangerous URL scheme in {k}: {v[:60]!r}")
        if tag == "script":
            self.scripts.append(a)
            self.in_script = True
            src = a.get("src", "")
            if not self.is_home:
                err(self.path, "script on a non-home page")
            if not REDIRECT_JS.match(src):
                err(self.path, f"unexpected script src {src!r}")
            if not a.get("integrity", "").startswith("sha384-"):
                err(self.path, "script without SRI integrity")
        # Sub-resources must be same-origin, root-relative.
        sub = None
        if tag in ("img", "script"):
            sub = a.get("src")
            if tag == "img" and not sub:
                err(self.path, "img without src")
            if "srcset" in a:
                err(self.path, "srcset not expected")
        if tag == "link" and a.get("rel", "").lower() in ("stylesheet", "icon", "apple-touch-icon", "preload", "modulepreload", "prefetch", "manifest"):
            sub = a.get("href")
        if sub is not None:
            if not sub.startswith("/") or sub.startswith("//"):
                err(self.path, f"sub-resource not same-origin root-relative: <{tag}> {sub!r}")
            else:
                self.internal_links.add(sub)
        if tag == "a":
            href = a.get("href", "")
            parts = urllib.parse.urlsplit(href)
            if href.startswith("/") and not href.startswith("//"):
                self.internal_links.add(href)
            elif parts.netloc in (SITE, "www." + SITE):
                self.internal_links.add(parts.path or "/")
            elif parts.scheme not in ("http", "https", "mailto", ""):
                err(self.path, f"unexpected link scheme {href!r}")
            if parts.scheme in ("http", "https") and parts.netloc not in (SITE, "www." + SITE):
                rel = set(a.get("rel", "").split())
                if not {"noopener", "noreferrer"} <= rel:
                    err(self.path, f"external link without rel=noopener noreferrer: {href[:60]}")

    def handle_endtag(self, tag):
        if tag == "math" and self.math_depth:
            self.math_depth -= 1
        if tag == "head":
            self.in_head = False
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script and data.strip():
            err(self.path, "inline script content")

    def handle_comment(self, data):
        if "[if" in data.lower():
            err(self.path, "conditional comment")


def resolve(root: Path, url_path: str) -> bool:
    p = urllib.parse.unquote(urllib.parse.urlsplit(url_path).path)
    if ".." in p.split("/"):
        return False
    target = root / p.lstrip("/")
    if p.endswith("/"):
        return (target / "index.html").is_file()
    return target.is_file() or (target / "index.html").is_file()


def check_html(root: Path, path: Path):
    rel = "/" + path.relative_to(root).as_posix()
    is_home = rel == "/index.html"
    text = path.read_text(encoding="utf-8")
    c = PageChecker(root, path, is_home)
    c.feed(text)
    c.close()
    # The document must literally start with doctype, <html>, <head>, <meta charset>, CSP meta.
    # Only then is the CSP guaranteed (per the HTML parsing rules) to sit in the real <head>
    # before any other element. Exactly one <head> and one CSP meta are allowed.
    expected = CSP_COMMON.format(s="'self'" if is_home else "'none'")
    m = PREFIX.match(text)
    if not m:
        err(path, "page does not start with doctype/html/head/meta charset/CSP meta")
    elif m.group("csp") != expected:
        err(path, f"CSP differs from the expected policy: {m.group('csp')!r}")
    if c.head_count != 1:
        err(path, f"expected exactly one <head>, found {c.head_count}")
    if c.csp_count != 1:
        err(path, f"expected exactly one CSP meta, found {c.csp_count}")
    heads = c.head_elems
    if is_home and len(c.scripts) != 1:
        err(path, f"home page must have exactly 1 script, found {len(c.scripts)}")
    if not any(t == "meta" and a.get("name") == "referrer" for t, a in heads):
        err(path, "referrer meta missing")
    for link in c.internal_links:
        if not resolve(root, link):
            err(path, f"broken internal link {link}")


def check_xml(root: Path, path: Path):
    # Input is our own Hugo output (RSS/sitemap), not third-party XML; expat in current Python
    # does not fetch external entities and limits entity expansion, so stdlib ElementTree is fine here.
    rel = "/" + path.relative_to(root).as_posix()
    rules = XML_RULES.get(rel)
    if rules is None:
        err(path, "unexpected XML file (only /index.xml and /sitemap.xml are published)")
        return
    raw = path.read_text(encoding="utf-8")
    if "<!DOCTYPE" in raw.upper() or "<!ENTITY" in raw.upper():
        err(path, "DOCTYPE/ENTITY in XML")
        return
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        err(path, f"XML parse error: {e}")
        return
    if tree.getroot().tag != rules["root"]:
        err(path, f"unexpected XML root {tree.getroot().tag}")
    for el in tree.iter():
        if el.tag not in rules["elements"]:
            err(path, f"unexpected XML element {el.tag}")
        for k in el.attrib:
            if (el.tag, k) not in rules["attrs"]:
                err(path, f"unexpected XML attribute {k} on {el.tag}")
        text = (el.text or "") + (el.tail or "")
        if "<" in text or ">" in text:
            err(path, f"markup inside XML text of {el.tag} (feeds/sitemap must be plain text)")
        if el.tag in ("link", "guid", "{http://www.sitemaps.org/schemas/sitemap/0.9}loc") and el.text:
            if not el.text.startswith(f"https://{SITE}/"):
                err(path, f"URL outside the site in {el.tag}: {el.text[:60]}")


def check_js(root: Path, path: Path):
    rel = "/" + path.relative_to(root).as_posix()
    if not REDIRECT_JS.match(rel):
        err(path, "unexpected JavaScript file")
        return
    src = path.read_text(encoding="utf-8")
    # These strings are what we search FOR (the redirect script must not contain them).
    for bad in ("eval(", "Function(", "innerHTML", "outerHTML", "document.write", "insertAdjacentHTML",
                "fetch(", "XMLHttpRequest", "import(", "localStorage", "cookie"):
        if bad in src:
            err(path, f"forbidden API in redirect script: {bad}")


def main():
    root = Path(sys.argv[1]).resolve()
    if not (root / "index.html").is_file():
        print("no index.html - wrong directory?", file=sys.stderr)
        sys.exit(2)
    n = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            err(path, "symlink in output")
            continue
        if not path.is_file():
            continue
        n += 1
        name = path.name.lower()
        ext = path.suffix.lower()
        if name.startswith(".") or ext not in ALLOWED_EXT:
            err(path, f"file type not allowed in the published site ({ext or name})")
            continue
        if ext == ".html":
            check_html(root, path)
        elif ext == ".xml":
            check_xml(root, path)
        elif ext == ".js":
            check_js(root, path)
        elif ext in (".png", ".jpg", ".jpeg"):
            head = path.read_bytes()[:8]
            if not (head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff")):
                err(path, "image extension but not PNG/JPEG data")
        elif ext == ".pdf":
            if not path.read_bytes()[:5] == b"%PDF-":
                err(path, "not a PDF")
    if errors:
        print(f"check_site: {len(errors)} problem(s) in {n} files", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        sys.exit(1)
    print(f"check_site: OK ({n} files)")


if __name__ == "__main__":
    main()

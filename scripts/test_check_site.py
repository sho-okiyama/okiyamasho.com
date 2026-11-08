#!/usr/bin/env python3
"""Regression tests for scripts/check_site.py: each case injects one dangerous change into a copy
of the built site and asserts that the checker rejects it; the untouched copy must pass.

Usage: python3 -I scripts/test_check_site.py public
Standard library only.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_site.py"


def sub(rel: str, pattern: str, repl: str, count: int = 1):
    def apply(root: Path):
        f = root / rel
        s = f.read_text(encoding="utf-8")
        new, n = re.subn(pattern, repl, s, count=count)
        assert n, f"test setup: pattern {pattern!r} not found in {rel}"
        f.write_text(new, encoding="utf-8")
    return apply


def write(rel: str, data: str):
    def apply(root: Path):
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(data, encoding="utf-8")
    return apply


POST = "posts/20170626/index.html"
MATH_POST = "posts/20170830/index.html"
CASES = {
    "event handler attribute": sub(POST, r"<p>", "<p onclick=alert(1)>"),
    "inline script on a non-home page": sub("profile/index.html", r"</body>", "<script>alert(1)</script></body>"),
    "external image": sub("archives/index.html", r"</body>", "<img src=https://evil.example/x.png></body>"),
    "javascript: link": sub("404.html", r"</body>", "<a href=javascript:alert(1)>x</a></body>"),
    "javascript: link with whitespace": sub("404.html", r"</body>", "<a href=\" java\tscript:alert(1)\">x</a></body>"),
    "iframe": sub("posts/index.html", r"</body>", "<iframe src=/x></iframe></body>"),
    "broken internal link": sub("profile/index.html", r"</body>", "<a href=/posts/nope/>x</a></body>"),
    "php file": write("wp-login.php", "<?php system($_GET[1]);"),
    "dotfile": write(".htaccess", "x"),
    "extra javascript file": write("js/evil.js", "alert(1)"),
    "weakened CSP": sub("profile/index.html", r"script-src 'none'", "script-src *"),
    "duplicate CSP content attribute": sub("index.html", r"<meta http-equiv=Content-Security-Policy content=",
                                           "<meta http-equiv=Content-Security-Policy content=\"default-src *\" content="),
    "duplicate script src": sub("index.html", r"<script src=", "<script src=https://attacker.invalid/p.js src="),
    "CSP pushed out of the real head": sub("index.html", r"<head>", "<body><div>early</div><head>"),
    "second CSP meta": sub("profile/index.html", r"</head>", "<meta http-equiv=Content-Security-Policy content=\"script-src *\"></head>"),
    "XHTML with script in an extra .xml": write("evil.xml", "<html xmlns=\"http://www.w3.org/1999/xhtml\"><script>alert(1)</script></html>"),
    "markup in RSS text": sub("index.xml", r"<title>", "<title>&lt;script&gt;"),
    "foreign URL in RSS": sub("index.xml", r"<link>https://okiyamasho\.com/", "<link>https://evil.example/"),
    "xml-stylesheet PI in RSS": sub("index.xml", r"<rss ", "<?xml-stylesheet type=\"text/css\" href=\"https://evil.example/t.css\"?><rss "),
    "xml-stylesheet PI in sitemap": sub("sitemap.xml", r"<urlset ", "<?xml-stylesheet type=\"text/xsl\" href=\"https://evil.example/t.xsl\"?><urlset "),
    "href inside MathML": sub(MATH_POST, r"<mi>", "<mi href=\"https://evil.example\">"),
    "img inside MathML": sub(MATH_POST, r"<mrow>", "<mrow><img src=/x.png>"),
    "unrendered TeX marker": sub("profile/index.html", r"<p>", "<p><span class=\"tex-inline\">x</span>"),
    "external link without rel": sub("profile/index.html", r"</body>", "<a href=https://example.com/>x</a></body>"),
    "meta refresh": sub("profile/index.html", r"</head>", "<meta http-equiv=refresh content=\"0;url=https://evil.example\"></head>"),
    "svg file": write("x.svg", "<svg xmlns=\"http://www.w3.org/2000/svg\" onload=\"alert(1)\"/>"),
    "png name but html content": write("wp-content/uploads/evil.png", "<script>alert(1)</script>"),
}


def run_checker(root: Path) -> int:
    return subprocess.run([sys.executable, "-I", str(CHECKER), str(root)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def main():
    public = Path(sys.argv[1]).resolve()
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean"
        shutil.copytree(public, clean)
        if run_checker(clean) != 0:
            failures.append("clean build is rejected (expected to pass)")
        for name, mutate in CASES.items():
            root = Path(tmp) / re.sub(r"\W+", "_", name)
            shutil.copytree(public, root)
            mutate(root)
            if run_checker(root) == 0:
                failures.append(f"NOT DETECTED: {name}")
    if failures:
        print("test_check_site: FAILED", file=sys.stderr)
        for f in failures:
            print("  - " + f, file=sys.stderr)
        sys.exit(1)
    print(f"test_check_site: OK (clean build passes, {len(CASES)} injected problems all rejected)")


if __name__ == "__main__":
    main()

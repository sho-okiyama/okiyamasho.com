// Regression test for the legacy-redirect script (old WordPress ?p=/page_id=/m= URLs).
// Usage: node scripts/test_redirect.js public/js/legacy-redirect.min.*.js
// Runs the built script against a fake window: known IDs must go to their fixed new URL,
// anything else (unknown IDs, prototype names, URLs, injection attempts) must not redirect.
const fs = require("fs");
const code = fs.readFileSync(process.argv[2], "utf8");
function run(pathname, search) {
  let dest = null;
  const window = { location: { pathname, search, replace: (u) => { dest = u; } } };
  new Function("window", "URLSearchParams", code)(window, URLSearchParams);
  return dest;
}
const cases = [
  ["/", "?p=473", "/posts/20171012/"],
  ["/", "?p=435", "/posts/20170929/"],
  ["/", "?p=404", "/posts/20170830/"],
  ["/", "?p=397", "/posts/20170819/"],
  ["/", "?p=359", "/posts/20170808/"],
  ["/", "?p=330", "/posts/20170728/"],
  ["/", "?p=302", "/posts/20170717/"],
  ["/", "?p=277", "/posts/20170626/"],
  ["/", "?p=230", "/posts/20170621/"],
  ["/", "?p=264", "/posts/20170619/"],
  ["/", "?p=122", "/posts/20170613/"],
  ["/", "?p=46", "/posts/20170610/"],
  ["/", "?page_id=11", "/profile/"],
  ["/", "?m=201710", "/archives/#m201710"],
  ["/", "?p=473&utm_source=x", "/posts/20171012/"],
  ["/", "?p=999", null],
  ["/", "?p=__proto__", null],
  ["/", "?p=constructor", null],
  ["/", "?p=hasOwnProperty", null],
  ["/", "?p=473%0a", null],
  ["/", "?p=https://evil.example", null],
  ["/", "?page_id=12", null],
  ["/", "?m=2017101", null],
  ["/", "?m=abc", null],
  ["/", "?m=201710%22%3E", null],
  ["/", "?cat=1", null],
  ["/", "", null],
  ["/posts/", "?p=473", null],
];
let fail = 0;
for (const [p, s, want] of cases) {
  const got = run(p, s);
  const ok = got === want;
  if (!ok) fail++;
  console.log(`${ok ? "OK  " : "FAIL"} ${p}${s} -> ${got}`);
}
console.log(fail ? `${fail} FAILED` : "all passed");
process.exit(fail ? 1 : 0);

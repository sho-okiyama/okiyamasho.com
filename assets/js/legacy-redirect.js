// Redirects old WordPress query-string URLs (/?p=473, /?page_id=11, /?m=201710) to the new
// static URLs. Destinations come ONLY from the fixed table below; no part of the query string is
// ever used as a destination or written into the page.
(function () {
  "use strict";
  var POSTS = {
  "46": "/posts/introduction/",
  "122": "/posts/learn-from-the-present/",
  "230": "/posts/technology-grows-by-itself/",
  "264": "/posts/medicine-ai-quantum-blockchain/",
  "277": "/posts/visualizing-4d/",
  "302": "/posts/era-of-analog-computers/",
  "330": "/posts/is-math-useful-in-society/",
  "359": "/posts/lifespan-grows-every-year/",
  "397": "/posts/understanding-ai-from-scratch/",
  "404": "/posts/how-ai-plays-go/",
  "435": "/posts/nationality-as-a-parameter/",
  "473": "/posts/exponential-technologies-and-the-future/"
};
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

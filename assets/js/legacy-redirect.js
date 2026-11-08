// Redirects old WordPress query-string URLs (/?p=473, /?page_id=11, /?m=201710) to the new
// static URLs. Destinations come ONLY from the fixed table below; no part of the query string is
// ever used as a destination or written into the page.
(function () {
  "use strict";
  var POSTS = {
  "46": "/posts/20170610/",
  "122": "/posts/20170613/",
  "230": "/posts/20170621/",
  "264": "/posts/20170619/",
  "277": "/posts/20170626/",
  "302": "/posts/20170717/",
  "330": "/posts/20170728/",
  "359": "/posts/20170808/",
  "397": "/posts/20170819/",
  "404": "/posts/20170830/",
  "435": "/posts/20170929/",
  "473": "/posts/20171012/"
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

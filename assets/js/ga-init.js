// Google Analytics 4 bootstrap (the loader gtag/js is included separately, async).
// The measurement ID comes from hugo.toml (params.ga4) via resources.ExecuteAsTemplate.
window.dataLayer = window.dataLayer || [];
function gtag() { window.dataLayer.push(arguments); }
gtag("js", new Date());
gtag("config", "{{ .id }}");

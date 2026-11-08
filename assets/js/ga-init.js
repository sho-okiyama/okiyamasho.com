// Google Analytics 4 bootstrap (the loader gtag/js is included separately, async).
// The measurement ID comes from hugo.toml (params.ga4) via resources.ExecuteAsTemplate.
window.dataLayer = window.dataLayer || [];
function gtag() { window.dataLayer.push(arguments); }
gtag("js", new Date());
// Google Signals / ad personalisation are off: page-view analytics only, no doubleclick or
// ga-audiences requests (keeps the CSP narrow and sends less data to ad systems).
gtag("config", "{{ .id }}", { allow_google_signals: false, allow_ad_personalization_signals: false });

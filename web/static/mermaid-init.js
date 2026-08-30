// Draws the ```mermaid fences that md_html leaves alone.
//
// Server-side, chroma has no mermaid lexer and language guessing is off, so
// those fences fall through to goldmark's plain renderer as
// <pre><code class="language-mermaid">. This file finds them, swaps each one
// for a <div class="mermaid">, and hands them to mermaid.
//
// mermaid.min.js is 2.5MB, so it is fetched only once a page actually contains
// a diagram — most issues have none. It is vendored (mermaid 11.4.1, MIT, from
// cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js) because the board is
// local-first and has to work with no network.
//
// Colors come from theme.css custom properties, so mermaid draws on DESIGN.md's
// tonal ladder instead of shipping a second palette.
(function () {
  var SELECTOR = "code.language-mermaid";
  var loading = false;
  var timer = null;

  function token(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return v.trim() || fallback;
  }

  function configure() {
    var surface = token("--bg-raised", "#191c20");
    var raised = token("--bg-hover", "#1d2126");
    var edge = token("--border-strong", "rgba(255,255,255,0.12)");
    var text = token("--text", "#e8eaed");
    var dim = token("--text-3", "#828994");
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      fontFamily: getComputedStyle(document.body).fontFamily,
      themeVariables: {
        darkMode: true,
        background: surface,
        primaryColor: raised,
        secondaryColor: surface,
        tertiaryColor: token("--bg-panel", "#141619"),
        mainBkg: raised,
        primaryTextColor: text,
        secondaryTextColor: text,
        tertiaryTextColor: text,
        textColor: text,
        titleColor: text,
        primaryBorderColor: edge,
        secondaryBorderColor: edge,
        tertiaryBorderColor: edge,
        nodeBorder: edge,
        lineColor: dim,
        edgeLabelBackground: surface,
        clusterBkg: surface,
        clusterBorder: edge,
        fontSize: "13px",
      },
    });
  }

  // Replace each <pre><code class="language-mermaid"> with the bare <div> that
  // mermaid renders into; the <pre> chrome would frame the finished diagram.
  function hoist() {
    var hosts = [];
    document.querySelectorAll(SELECTOR).forEach(function (code) {
      var host = document.createElement("div");
      host.className = "mermaid";
      host.textContent = code.textContent;
      var pre = code.closest("pre") || code;
      pre.replaceWith(host);
      hosts.push(host);
    });
    return hosts;
  }

  function draw() {
    if (!document.querySelector(SELECTOR)) return;
    if (!window.mermaid) {
      if (loading) return;
      loading = true;
      var s = document.createElement("script");
      s.src = "/static/mermaid.min.js";
      s.onload = draw;
      document.head.appendChild(s);
      return;
    }
    if (!window.mermaid.__lllConfigured) {
      configure();
      window.mermaid.__lllConfigured = true;
    }
    var hosts = hoist();
    if (hosts.length) window.mermaid.run({ nodes: hosts });
  }

  // SSE morphs replace descriptions and comments wholesale, which restores the
  // <pre><code class="language-mermaid"> markup, so redraw on DOM changes. The
  // guard above makes this terminate: mermaid's own output contains no
  // code.language-mermaid, so its mutations do not re-trigger a draw.
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(draw, 50);
  }

  function start() {
    new MutationObserver(schedule).observe(document.body, {
      childList: true,
      subtree: true,
    });
    draw();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();

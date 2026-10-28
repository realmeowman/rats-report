/* Lead tracker charts. Each page embeds its races and the weekend's game windows as JSON:
   <script type="application/json" id="race-data">{"segments":[...],"tz":"...","kick_utc":"...","races":{"<matchup_id>":{"w":rid,"l":rid,"pts":[[h,winnerPts,loserPts],...]}}}</script>
   and marks chart slots with <div data-race="<matchup_id>" data-persp="<roster_id>" data-mode="full|mini|thumb">. */
(function () {
  var el = document.getElementById("race-data");
  if (!el) return;
  var D = JSON.parse(el.textContent);
  var SEGS = D.segments.map(function (s) { return { a: s.start_h - 0.15, b: s.end_h + 0.15, lab: s.label }; });
  var dur = SEGS.map(function (s) { return Math.max(1.2, s.b - s.a); });
  var tot = dur.reduce(function (a, b) { return a + b; }, 0);
  SEGS.forEach(function (s, i) { s.w = dur[i] / tot; });
  var kick = Date.parse(D.kick_utc);

  function xmap(h, x0, W) {
    var gap = 6, x = x0, total = W - gap * (SEGS.length - 1);
    for (var i = 0; i < SEGS.length; i++) {
      var s = SEGS[i], sw = total * s.w;
      if (h <= s.b || i === SEGS.length - 1) {
        if (h < s.a) return x;
        return x + sw * Math.min(1, (h - s.a) / (s.b - s.a));
      }
      x += sw + gap;
    }
  }
  function fmt(h) {
    var d = new Date(kick + h * 3600e3);
    try {
      return d.toLocaleString("en-US", { timeZone: D.tz, weekday: "short", hour: "numeric", minute: "2-digit" }).toUpperCase();
    } catch (e) { return ""; }
  }
  function draw(slot) {
    var race = D.races[slot.getAttribute("data-race")];
    if (!race) return;
    var mode = slot.getAttribute("data-mode") || "full";
    var persp = +slot.getAttribute("data-persp");
    var flip = persp === race.l;
    var axis = mode !== "thumb";
    var W = mode === "full" ? 420 : mode === "mini" ? 340 : 118;
    var H = mode === "full" ? 260 : mode === "mini" ? 150 : 78;
    var L = axis ? 34 : 4, R = 6, T = axis ? 20 : 6, B = axis ? 22 : 6;
    var pts = race.pts.map(function (p) { return [p[0], flip ? p[2] - p[1] : p[1] - p[2]]; });
    var ext = Math.max.apply(null, [10].concat(pts.map(function (p) { return Math.abs(p[1]); })));
    var top = Math.ceil(ext / 20) * 20;
    function y(v) { return T + (H - T - B) * (top - v) / (2 * top); }
    function X(h) { return xmap(h, L, W - L - R); }
    var id = "c" + Math.random().toString(36).slice(2, 8);
    var d = "M" + X(pts[0][0]).toFixed(1) + "," + y(0).toFixed(1), line = "";
    pts.forEach(function (p, i) {
      var px = X(p[0]).toFixed(1), py = y(p[1]).toFixed(1);
      d += " L" + px + "," + py; line += (i ? " L" : "M") + px + "," + py;
    });
    d += " L" + X(pts[pts.length - 1][0]).toFixed(1) + "," + y(0).toFixed(1) + " Z";
    var g = '<defs><clipPath id="' + id + 'a"><rect x="0" y="0" width="' + W + '" height="' + y(0) + '"/></clipPath><clipPath id="' + id + 'b"><rect x="0" y="' + y(0) + '" width="' + W + '" height="' + H + '"/></clipPath></defs>';
    if (axis) {
      [top, top / 2, 0, -top / 2, -top].forEach(function (v) {
        g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '" stroke="var(--line)" stroke-width="' + (v === 0 ? 1.4 : .7) + '"/>';
        g += '<text x="' + (L - 5) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + (v > 0 ? "+" : "") + v + "</text>";
      });
      var x = L, total = W - L - R - 6 * (SEGS.length - 1);
      SEGS.forEach(function (s, i) {
        var sw = total * s.w;
        if (i) g += '<line x1="' + (x - 3) + '" x2="' + (x - 3) + '" y1="' + T + '" y2="' + (H - B) + '" stroke="var(--line)" stroke-dasharray="2 3"/>';
        g += '<text x="' + (x + sw / 2) + '" y="' + (H - 6) + '" text-anchor="middle">' + s.lab + "</text>";
        x += sw + 6;
      });
    } else {
      g += '<line x1="0" x2="' + W + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="var(--line)"/>';
    }
    g += '<path d="' + d + '" fill="var(--sand)" opacity=".28" clip-path="url(#' + id + 'a)"/>';
    g += '<path d="' + d + '" fill="var(--loss)" opacity=".28" clip-path="url(#' + id + 'b)"/>';
    g += '<path class="line" d="' + line + '" fill="none" stroke="var(--sand)" stroke-width="2" vector-effect="non-scaling-stroke" clip-path="url(#' + id + 'a)"/>';
    g += '<path class="line" d="' + line + '" fill="none" stroke="var(--loss)" stroke-width="2" vector-effect="non-scaling-stroke" clip-path="url(#' + id + 'b)"/>';
    var marks = mode === "full" ? ["low", "high", "end"] : mode === "mini" ? ["end"] : [];
    var done = {};
    marks.forEach(function (m) {
      var p;
      if (m === "high") p = pts.reduce(function (a, b) { return b[1] > a[1] ? b : a; });
      else if (m === "low") p = pts.reduce(function (a, b) { return b[1] < a[1] ? b : a; });
      else p = pts[pts.length - 1];
      if (p === pts[pts.length - 1]) m = "end";
      if (done[p[0]] || Math.abs(p[1]) < 0.01) return;
      done[p[0]] = 1;
      var px = X(p[0]), py = y(p[1]), v = (p[1] > 0 ? "+" : "") + p[1].toFixed(2);
      var anchor = px > W * 0.7 ? "end" : px < W * 0.3 ? "start" : "middle";
      var dx = anchor === "end" ? -6 : anchor === "start" ? 6 : 0;
      g += '<circle cx="' + px + '" cy="' + py + '" r="4" fill="var(--ink)"/>';
      var ty = py + (p[1] >= 0 ? -9 : 17);
      if (m === "end") { anchor = "end"; dx = -9; ty = py + 4; }
      g += '<text class="ann" x="' + (px + dx) + '" y="' + ty + '" text-anchor="' + anchor + '">' + v + (m !== "end" ? " · " + fmt(p[0]) : "") + "</text>";
    });
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "tracker");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", slot.getAttribute("data-label") || "Lead tracker");
    if (mode === "thumb") { svg.setAttribute("preserveAspectRatio", "none"); svg.style.height = "100%"; }
    svg.innerHTML = g;
    slot.appendChild(svg);
    Array.prototype.forEach.call(svg.querySelectorAll(".line"), function (p) {
      try { p.style.setProperty("--len", Math.ceil(p.getTotalLength())); } catch (e) {}
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-race]"), draw);
})();

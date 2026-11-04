#!/usr/bin/env python3
"""Rebuild the research-evolution chart and the theme colour-coding on the
publications pages.

Usage (from anywhere):
    python3 build.py                 # pages are two folders up (repo root)
    python3 build.py --pages PATH    # folder holding publications.html etc.
    python3 build.py --images PATH   # where to write research_evolution.svg/.png
                                     # (default: the pages folder)
    python3 build.py --check         # report only, change nothing
    python3 build.py --wordpress EXPORT.xml   # refresh abstracts.json from a
                                              # WordPress export, then build

papers.csv is the single source of truth. The script edits
publications.html and selected-papers.html in place. Everything it adds sits
between <!-- research-viz:begin ... --> / <!-- research-viz:end ... -->
markers (plus id / data-theme attributes and a colour box on paper rows), and
it strips all of that before adding it again, so running it twice gives the
same result.
"""
import argparse, csv, difflib, html, json, math, re, shutil, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Themes: key -> (label, colour, current?). Order = top-to-bottom in the chart.
THEMES = {
    "hw":    ("Resilience to hardware faults",         "#9c9c9c", False),
    "web":   ("Web application reliability",           "#c2c2c2", False),
    "cps":   ("CPS & embedded security",               "#d2652d", True),
    "edge":  ("Edge & cloud infrastructure",           "#4f9a5e", True),
    "ml":    ("ML reliability, security & privacy",    "#6b4fbb", True),
    "bc":    ("Smart contract & blockchain security",  "#b0457d", True),
}
CHART_START = 2010
PAGES = ("publications.html", "selected-papers.html")
# --------------------------------------------------------------------------


def norm(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).lower().replace("-", " ")
    return re.sub(r"[^a-z0-9 ]", "", s).split()


def key(venue, title):
    return " ".join(norm(venue)) + "|" + " ".join(norm(title))


def load_papers():
    rows = list(csv.DictReader(open(HERE / "papers.csv", newline="", encoding="utf-8")))
    bad = [r for r in rows if r["theme"] not in THEMES and r["theme"] != "none"]
    if bad:
        sys.exit(f"papers.csv: unknown theme in {[(r['page_title'][:40], r['theme']) for r in bad]}")
    for r in rows:
        r["chart"] = r["chart"].strip().lower() in ("y", "yes", "1", "true")
        if r["chart"] and r["theme"] == "none":
            sys.exit(f"papers.csv: a paper with theme 'none' cannot be in the chart: {r['page_title'][:60]}")
        if r["chart"] and not (r["id"] and r["year"] and r["chart_venue"] and r["size"]):
            sys.exit(f"papers.csv: chart row needs id, year, chart_venue and size: {r['page_title'][:60]}")
    ids = [r["id"] for r in rows if r["id"]]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        sys.exit(f"papers.csv: duplicate ids {sorted(dup)}")
    return rows


# --------------------------------------------------------------------------
# Cleaning: remove everything a previous run (or the first hand-off) added.
def clean(page):
    legacy = "Added by Claude" in page
    page = re.sub(r"[ \t]*<!-- research-viz:begin.*?<!-- research-viz:end[^>]*-->\n?", "", page, flags=re.S)
    # first hand-off used "Added by Claude" comments
    page = re.sub(r"[ \t]*<!-- ===== Added by Claude: research evolution figure \(START\).*?\(END\) ===== -->\n?", "", page, flags=re.S)
    page = re.sub(r"<!-- Added by Claude:[^>]*-->\s*(<style>.*?</style>|<script>.*?</script>)\n?", "", page, flags=re.S)
    page = re.sub(r"[ \t]*<!-- Added by Claude:[^>]*-->\s*<p class=\"theme-key\".*?</p>\n?", "", page, flags=re.S)
    page = re.sub(r"[ \t]*<p class=\"theme-filter-status\"[^>]*></p>\n?", "", page)
    page = re.sub(r'<span class="theme-box"[^>]*></span>', "", page)
    page = re.sub(r'<tr id="paper-[^"]*"', "<tr", page)
    page = re.sub(r'<tr data-theme="[^"]*"', "<tr", page)
    page = re.sub(r' ?<button type="button" class="abs-toggle"[^>]*>.*?</button>', "", page)
    page = re.sub(r'<div class="abs"[^>]*>.*?</div>', "", page, flags=re.S)
    if legacy:  # the first hand-off left extra blank lines around its blocks
        page = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", page)
    return page


def row_title(cell):
    a = re.match(r'\s*<a [^>]*>(.*?)</a>', cell, re.S)
    t = a.group(1) if a else cell.split("<br>")[0]
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip().rstrip(",")


def match_rows(page, papers, with_anchor):
    """Add theme boxes (and anchors) to table rows. Returns page, matched, unmatched."""
    by_key = {key(p["page_venue"], p["page_title"]): p for p in papers if p["page_title"] and p["page_venue"]}
    by_title = {}
    for p in papers:
        if p["page_title"]:
            by_title.setdefault(" ".join(norm(p["page_title"])), []).append(p)
    out, matched, unmatched = [], {}, []
    section = ""
    for line in page.split("\n"):
        m = re.search(r'<div id="cat-(\w+)"', line)
        if m:
            section = m.group(1)
        m = re.match(r'(\s*)<tr><td class="venue-cell">(.*?)</td><td>(.*)$', line)
        if m:
            venue, cell = m.group(2), m.group(3)
            title = row_title(cell)
            p = by_key.get(key(venue, title))
            if p is None:
                cands = by_title.get(" ".join(norm(title)), [])
                if len(cands) == 1:
                    p = cands[0]
            if p is None:  # small wording drift
                best, score = None, 0
                for q in papers:
                    if q["page_title"] and " ".join(norm(q["page_venue"])) == " ".join(norm(venue)):
                        s = difflib.SequenceMatcher(None, " ".join(norm(title)), " ".join(norm(q["page_title"]))).ratio()
                        if s > score:
                            best, score = q, s
                p = best if score >= 0.9 else None
            if p is None:
                unmatched.append((section, html.unescape(venue), title))
            elif p["theme"] == "none":
                pass  # deliberately left without a theme
            else:
                label, colour, _ = THEMES[p["theme"]]
                attrs = f' data-theme="{p["theme"]}"'
                if with_anchor and p["chart"] and p["id"]:
                    attrs = f' id="paper-{p["id"]}"' + attrs
                    matched[p["id"]] = p
                box = f'<span class="theme-box" style="background:{colour}" title="{html.escape(label)}"></span>'
                line = line.replace('<tr><td class="venue-cell">', f'<tr{attrs}><td class="venue-cell">{box}', 1)
                p["_count"] = p.get("_count", 0) + 1
        out.append(line)
    return "\n".join(out), matched, unmatched


# --------------------------------------------------------------------------
# Abstracts: imported once from a WordPress export, stored in abstracts.json
# (slug -> list of paragraphs). Only the abstract text is kept.
ABSTRACTS = HERE / "abstracts.json"
_ABS_START = re.compile(r"(?:<(?:strong|b|em|h\d)[^>]*>\s*)?Abstract\s*(?:</(?:strong|b|em|h\d)>)?\s*[:.\-–]?"
                        r"\s*(?:</(?:strong|b|em|h\d)>)?\s*[:.\-–]?", re.I)
_ABS_STOP = re.compile(r"^\s*\*|blogs referencing|news article|^\s*here is\b|supercede|superced|super-ceded|^\s*\[|"
                       r"^\s*(code|talk|slides|artifact|video|news|media|github)\b|^\s*\(|press release|award", re.I)


def post_slug(url):
    m = re.search(r"/\d{4}/\d{2}/\d{2}/([^/?#]+)/?(?:[?#].*)?$", url or "")
    return m.group(1) if m else None


def import_wordpress(xml_path):
    import xml.etree.ElementTree as ET
    ns = {"wp": "http://wordpress.org/export/1.2/", "content": "http://purl.org/rss/1.0/modules/content/"}
    out, skipped = {}, []
    for it in ET.parse(xml_path).getroot().findall("./channel/item"):
        if it.findtext("wp:post_type", namespaces=ns) != "post" or it.findtext("wp:status", namespaces=ns) != "publish":
            continue
        slug = post_slug(it.findtext("link")) or it.findtext("wp:post_name", namespaces=ns)
        body = (it.findtext("content:encoded", namespaces=ns) or "").replace("<!--more-->", "\n\n")
        m = _ABS_START.search(body)
        paras = []
        if m:
            for chunk in re.split(r"\n\s*\n|</p>\s*<p[^>]*>", body[m.end():]):
                text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", chunk))).strip()
                text = re.sub(r"\\(?:textit|textbf|emph|texttt)\{([^{}]*)\}", r"\1", text)  # LaTeX left in posts
                if not text:
                    if paras:
                        break
                    continue
                if paras and (_ABS_STOP.search(text) or re.match(r"\s*<(strong|b)\b", chunk.strip(), re.I)):
                    break
                paras.append(text)
                if sum(map(len, paras)) > 2500:
                    break
        if slug and len(" ".join(paras)) >= 150:
            out[slug] = paras
        else:
            skipped.append(html.unescape(it.findtext("title") or slug or "?"))
    ABSTRACTS.write_text(json.dumps(dict(sorted(out.items())), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Imported {len(out)} abstracts into {ABSTRACTS.name}; {len(skipped)} post(s) had no abstract we could find:")
    for t in skipped:
        print(f"    {t[:90]}")


def load_abstracts():
    return json.loads(ABSTRACTS.read_text(encoding="utf-8")) if ABSTRACTS.exists() else {}


def add_abstracts(page, abstracts):
    """Add an 'Abstract' toggle to every row whose title links to a blog post we have an abstract for."""
    if not abstracts:
        return page, 0
    out, n = [], 0
    for line in page.split("\n"):
        m = re.match(r'\s*<tr[^>]*><td class="venue-cell">.*?</td><td>\s*<a href="([^"]+)"', line)
        slug = post_slug(m.group(1)) if m and "blogs.ubc.ca" in m.group(1) else None
        end = line.rfind("</td>")
        if slug in abstracts and end != -1:
            n += 1
            body = "".join(f"<p>{html.escape(t, quote=False)}</p>" for t in abstracts[slug])
            line = (line[:end] + ' <button type="button" class="abs-toggle" aria-expanded="false">Abstract</button>'
                    f'<div class="abs" hidden>{body}</div>' + line[end:])
        out.append(line)
    return "\n".join(out), n


# --------------------------------------------------------------------------
def draw_chart(papers, linked, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    fonts = sorted((HERE / "fonts").glob("*.ttf"))
    for f in fonts:
        fm.fontManager.addfont(str(f))
    family = fm.FontProperties(fname=str(fonts[0])).get_name() if fonts else "DejaVu Sans"
    plt.rcParams.update({"font.family": family, "font.size": 10, "svg.fonttype": "none", "svg.hashsalt": "research-viz"})

    pts = [p for p in papers if p["chart"] and int(p["year"]) >= CHART_START]
    order = list(THEMES)
    ypos = {t: len(order) - 1 - i for i, t in enumerate(order)}
    last = max(int(p["year"]) for p in pts)
    cells = {}
    for p in pts:
        cells.setdefault((int(p["year"]), p["theme"]), []).append(p)

    fig, ax = plt.subplots(figsize=(13.5, 6.4), dpi=200)
    pos = {}
    for (yr, th), ps in sorted(cells.items()):
        ps = sorted(ps, key=lambda p: (p["size"] == "workshop", int(re.sub(r"\D", "", p["id"]) or 0), p["id"]))
        n = len(ps); cols = min(n, 3); rows = math.ceil(n / cols)
        for k, p in enumerate(ps):
            r, c = divmod(k, cols); cn = min(cols, n - r * cols)
            x = yr + (c - (cn - 1) / 2) * 0.27
            y = ypos[th] + (r - (rows - 1) / 2) * 0.2
            pos[p["id"]] = (x, y)
            colour, current = THEMES[th][1], THEMES[th][2]
            t1, main = p["size"] == "tier1", p["size"] != "workshop"
            sc = ax.scatter(x, y, s=92 if t1 else (52 if main else 24), color=colour,
                            alpha=(0.95 if current else 0.75) if main else 0.5,
                            edgecolor=("#1b1b1b" if current else "#8a8a8a") if t1 else "white",
                            linewidth=1.5 if t1 else 0.8, zorder=4 if t1 else 3)
            sc.set_gid(f"dot-{p['id']}")
            if p["id"] in linked:
                sc.set_urls([f"#paper-{p['id']}"])
    for p in pts:
        if p["label_dx"] and p["label_dy"]:
            x, y = pos[p["id"]]
            ax.annotate(f"[{p['chart_venue']}'{str(p['year'])[2:]}]", (x, y),
                        xytext=(float(p["label_dx"]), float(p["label_dy"])), textcoords="offset points",
                        fontsize=8.6, fontweight="semibold", zorder=5,
                        color="#222" if THEMES[p["theme"]][2] else "#9a9a9a",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    counts = {t: sum(1 for p in pts if p["theme"] == t) for t in order}
    ax.set_yticks([ypos[t] for t in order])
    ax.set_yticklabels([f"{THEMES[t][0]}  ({counts[t]})" for t in order])
    for t, lab in zip(order, ax.get_yticklabels()):
        lab.set_color(THEMES[t][1]); lab.set_fontweight("semibold")
    ax.set_ylim(-0.6, len(order) - 0.1)
    ax.set_xlim(CHART_START - 0.5, last + 0.8)
    ax.set_xticks(range(CHART_START, last + 1, 2)); ax.set_xticks(range(CHART_START, last + 1), minor=True)
    ax.grid(axis="y", color="#e4e4e4", lw=0.8, zorder=0)
    ax.grid(axis="x", which="minor", color="#f0f0f0", lw=0.6, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0); ax.spines["bottom"].set_color("#999")
    ax.set_title(f"Research evolution at UBC, {CHART_START}–{last}", loc="left", fontsize=15, fontweight="bold", pad=58)
    ax.text(0, 1.02, "Each dot is a conference or workshop paper (journal papers not shown).\n"
                     "Outlined = tier-1 venue, medium = other main track, small = workshop / short / supplemental.\n"
                     "Coloured rows are current research thrusts; grey rows are earlier work. "
                     "Labels mark award-winning and landmark papers.",
            transform=ax.transAxes, fontsize=9.3, color="#555")
    plt.tight_layout()
    outdir.mkdir(parents=True, exist_ok=True)
    plt.savefig(outdir / "research_evolution.png", bbox_inches="tight", metadata={"Software": None})
    plt.savefig(outdir / "research_evolution.svg", bbox_inches="tight", metadata={"Date": None, "Creator": None})
    plt.close(fig)
    return outdir / "research_evolution.svg", family, pts, last


def inline_svg(svg_path, family, pts, linked, last):
    svg = svg_path.read_text(encoding="utf-8")
    svg = svg[svg.index("<svg"):]
    svg = re.sub(r"<metadata>.*?</metadata>\s*", "", svg, flags=re.S)
    svg = re.sub(r'(<svg[^>]*?) width="[^"]*" height="[^"]*"', r"\1", svg, count=1)
    svg = svg.replace("<svg ", '<svg role="img" aria-labelledby="re-title" ', 1)
    svg = svg.replace(' target="_blank"', "")
    svg = svg.replace(f"font-family: '{family}'", "font-family: 'DM Sans', system-ui, sans-serif")
    svg = svg.replace("font-weight: 700", "font-weight: 600")
    info = {p["id"]: p for p in pts}

    def tip(m):
        p = info[m.group(1)]
        t = f"{p['chart_venue']}'{str(p['year'])[2:]}: {p['page_title']}"
        if p["id"] not in linked:
            t += " (not listed on this page)"
        return m.group(0) + f"<title>{html.escape(t)}</title>"
    svg = re.sub(r'<g id="dot-([^"]+)">', tip, svg)
    svg = re.sub(r"(<svg[^>]*>)", rf'\1<title id="re-title">Research evolution at UBC, {CHART_START}–{last}. '
                                    r'Click a dot to jump to the paper.</title>', svg, count=1)
    return svg


# --------------------------------------------------------------------------
CSS = """<!-- research-viz:begin styles -->
<style>
  .research-evolution { margin: 1.5rem 0 2rem; }
  .research-evolution .re-svg { max-width: 1100px; border: 1px solid #e5e5e5; border-radius: 6px; background: #fff; padding: 4px; }
  .research-evolution svg { display: block; width: 100%; height: auto; }
  .research-evolution svg a { cursor: pointer; }
  .research-evolution svg a:hover use { stroke: #000 !important; stroke-width: 2.5 !important; stroke-opacity: 1 !important; }
  .research-evolution figcaption { max-width: 1100px; margin-top: .6rem; font-size: .85rem; line-height: 1.5; color: #555; }
  .research-evolution .re-hint { display: none; margin: .4rem 0 0; font-size: .8rem; color: #777; }
  .papers-table tr td { transition: background 1.2s; }
  .papers-table tr.paper-flash td { background: #fff3b0; transition: background .4s; }
  .papers-table tr[id] { scroll-margin-top: 5rem; }
  .theme-box { display: inline-block; width: .6em; height: .6em; border-radius: 2px; margin-right: .45em; vertical-align: .05em; }
  .theme-key { display: flex; flex-wrap: wrap; gap: .35rem .6rem; margin: 0 0 1.1rem; font-size: .8rem; color: #555; }
  .theme-key-label { color: #777; align-self: center; }
  button.theme-chip { font: inherit; color: inherit; white-space: nowrap; background: none; border: 1px solid transparent; border-radius: 999px; padding: .1rem .55rem; cursor: pointer; }
  button.theme-chip:hover { border-color: #ccc; }
  button.theme-chip[aria-pressed="true"] { border-color: #555; background: #f3f3f3; font-weight: 600; }
  .theme-filter-status { font-size: .8rem; color: #555; margin: -.6rem 0 1rem; display: none; }
  .theme-filter-status button { font: inherit; background: none; border: 0; color: inherit; text-decoration: underline; cursor: pointer; padding: 0; }
  .papers-table tr.theme-hidden { display: none; }
  .theme-empty { font-size: .85rem; color: #777; margin: .5rem 0 1rem; }
  .abs-toggle { font: inherit; font-size: .75rem; color: var(--accent, #2b5c8a); background: none; border: 1px solid currentColor; border-radius: 999px; padding: 0 .5rem; margin-left: .4rem; cursor: pointer; vertical-align: .05em; opacity: .85; }
  .abs-toggle:hover { opacity: 1; }
  .abs-toggle::after { content: " \\25B8"; }
  .abs-toggle[aria-expanded="true"]::after { content: " \\25BE"; }
  .papers-table .abs { margin: .5rem 0 .3rem; padding: .6rem .8rem; border-left: 3px solid #ddd; background: #fafafa; font-size: .85rem; line-height: 1.55; color: #333; max-width: 52rem; }
  .papers-table tr:has(.abs:not([hidden])) td.venue-cell { vertical-align: top; }
  .papers-table .abs p { margin: 0 0 .5rem; } .papers-table .abs p:last-child { margin-bottom: 0; }
  @media (max-width: 760px) {
    .research-evolution .re-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .research-evolution .re-svg { min-width: 760px; }
    .research-evolution .re-hint { display: block; }
    .research-evolution figcaption { font-size: .8rem; }
  }
</style>
<!-- research-viz:end styles -->
</head>"""

JS = r"""<!-- research-viz:begin script -->
<script>
(function () {
  var current = null;
  var chips = document.querySelectorAll('button.theme-chip');
  var status = document.querySelector('.theme-filter-status');
  function applyFilter(f) {
    current = f;
    chips.forEach(function (c) { c.setAttribute('aria-pressed', c.dataset.filter === f ? 'true' : 'false'); });
    var shown = 0;
    document.querySelectorAll('.papers-table').forEach(function (tb) {
      var n = 0;
      tb.querySelectorAll('tr').forEach(function (tr) {
        var hide = f && tr.dataset.theme !== f;
        tr.classList.toggle('theme-hidden', !!hide);
        if (!hide) n++;
      });
      var note = tb.nextElementSibling && tb.nextElementSibling.classList.contains('theme-empty') ? tb.nextElementSibling : null;
      if (f && n === 0) {
        if (!note) { note = document.createElement('p'); note.className = 'theme-empty'; tb.after(note); }
        note.textContent = 'No papers in this section for the selected theme.';
      } else if (note) { note.remove(); }
      var cat = tb.closest('.paper-category');
      if (!cat || cat.classList.contains('active')) shown += n;
    });
    if (!status) return;
    if (f) {
      var chip = document.querySelector('button.theme-chip[data-filter="' + f + '"]');
      status.innerHTML = 'Showing ' + shown + ' paper' + (shown === 1 ? '' : 's') + ' in <strong></strong> &middot; <button type="button">Show all</button>';
      status.querySelector('strong').textContent = chip ? chip.dataset.label : f;
      status.querySelector('button').onclick = function () { applyFilter(null); };
      status.style.display = 'block';
    } else { status.style.display = 'none'; }
  }
  chips.forEach(function (c) {
    c.addEventListener('click', function () { applyFilter(current === c.dataset.filter ? null : c.dataset.filter); });
  });
  document.querySelectorAll('.paper-tab').forEach(function (t) {
    t.addEventListener('click', function () { setTimeout(function () { applyFilter(current); }, 0); });
  });

  function revealPaper(id, push) {
    var row = document.getElementById(id);
    if (!row) return false;
    if (current) applyFilter(null);
    var cat = row.closest('.paper-category');
    if (cat && !cat.classList.contains('active')) {
      var k = cat.id.replace('cat-', '');
      document.querySelectorAll('.paper-category').forEach(function (el) { el.classList.remove('active'); });
      document.querySelectorAll('.paper-tab').forEach(function (el) {
        el.classList.toggle('active', (el.getAttribute('onclick') || '').indexOf("'" + k + "'") !== -1);
      });
      cat.classList.add('active');
    }
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('paper-flash');
    setTimeout(function () { row.classList.remove('paper-flash'); }, 2500);
    if (push && history.replaceState) history.replaceState(null, '', '#' + id);
    return true;
  }
  document.querySelectorAll('.research-evolution svg a').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var href = a.getAttribute('href') || a.getAttributeNS('http://www.w3.org/1999/xlink', 'href') || '';
      if (href.charAt(0) === '#' && revealPaper(href.slice(1), true)) e.preventDefault();
    });
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.abs-toggle');
    if (!b) return;
    var box = b.nextElementSibling, open = b.getAttribute('aria-expanded') !== 'true';
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (box) box.hidden = !open;
  });
  if (location.hash.indexOf('#paper-') === 0) {
    window.addEventListener('load', function () { revealPaper(location.hash.slice(1), false); });
  }
  // links such as publications.html#theme=edge open the page already filtered
  function filterFromHash() {
    var m = location.hash.match(/^#theme=([a-z]+)$/);
    if (m && document.querySelector('button.theme-chip[data-filter="' + m[1] + '"]')) applyFilter(m[1]);
  }
  filterFromHash();
  window.addEventListener('hashchange', filterFromHash);
})();
</script>
<!-- research-viz:end script -->
"""


def theme_key(counts=None, only_present=False):
    chips = []
    for k, (label, colour, current) in sorted(THEMES.items(), key=lambda kv: not kv[1][2]):
        n = counts.get(k, 0) if counts is not None else None
        if only_present and not n:
            continue
        suffix = []
        if not current:
            suffix.append("earlier")
        if n is not None:
            suffix.append(str(n))
        text = html.escape(label) + (f" ({', '.join(suffix)})" if suffix else "")
        chips.append(f'<button type="button" class="theme-chip" data-filter="{k}" data-label="{html.escape(label)}" '
                     f'aria-pressed="false"><span class="theme-box" style="background:{colour}"></span>{text}</button>')
    return ('  <!-- research-viz:begin theme-key -->\n'
            '  <p class="theme-key" role="group" aria-label="Filter papers by theme"><span class="theme-key-label">Filter by theme:</span> '
            + " ".join(chips) + '</p>\n  <p class="theme-filter-status" aria-live="polite"></p>\n'
            '  <!-- research-viz:end theme-key -->\n')


def figure_block(svg):
    return (f'  <!-- research-viz:begin figure -->\n  <figure class="research-evolution">\n'
            f'    <div class="re-scroll"><div class="re-svg">{svg}</div></div>\n'
            f'    <p class="re-hint">Swipe sideways to see the whole timeline.</p>\n'
            f'    <figcaption>\n'
            f'      How my research has evolved since I joined UBC in {CHART_START}: conference and workshop papers grouped by research thrust.\n'
            f'      Coloured rows are current thrusts; grey rows are earlier work; outlined dots are tier-1 venues.\n'
            f'      Hover over a dot to see the paper, and click it to jump to it in the list below. Journal papers are not shown.\n'
            f'    </figcaption>\n  </figure>\n  <!-- research-viz:end figure -->\n')


def inject(page, before_marker, block):
    if page.count(before_marker) != 1:
        sys.exit(f"Could not find a unique place to insert ({before_marker.strip()!r}). Has the page layout changed?")
    return page.replace(before_marker, block + before_marker, 1)


def report_unmatched(name, unmatched):
    recent = [u for u in unmatched if (m := re.search(r"'(\d\d)", u[1])) and 10 <= int(m.group(1)) < 70]
    if recent:
        print(f"  {name}: {len(recent)} post-{CHART_START} paper(s) have no theme yet (add them to papers.csv):")
        for sec, venue, title in recent:
            print(f"    [{sec or '-'}] {venue}: {title[:80]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages", default=str(HERE.parent.parent), help="folder containing the HTML pages (default: repo root)")
    ap.add_argument("--images", default=None, help="folder for research_evolution.svg/.png (default: same as --pages)")
    ap.add_argument("--check", action="store_true", help="report what would change without writing")
    ap.add_argument("--wordpress", metavar="EXPORT.xml", help="import abstracts from a WordPress export into abstracts.json, then build")
    args = ap.parse_args()
    if args.wordpress:
        if args.check:
            sys.exit("--wordpress writes abstracts.json, so it can't be combined with --check")
        import_wordpress(args.wordpress)
    pages_dir = Path(args.pages).resolve()
    images_dir = Path(args.images).resolve() if args.images else pages_dir
    tmp = Path(tempfile.mkdtemp(prefix="research-viz-"))
    papers = load_papers()
    abstracts = load_abstracts()

    # publications.html: anchors + boxes + chart + key
    pub_path = pages_dir / PAGES[0]
    pub = clean(pub_path.read_text(encoding="utf-8"))
    pub, linked, unmatched = match_rows(pub, papers, with_anchor=True)
    pub, n_abs = add_abstracts(pub, abstracts)
    svg_path, family, pts, last = draw_chart(papers, linked, tmp)
    svg = inline_svg(svg_path, family, pts, linked, last)
    pub = inject(pub, '  <div class="paper-tabs">', figure_block(svg) + theme_key())
    pub = pub.replace("</head>", CSS, 1).replace("<footer>", JS + "<footer>", 1)
    print(f"{PAGES[0]}: {len(pts)} papers in the chart, {len(linked)} linked to the list, {n_abs} abstracts")
    missing = [p for p in pts if p["id"] not in linked]
    if missing:
        print(f"  {len(missing)} chart paper(s) not found on the page (shown without a link): "
              + "; ".join(f"{p['chart_venue']}'{p['year'][2:]}" for p in missing))
    report_unmatched(PAGES[0], unmatched)

    # selected-papers.html: boxes + counted key
    sel_path = pages_dir / PAGES[1]
    sel = None
    if sel_path.exists():
        for p in papers:
            p["_count"] = 0
        sel = clean(sel_path.read_text(encoding="utf-8"))
        sel, _, sel_unmatched = match_rows(sel, papers, with_anchor=False)
        sel, sel_abs = add_abstracts(sel, abstracts)
        counts = {}
        for p in papers:
            counts[p["theme"]] = counts.get(p["theme"], 0) + p.get("_count", 0)
        sel = inject(sel, '  <table class="papers-table">', theme_key(counts, only_present=True))
        sel = sel.replace("</head>", CSS, 1).replace("<footer>", JS + "<footer>", 1)
        print(f"{PAGES[1]}: " + ", ".join(f"{THEMES[k][0]} {n}" for k, n in counts.items() if n) + f"; {sel_abs} abstracts")
        report_unmatched(PAGES[1], sel_unmatched)

    # index.html: keep the colour squares (data-theme-box), tool-card stripes
    # (data-theme-card) and thrust labels (data-theme-label) in step with THEMES
    home_path, home = pages_dir / "index.html", None
    if home_path.exists():
        before = home_path.read_text(encoding="utf-8")
        def recolour(m):
            k = m.group(1)
            if k not in THEMES:
                print(f"  index.html: unknown theme '{k}' on a colour mark")
                return m.group(0)
            c = THEMES[k][1]
            tag = re.sub(r"background:[^;\"]+", f"background:{c}", m.group(0))
            tag = re.sub(r"(?<![\w-])color:#[0-9a-fA-F]{3,6}", f"color:{c}", tag)
            return re.sub(r"(inset \d+px 0 0 )#[0-9a-fA-F]{3,6}", rf"\g<1>{c}", tag)
        home = re.sub(r'<[a-z0-9]+ [^>]*data-theme-(?:box|card|label)="([a-z]+)"[^>]*>', recolour, before)
        n = len(re.findall(r"data-theme-(?:box|card|label)=", home))
        print(f"index.html: {n} colour mark(s)" + (" recoloured" if home != before else ", already up to date"))
        if home == before:
            home = None

    if args.check:
        shutil.rmtree(tmp, ignore_errors=True)
        print("--check: nothing written.")
        return
    pub_path.write_text(pub, encoding="utf-8")
    if sel is not None:
        sel_path.write_text(sel, encoding="utf-8")
    if home is not None:
        home_path.write_text(home, encoding="utf-8")
    images_dir.mkdir(parents=True, exist_ok=True)
    for name in ("research_evolution.svg", "research_evolution.png"):
        shutil.copyfile(tmp / name, images_dir / name)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Updated {pub_path}" + (f" and {sel_path}" if sel is not None else ""))
    print(f"Wrote {images_dir / 'research_evolution.svg'} and {images_dir / 'research_evolution.png'}")


if __name__ == "__main__":
    main()

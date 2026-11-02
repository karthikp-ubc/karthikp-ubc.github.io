# research-viz

Builds the research-evolution chart and the theme colour-coding on
`publications.html` and `selected-papers.html`.

## Layout

```
tools/research-viz/
  build.py          the build script
  papers.csv        one row per themed paper (the only file you normally edit)
  fonts/            DM Sans (SIL Open Font License, see OFL.txt), so the PNG matches the site
  requirements.txt
```

The script assumes the pages live two folders up, i.e. at the repo root.
If not, pass `--pages path/to/folder`.

Each run also writes `research_evolution.svg` and `research_evolution.png`
next to the pages (overwriting the previous ones), for use outside the
page, e.g. slides or social media. The page itself carries its own inline
copy of the chart and does not load these files. To put the images
somewhere else, pass `--images path/to/folder`.

## One-time setup

```
pip install -r tools/research-viz/requirements.txt
```

## Adding a new paper

1. Add the paper to `publications.html` (and `selected-papers.html` if it
   belongs there) as you normally would.
2. Add a row to `papers.csv` (see the columns below). For a conference or
   workshop paper you want in the chart, set `chart` to `y`.
3. Run `python3 tools/research-viz/build.py`
4. Read the output. It lists any post-2010 paper on the pages that has no
   row in `papers.csv` yet, and any chart paper it couldn't find on the page.
5. Check `git diff`, open the page locally, and commit.

`python3 build.py --check` reports the same things without writing anything.

## papers.csv columns

| column | meaning |
|---|---|
| `id` | Stable, unique id. Used for the anchor `#paper-<id>`, so don't change it once published. Needed only for chart papers. Any short text works for new papers, e.g. `n27-carve`. |
| `theme` | `hw`, `web`, `cps`, `edge`, `ml`, `bc`, or `none` (deliberately no box, e.g. CSF'11). |
| `chart` | `y` to draw a dot, `n` for list-only (journals, posters, pre-2010). |
| `year` | Year on the chart's x-axis (chart rows only). |
| `chart_venue` | Short venue used in chart labels and tooltips, e.g. `DSN`, `CCS`, `DSN-S`. |
| `size` | `tier1` (large, outlined), `main` (medium) or `workshop` (small). |
| `label_dx`, `label_dy` | Leave blank for no label. To label a dot as `[DSN'27]`, give an offset in points from the dot, e.g. `6` and `10` (right and above). Nudge these if a label overlaps something. |
| `section` | Informational only: `conf`, `journal`, `workshop` or `invited`. |
| `page_venue` | The venue text exactly as in the page's venue column, e.g. `DSN'26`, `IEEE S&P'24`. |
| `page_title` | The paper title as it appears on the page. Small differences are tolerated. |

Matching uses `page_venue` + `page_title`, so if you rename a paper on the
page, update the CSV row too (the build will warn you if it can't match).

## Changing themes or colours

Edit the `THEMES` table at the top of `build.py`. Each theme has a label,
a colour, and whether it's current (coloured) or earlier work (grey). The
order there is the top-to-bottom order of rows in the chart.

## What the build changes on the pages

Everything added sits between `<!-- research-viz:begin ... -->` and
`<!-- research-viz:end ... -->` comments: a style block in `<head>`, the
figure and theme key above the paper tabs, and a script before the footer.
Paper rows also get an `id`, a `data-theme` attribute and a small colour box.

Each run strips all of this and adds it again, so running it twice gives the
same result, and the rest of the page is never touched. To remove everything,
delete the marked blocks and the three row additions, or check out the page
from before the first build.

## Deployment note

If your whole repo is copied to the web server, this folder will be
public too. It contains nothing private, but you can exclude
`tools/` from the upload if you prefer.

# Tomizuka Academic Family Tree

Interactive radial family tree of Professor Masayoshi Tomizuka's academic
descendants, made for his 80th birthday (Tomizuka Fest, August 7 2026).
Linked from the **Tomizuka Academic Family Tree** button on
<https://tomi80th.github.io/tomizukafest/>.

Live page: `https://thomaschen98.github.io/tomizuka-family-tree/` (once pushed).

## What's here

```
index.html            the whole page (HTML + CSS + JS, no build step)
assets/d3.v7.min.js   vendored D3 — no CDN dependency
assets/tomizuka.jpg   center portrait
data/tree.js          generated data (window.TREE_DATA) — no contact info, ever
photos/               survey photos land here, named <person-id>.jpg
scripts/build_data.py regenerates data/tree.js
```

`data/tree.js` is a plain script (not fetch/JSON) so the page also works from
`file://` with no server.

## Photos

118 of 165 first-gen portraits were bootstrapped from public sources — the MSC
lab site (80), faculty pages, Google Scholar, LinkedIn and news features (38) —
each verified against the person's Berkeley/Tomizuka record before saving.
`photos/manifest.json` records the source URL and confidence per photo. Survey
uploads replace these; people without a confident public photo render as
decade-colored dots (initials appear on hover) until then.

## Updating the data

```bash
python3 scripts/build_data.py "/path/to/Survey Form Contact Lists.xlsx"
```

Emails and remarks are read for parsing only and are **never written to the
output**. Affiliations/titles for first-gen professors live in the `EDUCATORS`
table at the top of the script until each person's survey response replaces
them.

## The survey pipeline

Already built:

- **`survey.html`** — the "fill your card" form, same design as the tree page.
  Advisor field autocompletes from every professor already on the tree.
  The **"I am (or was) a professor" checkbox** is the growth mechanism: it
  upgrades the respondent to an expandable branch (even if the original
  contact sheet missed them — any generation) and shows them the
  forward-this-link-to-your-students instruction.
- **`scripts/apps_script.gs`** — 2-minute Google Apps Script backend:
  `doPost` appends responses to a Sheet, `doGet` serves them as CSV (emails
  excluded). Deploy it, paste the web-app URL into `APPS_SCRIPT_URL` at the
  top of survey.html.
- **`build_data.py --survey responses.csv`** — merge: name matches an
  existing node → card updated in place (professor checkbox flips them to a
  branch); new name + matched advisor → appended as that advisor's child, so
  generations 2…N need no page changes, only data. Unmatched advisors land in
  `data/needs-review.md` for a human pass.

- **`.github/workflows/update-tomizuka-tree.yml`** (repo root) — rebuilds the
  tree **every 6 hours** (plus a manual Run-workflow button) from
  `data/base.json` (the sanitized, email-free snapshot of the contact sheet)
  merged with `data/sample_responses.csv` and, once `SURVEY_CSV_URL` in the
  workflow is filled in, the live Apps Script CSV. Commits only when the data
  actually changed; GitHub Pages redeploys in ~1 minute.

So the refresh latency is: survey submission → Google Sheet (instant) →
next 6-hour cron (or a manual trigger) → live about a minute later.

### Photo policy: auto-publish, weekly human audit

Survey `photo_url`s are ingested automatically by the Action
(`scripts/ingest_photos.py`): downloaded, validated as a real image ≥80px,
resized to 240px JPEG, published, and recorded in `photos/manifest.json` as
`self-submitted`. The weekly check is `photos.html` — every photo with its
person-id and source. To remove a photo, add its id as a line in
`photos/blocklist.txt`: the next run deletes the file and never re-ingests it
(deleting the jpg alone is NOT enough for survey photos — it would come back).

`data/sample_responses.csv` is a demo of the format — 45 real PhD students of
Changliu Liu (CMU), Kyoungchul Kong (KAIST) and Xu Chen (UW), scraped from
their lab websites (`source=bootstrap`, marked "pending survey confirmation"
in the tooltip). Two of Kong's graduates are professors themselves, so the
demo shows a third generation opening.

## Design notes

- Layout follows the "Maison Grizzle" radial poster: professor portrait at the
  center, first generation ordered by PhD year around the ring, decade arcs,
  descendants opening outward.
- Page chrome matches tomizukafest (cream/charcoal/gold, Playfair Display).
- Decade colors are an ordinal single-hue blue ramp validated for CVD safety
  in both light and dark mode; professor status is additionally encoded by the
  gold ring + legend + table badge (never color alone).
- Table view is the accessible twin of the chart; search works on both.

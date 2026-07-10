#!/usr/bin/env python3
"""Convert the BFS-crawl workflow result into data/gen_crawl.csv.

Usage:
    python3 scripts/merge_crawl.py /path/to/workflow_output.json

The workflow output is {"result": {"rosters": [...], "faculty": [...]}} (or
the result object directly). Rows are written level by level so every
advisor exists before their students merge. Photo URLs captured from roster
pages go into the photo_url column — scripts/ingest_photos.py downloads and
validates them like any survey submission. All rows are source=bootstrap,
i.e. "pending survey confirmation" until the person fills the survey.
"""
import csv
import json
import re
import sys
import unicodedata


def norm(n):
    s = unicodedata.normalize('NFKD', n or '').encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\([^)]*\)', ' ', s)
    return re.sub(r'[^a-z]', '', s)


def main():
    raw = json.load(open(sys.argv[1]))
    res = raw.get('result', raw)
    rosters = res['rosters']
    faculty = res.get('faculty', [])

    fac = {}
    for f in faculty:
        k = norm(f['name'])
        best = fac.get(k)
        rank = {'high': 2, 'medium': 1, 'low': 0}
        if best is None or rank.get(f.get('confidence'), 0) > rank.get(best.get('confidence'), 0):
            fac[k] = f

    rows = []
    seen = set()          # (advisor, student) pairs — dedupe repeated rosters
    for r in sorted(rosters, key=lambda r: (r['advisorGen'], r['advisor'])):
        for s in r['students']:
            key = (norm(r['advisor']), norm(s['name']))
            if key in seen or not (s.get('name') or '').strip():
                continue
            seen.add(key)
            f = fac.get(norm(s['name']))
            is_prof = bool(f and f.get('isProfessor')
                           and f.get('confidence') in ('high', 'medium'))
            dead = bool(f and f.get('status') == 'deceased')
            rows.append({
                'name': s['name'].strip(),
                'advisor': r['advisor'],
                'status': 'current' if s['status'] == 'phd_current' else 'graduated',
                'grad_year': s.get('gradYear') or '',
                'is_professor': 'yes' if is_prof else 'no',
                'affiliation': (f.get('affiliation') or '') if is_prof else '',
                'title': (f.get('title') or '') if is_prof else '',
                'note': (s.get('note') or '').strip(),
                'bio': '',
                'photo_url': (s.get('photoUrl') or '').strip(),
                'source': 'bootstrap',
                'in_memoriam': 'yes' if dead else '',
            })

    cols = ['name', 'advisor', 'status', 'grad_year', 'is_professor',
            'affiliation', 'title', 'note', 'bio', 'photo_url', 'source',
            'in_memoriam']
    with open('data/gen_crawl.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    n_prof = sum(1 for r in rows if r['is_professor'] == 'yes')
    n_photo = sum(1 for r in rows if r['photo_url'])
    print(f'wrote data/gen_crawl.csv: {len(rows)} students, '
          f'{n_prof} professors, {n_photo} photo urls')


if __name__ == '__main__':
    main()

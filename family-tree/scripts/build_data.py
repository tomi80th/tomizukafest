#!/usr/bin/env python3
"""Build data/tree.js for the Tomizuka Academic Family Tree.

Reads the first-generation contact list (xlsx) and emits a hierarchical
JSON structure. Emails are intentionally excluded from the output — the
published page must never contain contact information.

Usage:
    python3 scripts/build_data.py "/path/to/Survey Form Contact Lists.xlsx" \
        [--survey responses.csv ...]

Survey CSV columns (see survey.html / scripts/apps_script.gs):
    name, advisor, status(graduated|current), grad_year, is_professor,
    affiliation, title, bio, note, source

Merge semantics — this is what makes the tree grow by itself:
  * respondent name matches an existing node       -> card updated in place;
    is_professor=yes upgrades them to an expandable branch even if the
    original contact sheet missed it (any generation).
  * respondent is new + advisor matches a node     -> appended as that
    node's child (advisor "Masayoshi Tomizuka" -> first generation).
  * advisor not found                              -> data/needs-review.md
"""
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

# ---------------------------------------------------------------------------
# Curated metadata for first-generation alumni who lead (or led) their own
# academic groups.  affiliation/title are display strings; verified=True means
# the entry was checked against a public faculty page.  Everything else in the
# tree comes from the survey, so this table is only a bootstrap for the demo.
# ---------------------------------------------------------------------------
EDUCATORS = {
    # Verified against public faculty pages, 2026-07 (see README).
    'horowitz-roberto':      ('UC Berkeley', 'Distinguished Professor'),
    'tsao-tsu-chin':         ('UCLA', 'Distinguished Professor'),
    'teo-chee-leong':        ('National University of Singapore', 'Professor Emeritus'),
    'yang-sangsik':          ('Ajou University', 'Professor'),
    'oh-jun-ho':             ('KAIST', 'Professor Emeritus'),
    'chen-min-shin':         ('National Taiwan University', 'Professor'),
    'langari-reza':          ('Texas A&M University', 'Regents Professor'),
    'hu-jwu-sheng':          ('National Yang Ming Chiao Tung University', 'Professor'),
    'jeon-doyoung':          ('Sogang University', 'Professor'),
    'kachroo-pushkin':       ('University of Nevada, Las Vegas', 'Professor'),
    'hwang-yean-ren':        ('National Central University', 'Professor'),
    'chiu-george':           ('Purdue University', 'Professor'),
    'yao-bin':               ('Purdue University', 'Professor'),
    'pagilla-prabhakar':     ('Texas A&M University', 'Professor'),
    'lee-hyeongcheol':       ('Hanyang University', 'Professor'),
    'chee-wonshik':          ('UT Austin', 'Research Professor'),
    'feng-kai-ten':          ('National Yang Ming Chiao Tung University', 'Professor'),
    'ibaraki-soichi':        ('Hiroshima University', 'Professor'),
    'suryanarayanan-shashikanth': ('IIT Bombay', 'Professor'),
    'hsiao-te-sheng':        ('National Yang Ming Chiao Tung University', 'Associate Professor'),
    'jeon-soo':              ('University of Waterloo', 'Professor'),
    'mishra-sandipan':       ('Rensselaer Polytechnic Institute', 'Professor'),
    'kong-kyoungchul':       ('KAIST', 'Professor'),
    'pan-liang':             ('Purdue University', 'Professor'),
    'wu-guoyuan':            ('UC Riverside', 'Adjunct Professor, Research Faculty'),
    'bae-joonbum':           ('UNIST', 'Professor'),
    'chen-xu':               ('University of Washington', 'Associate Professor'),
    'wang-cong':             ('New Jersey Institute of Technology', 'Associate Professor'),
    'zhang-wenlong':         ('Arizona State University', 'Associate Professor'),
    'liu-changliu':          ('Carnegie Mellon University', 'Associate Professor'),
    'zheng-minghui':         ('Texas A&M University', 'Associate Professor'),
    'chen-jianyu':           ('Tsinghua University', 'Assistant Professor'),
    'li-jiachen':            ('UC Riverside', 'Assistant Professor'),
    'tang-chen':             ('UCLA', 'Assistant Professor'),
    'ding-mingyu':           ('UNC Chapel Hill', 'Assistant Professor'),
    'hu-yeping':             ('UCLA', 'Incoming Assistant Professor'),
    # Dropped after verification (retired / left academia / could not confirm):
    # lee-gun-bok, tarn-jiun-haur, al-majed-mohammed, tai-meihua,
    # anwar-george (Lecturer), chang-siu-evan (now industry).
    # ding-mingyu and kurkcu-burak are professors but joined as postdoc/visitor,
    # so they are excluded from the tree (students only).
}

IN_MEMORIAM = {'chen-min-shin'}


def slugify(first, last):
    s = f'{last}-{first}'.lower()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s


def read_rows(path):
    z = zipfile.ZipFile(path)
    shared = []
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    for si in root.iter(NS + 'si'):
        shared.append(''.join(t.text or '' for t in si.iter(NS + 't')))
    root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    rows = []
    for row in root.iter(NS + 'row'):
        cells = {}
        for c in row.iter(NS + 'c'):
            v = c.find(NS + 'v')
            if v is None:
                continue
            val = v.text
            if c.get('t') == 's':
                val = shared[int(val)]
            col = 0
            for ch in re.match(r'([A-Z]+)', c.get('r')).group(1):
                col = col * 26 + ord(ch) - 64
            cells[col - 1] = (val or '').strip()
        if cells:
            rows.append(cells)
    return rows


def parse_batch(note):
    """Return (sort_key, display, kind, year_or_None)."""
    n = (note or '').strip().lower()
    m = re.search(r'(\d{4})\s*-\s*(\d{4})', n)
    if m:
        y = int(m.group(2))
        return (y, f'PhD {m.group(1)}–{m.group(2)[2:]}', 'phd', y)
    m = re.search(r'(\d{4})', n)
    if m:
        y = int(m.group(1))
        return (y, f'PhD {y}', 'phd', y)
    if 'postdoc' in n:
        return (10001, 'Postdoc', 'postdoc', None)
    if 'visitor' in n or 'visiting' in n:
        return (10002, 'Visiting Scholar', 'visitor', None)
    if 'current' in n:
        return (10000, 'PhD Candidate', 'current', None)
    return (10003, note or '', 'other', None)


def decade_bin(kind, year):
    if kind in ('current', 'postdoc', 'visitor', 'other'):
        return 'Current'
    if year < 1990:
        return '1977–1989'
    return f'{year // 10 * 10}s'


def norm_name(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    # people write advisors as "Prof. X", "Professor X", "Dr. X" — drop honorifics
    s = re.sub(r'\b(professor|prof|dr|mr|mrs|ms)\.?\s+', ' ', s)
    # and themselves as 'Wenjie (Jeff) Li' — drop parenthesized nicknames
    s = re.sub(r'\([^)]*\)', ' ', s)
    return re.sub(r'[^a-z]', '', s)


def slug_full(name):
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def _pagey(url):
    """True when a URL is a web page rather than a direct image link —
    people often paste their homepage into the photo field."""
    u = (url or '').strip()
    return (u.lower().startswith('http')
            and not re.search(r'\.(jpe?g|png|gif|webp|avif|bmp)([?#]|$)', u, re.I)
            and 'drive.google.com/uc' not in u)


def merge_survey(tree, path):
    import csv
    by_name, ids, parent_of = {}, set(), {}

    def index(node, parent_name):
        # a name maps to a LIST of nodes: genuine namesakes exist on the tree,
        # so identity is (name x advisor), never the bare name
        by_name.setdefault(norm_name(node['name']), []).append(node)
        ids.add(node.get('id'))
        parent_of[node.get('id')] = parent_name
        for c in node.get('children', []):
            index(c, node['name'])
    index(tree, None)

    unmatched = []
    mismatched = []
    for r in csv.DictReader(open(path)):
        name = (r.get('name') or '').strip()
        if not name:
            continue
        is_prof = (r.get('is_professor') or '').strip().lower() in ('true', 'yes', 'y', '1')
        m = re.search(r'\d{4}', r.get('grad_year') or '')
        year = int(m.group(0)) if m else None
        status_l = (r.get('status') or '').strip().lower()
        is_ms = status_l == 'ms' or 'master' in status_l
        graduated = 'grad' in status_l
        current = (('current' in status_l) or (year is None and not graduated)) and not is_ms
        kind = 'ms' if is_ms else ('current' if current else 'phd')
        provisional = (r.get('source') or '').strip() == 'bootstrap'

        # distinct=yes explicitly declares a namesake: never merge by name
        distinct = (r.get('distinct') or '').strip().lower() in ('yes', 'true', '1')
        adv_n = norm_name(r.get('advisor') or '')
        cands = [] if distinct else (by_name.get(norm_name(name)) or [])
        if adv_n:
            # identity is (name x advisor): route to the candidate under the
            # SAME advisor; a name that exists only under other advisors is a
            # homonym or co-advised duplicate — never overwrite, flag it
            me = next((c for c in cands
                       if norm_name(parent_of.get(c.get('id')) or '') == adv_n), None)
            if me is None and cands:
                mismatched.append(r)
                continue
        else:
            me = cands[0] if cands else None
        if me is not None:                      # update an existing card
            if not provisional:
                me['provisional'] = False       # a real survey confirms the card
                if name != me['name']:
                    me['name'] = name           # self-reported name wins
            if is_prof and not me.get('educator'):
                me['educator'] = True
            aff_in = (r.get('affiliation') or '').strip()
            title_in = (r.get('title') or '').strip()
            if aff_in:
                me['affiliation'] = aff_in
                me['note'] = None   # structured affiliation supersedes freetext
            if title_in:
                me['title'] = title_in
            if (r.get('bio') or '').strip():
                me['bio'] = r['bio'].strip()
            if (r.get('note') or '').strip() and not aff_in:
                me['note'] = r['note'].strip()
            hp = (r.get('homepage') or '').strip()
            if hp.lower().startswith('http'):
                me['homepage'] = hp
            elif not me.get('homepage') and _pagey(r.get('photo_url')):
                me['homepage'] = (r.get('photo_url') or '').strip()
            # a year only counts as graduation when status isn't "current" —
            # current students often write their EXPECTED graduation year
            if is_ms:                          # curator override: MS, not PhD
                me['kind'] = 'ms'
                me['batch'] = f'MS {year}' if year else 'MS'
                if year:
                    me['year'] = year
                    me['decade'] = decade_bin('phd', year)
            elif year and not current:
                me['year'] = year
                me['kind'] = 'phd'
                me['batch'] = f'PhD {year}'
                me['decade'] = decade_bin('phd', year)
                # graduating drops the automatic "UC Berkeley" (current-student)
                # tag unless the row supplied a real affiliation
                if (not aff_in and me.get('affiliation') == 'UC Berkeley'
                        and not me.get('title') and not me.get('educator')):
                    me['affiliation'] = None
            continue

        pcands = by_name.get(norm_name(r.get('advisor') or '')) or []
        # among advisor namesakes, only an educator can be the parent
        parent = (pcands[0] if len(pcands) == 1
                  else next((c for c in pcands if c.get('educator')), None))
        if parent is None:                      # advisor unknown -> human pass
            unmatched.append(r)
            continue

        pid = slug_full(name)
        if pid in ids:
            pid = f"{pid}--{parent['id'][:10]}"
        ids.add(pid)
        child = {
            'id': pid,
            'name': name,
            'batch': ((f'MS {year}' if year else 'MS') if is_ms
                      else ((f'PhD {year}' if year else 'PhD') if not current
                            else 'PhD Candidate')),
            'kind': kind,
            'year': year if not current else None,   # expected years don't sort
            'decade': decade_bin(kind, year) if (not current and year) else 'Current',
            'educator': is_prof,
            'affiliation': (r.get('affiliation') or '').strip() or None,
            'title': (r.get('title') or '').strip() or None,
            'inMemoriam': (r.get('in_memoriam') or '').strip().lower() in ('true', 'yes', 'y', '1'),
            'photo': f'photos/{pid}.jpg' if os.path.exists(f'photos/{pid}.jpg') else None,
            'bio': (r.get('bio') or '').strip() or None,
            'note': (None if (r.get('affiliation') or '').strip()
                     else (r.get('note') or '').strip() or None),
            'homepage': ((r.get('homepage') or '').strip()
                         if (r.get('homepage') or '').strip().lower().startswith('http')
                         else ((r.get('photo_url') or '').strip()
                               if _pagey(r.get('photo_url')) else None)),
            'provisional': provisional,
            'children': [],
        }
        parent.setdefault('children', []).append(child)
        by_name.setdefault(norm_name(name), []).append(child)
        parent_of[pid] = parent['name']

    for node_list in _walk_children(tree):
        node_list.sort(key=lambda c: (c['year'] or 9999, c['name']))

    # accumulate across ALL survey files; write_review() flushes once at the end
    # (a per-file write let the last, clean file erase earlier files' reports)
    _REVIEW['unmatched'].extend(unmatched)
    _REVIEW['mismatched'].extend(mismatched)


_REVIEW = {'unmatched': [], 'mismatched': []}


def write_review():
    unmatched, mismatched = _REVIEW['unmatched'], _REVIEW['mismatched']
    if unmatched or mismatched:
        with open('data/needs-review.md', 'w') as f:
            if unmatched:
                f.write('# Survey rows whose advisor could not be matched\n\n')
                for r in unmatched:
                    f.write(f"- {r.get('name')} (advisor given: {r.get('advisor')!r})\n")
            if mismatched:
                f.write('\n# Name exists under a different advisor '
                        '(homonym, or co-advised duplicate?)\n\n')
                f.write('If a real namesake: re-add the row with distinct=yes. '
                        'If co-advised: safe to ignore.\n\n')
                for r in mismatched:
                    f.write(f"- {r.get('name')} (row advisor: {r.get('advisor')!r}, "
                            f"{r.get('status')} {r.get('grad_year')})\n")
        print(f'WARNING {len(unmatched)} unmatched, {len(mismatched)} advisor-mismatched '
              f'-> data/needs-review.md', file=sys.stderr)
    elif os.path.exists('data/needs-review.md'):
        os.remove('data/needs-review.md')


def _walk_children(node):
    for c in node.get('children', []):
        yield from _walk_children(c)
    if node.get('children'):
        yield node['children']


def refresh_photos(node):
    """Re-check photos/<id>.jpg for every node — photos can land after the
    base was written (survey uploads, later collection passes)."""
    if node.get('id') and node['id'] != 'tomizuka':
        p = f"photos/{node['id']}.jpg"
        if os.path.exists(p):
            node['photo'] = p
    for c in node.get('children', []):
        refresh_photos(c)


def write_tree(tree, out='data/tree.js'):
    with open(out, 'w') as f:
        f.write('// Generated by scripts/build_data.py — do not edit by hand.\n')
        f.write('// Contact information is deliberately excluded from this file.\n')
        f.write('window.TREE_DATA = ')
        json.dump(tree, f, ensure_ascii=False, indent=1)
        f.write(';\n')
    people = tree['children']
    n_edu = sum(p['educator'] for p in people)
    years = [p['year'] for p in people if p['year']]
    n_desc = 0
    stack = list(people)
    while stack:
        n = stack.pop()
        n_desc += len(n.get('children', []))
        stack.extend(n.get('children', []))
    print(f'{len(people)} first-gen ({n_edu} educators, years {min(years)}–{max(years)}), '
          f'{n_desc} descendants')
    print(f'wrote {out}')


def get_opt(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def main():
    args = sys.argv[1:]
    surveys = get_opt(args, '--survey')
    base_in = (get_opt(args, '--base') or [None])[0]
    write_base = (get_opt(args, '--write-base') or [None])[0]

    if base_in:
        # CI path: start from the committed, email-free base snapshot
        tree = json.load(open(base_in))
        for sv in surveys:
            merge_survey(tree, sv)
        write_review()
        refresh_photos(tree)
        write_tree(tree)
        return

    if not args or args[0].startswith('--'):
        sys.exit('usage: build_data.py <contact-list.xlsx> [--write-base data/base.json] '
                 '[--survey responses.csv ...]\n'
                 '       build_data.py --base data/base.json [--survey responses.csv ...]')
    src = args[0]
    rows = read_rows(src)[1:]  # skip header

    people = []
    seen = set()
    for cells in rows:
        first, last = cells.get(0, ''), cells.get(1, '')
        note = cells.get(2, '')
        if not first and not last:
            continue
        pid = slugify(first, last)
        if pid in seen:
            print(f'WARNING duplicate id {pid}', file=sys.stderr)
        seen.add(pid)
        sort_key, display, kind, year = parse_batch(note)
        if kind in ('postdoc', 'visitor'):
            continue          # the tree is students only
        edu = EDUCATORS.get(pid)
        person = {
            'id': pid,
            'name': f'{first} {last}'.strip(),
            'batch': display,
            'kind': kind,
            'year': year,
            'sortKey': sort_key,
            'decade': decade_bin(kind, year),
            'educator': bool(edu),
            'affiliation': edu[0] if edu else ('UC Berkeley' if kind in ('current', 'postdoc', 'visitor') else None),
            'title': edu[1] if edu else None,
            'inMemoriam': pid in IN_MEMORIAM,
            # photos/<id>.jpg — from the survey, or web-collected as bootstrap
            'photo': f'photos/{pid}.jpg' if os.path.exists(f'photos/{pid}.jpg') else None,
            'children': [],          # next generation, filled in from survey
        }
        people.append(person)

    people.sort(key=lambda p: (p['sortKey'], p['name']))
    for p in people:
        del p['sortKey']

    tree = {
        'id': 'tomizuka',
        'name': 'Masayoshi Tomizuka',
        'title': 'Cheryl and John Neerhout, Jr. Distinguished Professor',
        'affiliation': 'UC Berkeley · Mechanical Engineering',
        'photo': 'assets/tomizuka.jpg',
        'children': people,
    }

    if write_base:
        with open(write_base, 'w') as f:
            json.dump(tree, f, ensure_ascii=False, indent=1)
        print(f'wrote {write_base} (sanitized base — safe to commit)')

    for sv in surveys:
        merge_survey(tree, sv)
    refresh_photos(tree)
    write_tree(tree)


if __name__ == '__main__':
    main()

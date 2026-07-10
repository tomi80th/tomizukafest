#!/usr/bin/env python3
"""Ingest survey-submitted photos (the photo_url column) into photos/.

Policy: photos publish automatically; a human reviews photos.html weekly and
blocks bad ones by adding the person-id to photos/blocklist.txt (one id per
line). Blocked ids get their file deleted and are never re-ingested.

Usage:
    python3 scripts/ingest_photos.py [responses.csv ...]

Run from the repo root, after build_data.py (needs data/tree.js for the
name -> id mapping) and before a second build_data.py pass (which refreshes
photo paths in the rendered data). Requires Pillow.
"""
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import norm_name  # the same matcher the survey merge uses

MANIFEST = 'photos/manifest.json'
BLOCKLIST = 'photos/blocklist.txt'
MAX_BYTES = 15_000_000


def load_tree():
    s = open('data/tree.js').read()
    return json.loads(re.sub(r'^.*?window\.TREE_DATA = ', '', s, flags=re.S).rstrip(';\n'))


def name_index(tree):
    """norm-name -> [(advisor-norm, id), ...]. Namesakes are real (three on the
    tree already), so a bare name is not an identity — (name x advisor) is."""
    idx = {}
    stack = [(c, tree.get('name') or '') for c in tree.get('children', [])]
    while stack:
        n, parent = stack.pop()
        idx.setdefault(norm_name(n['name']), []).append((norm_name(parent), n['id']))
        stack.extend((c, n['name']) for c in n.get('children', []))
    return idx


def resolve(idx, name, advisor):
    cands = idx.get(norm_name(name)) or []
    if len(cands) == 1:
        return cands[0][1]
    adv = norm_name(advisor or '')
    for parent, pid in cands:
        if parent == adv:
            return pid
    return None  # ambiguous namesake, no advisor match — never guess a face


IMG_HINTS = ('profile', 'avatar', 'portrait', 'headshot', 'prof_pic',
             'author', 'me.jpg', 'me.jpeg', 'me.png', 'me.webp')
IMG_BLOCK = ('logo', 'banner', 'icon', 'favicon', 'preview', 'publication',
             'badge', 'sprite', 'qrcode')


def extract_portrait(path, base_url):
    """People paste page links (faculty pages, personal sites) rather than
    direct image URLs. Try og:image / twitter:image first, then look for an
    <img> that smells like the site owner's portrait (academic-homepage
    templates use profile/avatar/me.jpg naming conventions)."""
    from urllib.parse import urljoin
    try:
        head = open(path, 'rb').read(500_000).decode('utf-8', 'replace')
    except OSError:
        return None
    low = head.lower()
    if '<meta' not in low and '<img' not in low:
        return None
    m = (re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*'
                   r'content=["\']([^"\']+)', head, re.I)
         or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*'
                      r'(?:property|name)=["\'](?:og:image|twitter:image)', head, re.I))
    if m:
        return urljoin(base_url, m.group(1))
    best, best_score = None, 0
    for im in re.finditer(r'<img[^>]+>', head, re.I):
        orig = im.group(0)
        tag = orig.lower()                       # match case-insensitively...
        sm = re.search(r'src=["\']([^"\']+)', orig, re.I)
        if not sm or any(b in tag for b in IMG_BLOCK):
            continue
        score = sum(1 for h in IMG_HINTS if h in tag)
        if score > best_score:
            best_score, best = score, sm.group(1)  # ...but keep the URL's case
    return urljoin(base_url, best) if best else None


def load_blocklist():
    ids = set()
    if os.path.exists(BLOCKLIST):
        for line in open(BLOCKLIST):
            line = line.strip()
            if line and not line.startswith('#'):
                ids.add(line)
    return ids


def main():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 60_000_000

    idx = name_index(load_tree())
    manifest = json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {}
    blocked = load_blocklist()

    for pid in sorted(blocked):
        p = f'photos/{pid}.jpg'
        if os.path.exists(p):
            os.remove(p)
            print(f'blocklist: removed {p}')
        manifest.pop(pid, None)

    for path in sys.argv[1:]:
        for r in csv.DictReader(open(path)):
            url = (r.get('photo_url') or '').strip()
            name = (r.get('name') or '').strip()
            if not name or not url.lower().startswith('http'):
                continue
            pid = resolve(idx, name, r.get('advisor'))
            if pid is None or pid in blocked:
                continue
            dst = f'photos/{pid}.jpg'
            if (manifest.get(pid) or {}).get('source') == url and os.path.exists(dst):
                continue  # this exact photo is already in
            tmp = f'/tmp/ingest_{pid}'

            def fetch(u):
                rc = subprocess.run(
                    ['curl', '-sL', '--max-time', '60',
                     '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                     '--max-filesize', str(MAX_BYTES), '-o', tmp, u],
                ).returncode
                return rc == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 2000

            def as_image():
                im = Image.open(tmp)
                im.load()
                return im

            if not fetch(url):
                print(f'skip {pid}: download failed ({url})')
                continue
            try:
                try:
                    im = as_image()
                except Exception:
                    # not an image — maybe a page; try its portrait once
                    og = extract_portrait(tmp, url)
                    if not (og and fetch(og)):
                        print(f'skip {pid}: not an image and no portrait found ({url})')
                        continue
                    im = as_image()
                if im.width < 80 or im.height < 80:
                    print(f'skip {pid}: too small {im.size}')
                    continue
                im = im.convert('RGB')
                im.thumbnail((240, 240))
                im.save(dst, 'JPEG', quality=88)
            except Exception as e:
                print(f'skip {pid}: not a usable image ({e})')
                continue
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
            manifest[pid] = {
                'source': url,
                'confidence': 'self-submitted (survey)',
                'ingested': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            }
            print(f'ingested {dst} <- {url}')

    json.dump(manifest, open(MANIFEST, 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()

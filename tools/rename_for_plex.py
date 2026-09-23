#!/usr/bin/env python3
"""Rename scene files into the only form Plex's TV scanner understands.

Plex's "Plex TV Series" scanner assigns no season/episode number to
`Show - YYYY-MM-DD - Title.ext` or to release-style `Show.YY.MM.DD.stuff.ext`,
so those files land in [Unknown Season] and can never bind to a provider
episode. `Show - S<year>E<MMDD> - Title.ext` parses cleanly and matches the
scheme tpdb-provider already uses (season = year, episode = MMDD).

Each rename is resolved against ThePornDB itself: the folder gives the site,
the filename gives the date, and the real scene title comes from the API.

Dry run by default. Nothing is touched without --apply.
"""
import argparse
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from tpdb_provider import tpdb  # noqa: E402

VIDEO_EXT = {'.mp4', '.mkv', '.avi', '.wmv', '.mov', '.m4v', '.mpg', '.mpeg', '.flv'}

# already correct - leave alone
DONE_RE = re.compile(r'\bS(\d{4})E(\d{3,4})\b', re.IGNORECASE)

DATE_PATTERNS = [
    # 2019-01-18 / 2019.01.18 / 2019_01_18
    (re.compile(r'(?<!\d)(20\d{2})[-._](\d{2})[-._](\d{2})(?!\d)'), 'ymd'),
    # 22.05.2012  (day.month.year)
    (re.compile(r'(?<!\d)(\d{2})[-._](\d{2})[-._](20\d{2})(?!\d)'), 'dmy'),
    # 24.06.27 release style (yy.mm.dd)
    (re.compile(r'(?<!\d)(\d{2})[-._](\d{2})[-._](\d{2})(?!\d)'), 'yy'),
]

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def parse_date(name):
    for regex, kind in DATE_PATTERNS:
        m = regex.search(name)
        if not m:
            continue
        a, b, c = m.groups()
        try:
            if kind == 'ymd':
                y, mo, d = int(a), int(b), int(c)
            elif kind == 'dmy':
                d, mo, y = int(a), int(b), int(c)
            else:
                y, mo, d = 2000 + int(a), int(b), int(c)
        except ValueError:
            continue
        if 1 <= mo <= 12 and 1 <= d <= 31 and 1990 <= y <= 2099:
            return '%04d-%02d-%02d' % (y, mo, d)
    return None


def sanitize(title):
    title = unicodedata.normalize('NFKC', title or '')
    title = ILLEGAL.sub('', title).strip().rstrip('.')
    return ' '.join(title.split())[:120]


def resolve_site(folder):
    sites = tpdb.search_sites(folder)
    if not sites:
        return None
    wanted = ' '.join(folder.split()).lower()
    for site in sites:
        if (site.get('name') or '').lower() == wanted:
            return site
    squashed = wanted.replace(' ', '')
    for site in sites:
        if (site.get('short_name') or '').lower() == squashed:
            return site
    return sites[0]


def scenes_by_date(site_id):
    index = {}
    for scene in tpdb.scenes_for_site(site_id):
        date = (scene.get('date') or '')[:10]
        if date:
            index.setdefault(date, []).append(scene)
    return index


def pick(scenes, filename):
    """Disambiguate same-day releases by title tokens in the filename."""
    if len(scenes) == 1:
        return scenes[0], False
    haystack = re.sub(r'[^a-z0-9]+', ' ', filename.lower())
    best, best_score = None, 0
    for scene in scenes:
        tokens = [t for t in re.sub(r'[^a-z0-9]+', ' ',
                                    (scene.get('title') or '').lower()).split()
                  if len(t) > 2]
        if not tokens:
            continue
        score = sum(1 for t in tokens if t in haystack) / float(len(tokens))
        if score > best_score:
            best, best_score = scene, score
    if best is not None and best_score >= 0.5:
        return best, False
    return scenes[0], True   # ambiguous


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root', help='library root, e.g. ".../Scenes Agent"')
    ap.add_argument('--apply', action='store_true', help='actually rename')
    ap.add_argument('--only', help='limit to one show folder')
    ap.add_argument('--report', default='rename_report.tsv')
    args = ap.parse_args()

    stats = {'ok': 0, 'ambiguous': 0, 'already': 0, 'no_date': 0,
             'no_scene': 0, 'no_site': 0, 'collision': 0}
    rows = []

    folders = sorted(d for d in os.listdir(args.root)
                     if os.path.isdir(os.path.join(args.root, d)))
    if args.only:
        folders = [d for d in folders if d == args.only]

    for folder in folders:
        path = os.path.join(args.root, folder)
        files = sorted(f for f in os.listdir(path)
                       if os.path.splitext(f)[1].lower() in VIDEO_EXT)
        if not files:
            continue

        site = resolve_site(folder)
        if not site:
            stats['no_site'] += len(files)
            for f in files:
                rows.append(('NO_SITE', folder, f, ''))
            print('  !! no TPDB site for folder %r (%d files)' % (folder, len(files)))
            continue

        by_date = scenes_by_date(site.get('id'))
        print('%-32s site=%-6s scenes=%-5d files=%d'
              % (folder[:32], site.get('id'), sum(map(len, by_date.values())), len(files)))

        for fname in files:
            stem, ext = os.path.splitext(fname)
            if DONE_RE.search(stem):
                stats['already'] += 1
                rows.append(('ALREADY', folder, fname, ''))
                continue

            date = parse_date(stem)
            if not date:
                stats['no_date'] += 1
                rows.append(('NO_DATE', folder, fname, ''))
                continue

            scenes = by_date.get(date)
            if not scenes:
                stats['no_scene'] += 1
                rows.append(('NO_SCENE', folder, fname, date))
                continue

            scene, ambiguous = pick(scenes, stem)
            year, mm, dd = date[:4], date[5:7], date[8:10]
            title = sanitize(scene.get('title')) or 'Untitled'
            new = '%s - S%sE%s%s - %s%s' % (folder, year, mm, dd, title, ext)

            if new == fname:
                stats['already'] += 1
                rows.append(('ALREADY', folder, fname, ''))
                continue

            dst = os.path.join(path, new)
            if os.path.exists(dst):
                stats['collision'] += 1
                rows.append(('COLLISION', folder, fname, new))
                continue

            stats['ambiguous' if ambiguous else 'ok'] += 1
            rows.append(('AMBIGUOUS' if ambiguous else 'RENAME',
                         folder, fname, new))

            if args.apply and not ambiguous:
                os.rename(os.path.join(path, fname), dst)

    with open(args.report, 'w') as fh:
        fh.write('status\tfolder\told\tnew\n')
        for row in rows:
            fh.write('\t'.join(row) + '\n')

    print()
    print('%s' % ('APPLIED' if args.apply else 'DRY RUN - nothing changed'))
    for key in ('ok', 'ambiguous', 'already', 'no_date', 'no_scene',
                'no_site', 'collision'):
        print('  %-10s %d' % (key, stats[key]))
    print('  report -> %s' % args.report)
    if not args.apply:
        print('\nRe-run with --apply to rename (AMBIGUOUS rows are skipped).')


if __name__ == '__main__':
    main()

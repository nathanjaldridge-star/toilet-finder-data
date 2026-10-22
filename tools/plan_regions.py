#!/usr/bin/env python3
"""Split the world into Geofabrik extracts small enough for a GitHub runner, grouped into N balanced jobs.

Top-level regions bigger than --max-gb are replaced by their children (recursively), so peak disk per job stays
around two files of at most --max-gb. Prints a JSON matrix: {"include": [{"group": 0, "regions": "a b c", "gb": 9.1}, ...]}
Usage: plan_regions.py [--jobs 8] [--max-gb 6]  (reads https://download.geofabrik.de/index-v1-nogeom.json)
"""
import argparse, json, sys, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('--jobs', type=int, default=8)
ap.add_argument('--max-gb', type=float, default=6)
ap.add_argument('--index', default='https://download.geofabrik.de/index-v1-nogeom.json')
a = ap.parse_args()
UA = {'User-Agent': 'ToiletFinder-dataset-builder/1.0 (+https://github.com/nathanjaldridge-star/toilet-finder-data)'}


def fetch(url, method='GET'):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA, method=method), timeout=60)


idx = json.load(fetch(a.index))
feats = [f['properties'] for f in idx['features']]
children = {}
for p in feats:
    children.setdefault(p.get('parent'), []).append(p)


def size(p):
    try:
        return int(fetch(p['urls']['pbf'], 'HEAD').headers.get('Content-Length', 0))
    except Exception:
        return 0


def path(p):  # region path as used in the download URL, e.g. europe/germany
    return p['urls']['pbf'].split('download.geofabrik.de/')[1].rsplit('-latest.osm.pbf', 1)[0]


# Geofabrik also publishes overlapping convenience groupings next to the real countries/states; skip them so every
# area is downloaded once (overlaps at borders are harmless, build_tiles.py dedupes by OSM id).
EXCLUDE = {'alps', 'britain-and-ireland', 'dach', 'great-britain', 'us', 'us-midwest', 'us-northeast', 'us-pacific',
           'us-south', 'us-west', 'south-africa-and-lesotho', 'sea'}
out = []


def visit(p):
    if p['id'] in EXCLUDE:
        return
    s = size(p) or size(p)
    kids = children.get(p['id'], [])
    if s > a.max_gb * 1e9 and kids:
        for k in kids:
            visit(k)
    else:
        out.append((path(p), s))


for p in children[None]:
    visit(p)
groups = [{'group': i, 'regions': [], 'bytes': 0} for i in range(a.jobs)]
for r, s in sorted(out, key=lambda x: -x[1]):
    g = min(groups, key=lambda g: g['bytes'])
    g['regions'].append(r); g['bytes'] += s
print(json.dumps({'include': [{'group': g['group'], 'regions': ' '.join(g['regions']), 'gb': round(g['bytes'] / 1e9, 1)} for g in groups if g['regions']]}))
print('regions: %d, total %.1f GB' % (len(out), sum(s for _, s in out) / 1e9), file=sys.stderr)

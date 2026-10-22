#!/usr/bin/env python3
"""Turn osmium geojsonseq extracts into the static tile dataset the apps load.

Input: one or more *.geojsonseq files from extract.sh (amenity=toilets, toilets=yes and opening_hours objects,
with osmium ids like n123 / w45 / r6). Output (OUTDIR):
  index.json           {v, deg, generated, attribution, licence, counts}
  tiles.json           {key: [toilets, customersOnly, bytes]}
  tiles/<key>.json     {v, k, t: [[type, id, lat, lon, tags], ...], p: [[type, id, lat, lon, [s,w,n,e]|0, tags], ...]}
Tile key = floor(lat/deg)_floor(lon/deg). "t" are toilets (amenity=toilets, plus businesses/venues tagged
toilets=yes); "p" are "parent" features with opening_hours that contain or sit next to a toilet without hours,
so the apps can infer hours offline exactly like they do from the Overpass parents query.
"""
import argparse, glob, json, math, os, sys, time
from collections import defaultdict

KEEP_TOILET = ['amenity', 'toilets', 'name', 'opening_hours', 'check_date:opening_hours', 'wheelchair', 'fee', 'access',
               'toilets:access', 'toilets:wheelchair', 'toilets:fee', 'toilets:opening_hours', 'operator', 'male', 'female',
               'unisex', 'gender_segregated', 'toilets:position', 'urinal', 'toilets:urinal', 'toilets:urinals',
               'changing_table', 'diaper', 'shop', 'tourism', 'leisure', 'railway', 'public_transport', 'brand']
# Same tables as app/lib/data.js (PARENT_AREA / NODE_PARENT); keep in sync.
PARENT_AREA = {
    'leisure': ['park', 'garden', 'playground', 'recreation_ground', 'nature_reserve', 'sports_centre', 'stadium', 'common', 'dog_park'],
    'amenity': ['library', 'marketplace', 'community_centre', 'townhall', 'theatre', 'cinema', 'arts_centre', 'bus_station', 'ferry_terminal', 'pub', 'bar', 'cafe', 'restaurant', 'fast_food', 'hospital', 'college', 'university', 'school'],
    'railway': ['station', 'halt', 'tram_stop', 'subway_entrance'],
    'public_transport': ['station'],
    'tourism': ['museum', 'gallery', 'attraction', 'zoo', 'theme_park', 'information'],
    'shop': ['mall', 'supermarket', 'department_store', 'convenience', 'general'],
    'building': ['retail', 'commercial', 'supermarket', 'train_station', 'public', 'civic', 'museum', 'transportation'],
    'landuse': ['cemetery', 'recreation_ground'],
    'historic': ['castle', 'monument', 'ruins'],
}
NODE_PARENT = {'railway': ['station', 'halt'], 'public_transport': ['station'], 'amenity': ['library', 'community_centre', 'townhall', 'bus_station'],
               'tourism': ['museum', 'gallery', 'attraction'], 'leisure': ['park', 'garden']}
KEEP_PARENT = ['leisure', 'railway', 'public_transport', 'amenity', 'tourism', 'shop', 'building', 'landuse', 'historic', 'name', 'opening_hours']
PRIVATE = {'private', 'no'}


def category(tags, table):
    for k, vals in table.items():
        if tags.get(k) in vals:
            return k
    return None


def geom_bounds(g):
    """-> (s, w, n, e) of a GeoJSON geometry."""
    t, c = g['type'], g['coordinates']
    if t == 'Point':
        return c[1], c[0], c[1], c[0]
    s = w = 1e9; n = e = -1e9
    stack = [c]
    while stack:
        x = stack.pop()
        if x and isinstance(x[0], (int, float)):
            lon, lat = x[0], x[1]
            if lat < s: s = lat
            if lat > n: n = lat
            if lon < w: w = lon
            if lon > e: e = lon
        else:
            stack.extend(x)
    return s, w, n, e


def r5(x):
    return round(x, 5)


def dist(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    dlat, dlon = (lat2 - lat1) * r, (lon2 - lon1) * r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(dlon / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(min(1, a)))


def read_features(path):
    with open(path, 'rb') as f:
        for line in f:
            line = line.strip().lstrip(b'\x1e')
            if line:
                yield json.loads(line)


class Grid:
    """Points bucketed in ~0.005 deg cells for neighbour lookups."""
    C = 0.005

    def __init__(self):
        self.cells = defaultdict(list)

    def key(self, lat, lon):
        return int(math.floor(lat / self.C)), int(math.floor(lon / self.C))

    def add(self, lat, lon, item):
        self.cells[self.key(lat, lon)].append(item)

    def near(self, lat, lon, ring=1):
        a, b = self.key(lat, lon)
        for i in range(a - ring, a + ring + 1):
            for j in range(b - ring, b + ring + 1):
                yield from self.cells.get((i, j), ())


def _ident(f):
    fid = f.get('id') or ''
    typ = {'n': 'node', 'w': 'way', 'r': 'relation', 'a': 'way'}.get(fid[:1])
    return (typ, int(fid[1:])) if typ and fid[1:].isdigit() else (None, None)


def process_region(path, deg, sink, stats):
    # Pass 1: toilets and venues (and the operators of hourless toilets, for name-matched parents).
    toilets, venues, operators = {}, {}, set()
    for f in read_features(path):
        tags = f.get('properties') or {}
        if not tags or not f.get('geometry') or not (tags.get('amenity') == 'toilets' or tags.get('toilets') == 'yes'):
            continue
        typ, oid = _ident(f)
        if not typ:
            continue
        s, w, n, e = geom_bounds(f['geometry'])
        lat, lon = (s + n) / 2, (w + e) / 2
        key = typ[0] + str(oid)
        if tags.get('amenity') == 'toilets':
            if tags.get('access') in PRIVATE or tags.get('toilets:access') in PRIVATE:
                stats['private_skipped'] += 1
                continue
            toilets[key] = (typ, oid, lat, lon, {k: tags[k] for k in KEEP_TOILET if k in tags})
            if not tags.get('opening_hours') and tags.get('operator'):
                operators.add(tags['operator'].lower())
        else:
            if tags.get('toilets:access') in PRIVATE or tags.get('access') in PRIVATE:
                stats['private_skipped'] += 1
                continue
            venues[key] = (typ, oid, lat, lon, {k: tags[k] for k in KEEP_TOILET if k in tags})
    # Pass 2: candidate parents (features with opening_hours of a parent kind, or named like a toilet's operator).
    parents = {}
    for f in read_features(path):
        tags = f.get('properties') or {}
        if not tags.get('opening_hours') or tags.get('amenity') == 'toilets' or not f.get('geometry'):
            continue
        typ, oid = _ident(f)
        if not typ:
            continue
        s, w, n, e = geom_bounds(f['geometry'])
        area = n > s or e > w
        if category(tags, PARENT_AREA if area else NODE_PARENT) or (tags.get('name') or '').lower() in operators:
            parents[typ[0] + str(oid)] = (typ, oid, (s + n) / 2, (w + e) / 2, (s, w, n, e) if area else None, {k: tags[k] for k in KEEP_PARENT if k in tags})

    grid = Grid()
    for t in toilets.values():
        grid.add(t[2], t[3], t)
    # A venue tagged toilets=yes with a mapped amenity=toilets within 30 m is the same facility: keep the toilet.
    for k, v in list(venues.items()):
        if any(dist(v[2], v[3], t[2], t[3]) <= 30 for t in grid.near(v[2], v[3])):
            del venues[k]
            stats['venues_deduped'] += 1

    # Parents worth shipping: areas whose bbox (padded ~3 m) holds an hourless toilet, nodes within 60 m of one.
    hourless = Grid()
    for t in toilets.values():
        if not t[4].get('opening_hours'):
            hourless.add(t[2], t[3], t)
    for p in parents.values():
        typ, oid, lat, lon, b, tags = p
        hit_tiles = set()
        if b:
            if not category(tags, PARENT_AREA) and not tags.get('name'):
                continue
            pad = 0.00003
            s, w, n, e = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
            if (n - s) < 0.05 and (e - w) < 0.05:
                cands = (t for i in range(int(math.floor(s / Grid.C)), int(math.floor(n / Grid.C)) + 1)
                         for j in range(int(math.floor(w / Grid.C)), int(math.floor(e / Grid.C)) + 1)
                         for t in hourless.cells.get((i, j), ()))
            else:
                cands = (t for cell in hourless.cells.values() for t in cell)
            for t in cands:
                if s <= t[2] <= n and w <= t[3] <= e and (category(tags, PARENT_AREA) or (t[4].get('operator') or '').lower() == (tags.get('name') or '').lower()):
                    hit_tiles.add(tile_key(t[2], t[3], deg))
        else:
            for t in hourless.near(lat, lon):
                d = dist(lat, lon, t[2], t[3])
                if (category(tags, NODE_PARENT) and d <= 25) or (d <= 60 and tags.get('name') and (t[4].get('operator') or '').lower() == tags['name'].lower()):
                    hit_tiles.add(tile_key(t[2], t[3], deg))
        if hit_tiles:
            row = [typ[0], oid, r5(lat), r5(lon), [r5(x) for x in b] if b else 0, tags]
            for k in hit_tiles:
                sink(k, 'p', row)
            stats['parents'] += 1

    for t in list(toilets.values()) + list(venues.values()):
        sink(tile_key(t[2], t[3], deg), 't', [t[0][0], t[1], r5(t[2]), r5(t[3]), t[4]])
    stats['toilets'] += len(toilets)
    stats['venues'] += len(venues)


def tile_key(lat, lon, deg):
    return '%d_%d' % (math.floor(lat / deg), math.floor(lon / deg))


PUBLIC_VENUE = {('amenity', v) for v in ['library', 'townhall', 'community_centre', 'bus_station', 'ferry_terminal', 'marketplace', 'place_of_worship', 'hospital', 'shelter']} | \
               {('leisure', v) for v in ['park', 'garden', 'playground', 'recreation_ground', 'nature_reserve', 'common', 'beach_resort']} | \
               {('railway', v) for v in ['station', 'halt']} | {('public_transport', 'station')} | {('shop', 'mall')} | {('tourism', 'information')}


def is_customers_only(tags):
    """Same rule as Data.customersOnly in app/lib/data.js."""
    if tags.get('amenity') == 'toilets':
        return tags.get('access') == 'customers' or tags.get('toilets:access') == 'customers'
    if tags.get('toilets:access') in ('yes', 'public', 'permissive'):
        return False
    return not any((k, tags.get(k)) in PUBLIC_VENUE for k in ('amenity', 'leisure', 'railway', 'public_transport', 'shop', 'tourism'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--deg', type=float, default=0.5)
    ap.add_argument('--tmp', default=None)
    a = ap.parse_args()
    tmp = a.tmp or os.path.join(a.out, '..', '_tiles_tmp')
    os.makedirs(tmp, exist_ok=True)
    for f in glob.glob(os.path.join(tmp, '*.ndjson')):
        os.remove(f)
    handles = {}

    def sink(key, kind, row):
        fh = handles.get(key)
        if fh is None:
            if len(handles) > 800:
                for h in handles.values():
                    h.close()
                handles.clear()
            fh = handles[key] = open(os.path.join(tmp, key + '.ndjson'), 'a')
        fh.write(json.dumps([kind, row], separators=(',', ':'), ensure_ascii=False) + '\n')

    stats = defaultdict(int)
    files = []
    for p in a.inputs:
        files.extend(sorted(glob.glob(p)) if any(ch in p for ch in '*?') else [p])
    for p in files:
        t0 = time.time()
        before = dict(stats)
        process_region(p, a.deg, sink, stats)
        print('%s: +%d toilets +%d venues +%d parents (%.0fs)' % (os.path.basename(p), stats['toilets'] - before.get('toilets', 0),
              stats['venues'] - before.get('venues', 0), stats['parents'] - before.get('parents', 0), time.time() - t0), flush=True)
    for h in handles.values():
        h.close()

    tdir = os.path.join(a.out, 'tiles')
    os.makedirs(tdir, exist_ok=True)
    for f in glob.glob(os.path.join(tdir, '*.json')):
        os.remove(f)
    index, total, cust, total_bytes, wheel, hours = {}, 0, 0, 0, 0, 0
    for path in sorted(glob.glob(os.path.join(tmp, '*.ndjson'))):
        key = os.path.basename(path)[:-7]
        ts, ps = {}, {}
        with open(path) as fh:
            for line in fh:
                kind, row = json.loads(line)
                (ts if kind == 't' else ps)[row[0] + str(row[1])] = row  # regions overlap at borders: dedupe by id
        rows = sorted(ts.values(), key=lambda r: (r[2], r[3]))
        c = sum(1 for r in rows if is_customers_only(r[4]))
        body = json.dumps({'v': 1, 'k': key, 't': rows, 'p': sorted(ps.values(), key=lambda r: (r[2], r[3]))}, separators=(',', ':'), ensure_ascii=False)
        with open(os.path.join(tdir, key + '.json'), 'w') as out:
            out.write(body)
        n = len(body.encode('utf-8'))
        index[key] = [len(rows), c, n]
        total += len(rows); cust += c; total_bytes += n
        wheel += sum(1 for r in rows if r[4].get('wheelchair') == 'yes' or r[4].get('toilets:wheelchair') == 'yes')
        hours += sum(1 for r in rows if r[4].get('opening_hours'))
        os.remove(path)
    meta = {
        'v': 1, 'deg': a.deg, 'generated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': 'OpenStreetMap via Geofabrik extracts, filtered with osmium',
        'attribution': '© OpenStreetMap contributors, ODbL 1.0', 'licence': 'https://opendatacommons.org/licenses/odbl/1-0/',
        'counts': {'toilets': total, 'public': total - cust, 'customersOnly': cust, 'withHours': hours, 'wheelchairYes': wheel,
                   'parents': stats['parents'], 'privateSkipped': stats['private_skipped'], 'venuesDeduped': stats['venues_deduped'],
                   'tiles': len(index), 'bytes': total_bytes},
    }
    with open(os.path.join(a.out, 'index.json'), 'w') as out:
        json.dump(meta, out, separators=(',', ':'))
    # Per-tile [toilets, customersOnly, bytes]; the apps don't need it (a missing tile is a 404), tooling does.
    with open(os.path.join(a.out, 'tiles.json'), 'w') as out:
        json.dump(index, out, separators=(',', ':'))
    print(json.dumps(meta['counts']))


if __name__ == '__main__':
    main()

# Toilet Finder data

Worldwide public-toilet tiles from OpenStreetMap for the [Toilet Finder](https://nathanjaldridge-star.github.io/toilet-finder-app/) app.

- **Live data:** https://nathanjaldridge-star.github.io/toilet-finder-data/ (branch `gh-pages`, rebuilt weekly)
- `v1/index.json`: build time, counts, attribution
- `v1/tiles/<floor(lat/0.5)>_<floor(lon/0.5)>.json`: one 0.5° tile; a 404 means no toilets there
- `v1/tiles.json`: every tile with `[toilets, customersOnly, bytes]`

Tile format: `{"v":1,"k":"103_-1","t":[[type,id,lat,lon,tags],...],"p":[[type,id,lat,lon,[s,w,n,e]|0,tags],...]}` where
`type` is `n`/`w`/`r` (OSM node/way/relation, ways and relations reduced to their bounding-box centre), `t` holds toilets
(`amenity=toilets`, plus venues tagged `toilets=yes`, which the app shows as "customers only" unless they are public
venues such as parks or stations) and `p` holds nearby features with `opening_hours` used to infer a toilet's hours.

## How it's built

1. `tools/plan_regions.py` splits the world into Geofabrik extracts of at most ~6 GB and balances them over 8 jobs.
2. `tools/extract.sh` downloads each extract, keeps `amenity=toilets`, `toilets=yes` and `opening_hours` objects with
   `osmium tags-filter`, exports them with `osmium export`, and deletes the extract.
3. `tools/build_tiles.py` merges everything (deduping by OSM id), drops private toilets, keeps the tags the app uses and
   writes the tiles.
4. `.github/workflows/build-data.yml` runs this every Monday and force-pushes the result to `gh-pages` as a single commit
   (no history, so the repo stays small).

Run locally: `bash tools/extract.sh /var/tmp/osm europe/united-kingdom && python3 tools/build_tiles.py '/var/tmp/osm/out/*.geojsonseq' --out site/v1`

## Licence

**Data © OpenStreetMap contributors, [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).** See
[site-static/LICENSE.md](site-static/LICENSE.md). Build scripts: MIT.

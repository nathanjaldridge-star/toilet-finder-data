#!/usr/bin/env bash
# Extract every amenity=toilets, toilets=yes and opening_hours object worldwide (the latter for parent-hours inference) from Geofabrik continent extracts.
# One region at a time (download -> osmium tags-filter -> osmium export -> delete), downloading the next
# region while the current one is filtered, so peak disk use is roughly the two largest regions (~55 GB).
# Usage: extract.sh WORKDIR [region ...]   (default: all Geofabrik top-level regions)
set -euo pipefail
WORK=${1:?workdir}; shift || true
REGIONS=("$@")
[ ${#REGIONS[@]} -eq 0 ] && REGIONS=(antarctica central-america australia-oceania south-america russia africa asia north-america europe)
UA="ToiletFinder-dataset-builder/1.0 (+https://github.com/nathanjaldridge-star/toilet-finder-app)"
mkdir -p "$WORK/out"
cd "$WORK"
# Regions are Geofabrik paths such as "europe" or "europe/germany"; files use "_" for "/".
dl() { # region -> region.osm.pbf (resumable)
  local u=$1 r=${1//\//_}
  [ -s "out/$r.geojsonseq" ] && return 0
  curl -sSfL --retry 5 --retry-delay 10 -C - -A "$UA" -o "$r.osm.pbf.part" "https://download.geofabrik.de/$u-latest.osm.pbf"
  mv "$r.osm.pbf.part" "$r.osm.pbf"
}
filt() {
  local r=${1//\//_}
  [ -s "out/$r.geojsonseq" ] && { echo "skip $r"; return 0; }
  osmium tags-filter --overwrite -o "$r.toilets.osm.pbf" "$r.osm.pbf" nwr/amenity=toilets nwr/toilets=yes nwr/opening_hours
  rm -f "$r.osm.pbf"
  osmium export --overwrite -f geojsonseq -u type_id -o "out/$r.geojsonseq.tmp" "$r.toilets.osm.pbf"
  mv "out/$r.geojsonseq.tmp" "out/$r.geojsonseq"
  rm -f "$r.toilets.osm.pbf"
  echo "$(date -Is) done $r $(wc -l < out/$r.geojsonseq) features"
}
pid=""
dl "${REGIONS[0]}"
for i in "${!REGIONS[@]}"; do
  r=${REGIONS[$i]}
  [ -n "$pid" ] && wait "$pid"
  next=${REGIONS[$((i+1))]:-}
  if [ -n "$next" ]; then dl "$next" & pid=$!; else pid=""; fi
  echo "$(date -Is) filtering $r"
  filt "$r"
done
[ -n "$pid" ] && wait "$pid"
echo "$(date -Is) all regions done"

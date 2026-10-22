# Data licence

The toilet tiles in `v1/` are a derived database extracted from OpenStreetMap.

**© OpenStreetMap contributors.** The data is made available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Individual contents are under the [Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/).
See https://www.openstreetmap.org/copyright.

If you use this data you must:
- credit "© OpenStreetMap contributors" wherever the data is shown, and
- share any adapted version of the database under the ODbL.

What was done to the source data: objects tagged `amenity=toilets` and `toilets=yes` were selected (toilets with
`access=private|no` dropped; venues within 30 m of a mapped toilet dropped as duplicates), ways and relations were
reduced to the centre of their bounding box, tags were reduced to the ones listed in `tools/build_tiles.py`, and nearby
features with `opening_hours` (parks, stations, libraries...) were kept so hours can be inferred.

The build scripts (`tools/`) are MIT licensed.

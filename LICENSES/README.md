# Licences

| Material | Licence | File |
|---|---|---|
| Code in this repository (pipeline, tests, workflows) | GPL-3.0-or-later | `../LICENSE` |
| Data derived from OpenStreetMap (`businesses-*` packs) | ODbL-1.0, attribution "© OpenStreetMap contributors" | `ODbL-1.0.txt` (text from the SPDX licence list), `sources/osm.md` |
| Rules (`rules-*.json`) | GPL-3.0-or-later (curated by this project, citing public legal sources) | `sources/` notes |
| Spam sources | One note per source in `sources/<sourceId>.md`; a source is packaged only when its licence allows redistribution | `sources/` |

Every source card under `sources/` must have a matching `LICENSES/sources/<id>.md`; the licence audit fails otherwise.

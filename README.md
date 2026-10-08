# UltimatePhone-data

Data packs for [UltimatePhone](https://github.com/qtekfun/UltimatePhone): business names by phone number
(derived from OpenStreetMap) and prefix rules. They are published as releases of this repository, signed, and the app
downloads only the packs it needs. Same layout as [UltimateMaps-data](https://github.com/qtekfun/UltimateMaps-data).

Stable manifest (always the latest release):
`https://github.com/qtekfun/UltimatePhone-data/releases/latest/download/manifest.json`
(signature next to it: `.../manifest.json.sig`).

## What a release contains

Tag `data-<YYYY.MM.DD>` (`-2`, `-3`, ... if there is more than one release that day). Only the two newest data releases
are kept; older ones and their tags are deleted. **Every release is complete and self-contained**: packs that were
not rebuilt in that run are copied from the previous release, so no URL in a manifest points at a pruned release.

| Asset | What |
|---|---|
| `manifest.json` | List of packs: id, type, region, version, url, sha256, bytes, entries, license, attribution, dependsOn, compression, uncompressedBytes, uncompressedSha256 (+ `sourceId` for spam packs). Schema: `pipeline/schemas/manifest.schema.json` |
| `manifest.json.sig` | Detached Ed25519 signature of `manifest.json` (see below) |
| `SHA256SUMS` | `sha256sum` format, every other asset |
| `businesses-<region>.db.xz` | SQLite pack of businesses (ES, DE, AT to start), XZ-compressed |
| `spam-<sourceId>.db.xz` | SQLite pack of one spam source, **only** for sources licensed for redistribution (none yet) |
| `rules-<country>.json` | Prefix rules, small, uncompressed JSON (`compression: "none"`) |

### Pack formats

`businesses-<region>.db` (SQLite):

- `numbers(e164 TEXT PRIMARY KEY, name, brand, category, osm_id, alt_names)`: `alt_names` is a JSON array with up to
  `max_alternatives` other names for the same number (best-quality name wins, ties by lowest OSM id).
- `numbers_fts`: FTS5 external-content table over `numbers.name` (`unicode61 remove_diacritics 2`, so "cafe" finds
  "Café"). Join with `numbers` on `rowid`.
- `meta(key, value)`: `packId, schema, type, version, region, country, generatedAt, license, licenseUrl, attribution,
  sourceUrls, entries, entriesWithAlternatives, entriesByCategory, elementsBusiness, elementsWithPhone,
  coveragePercent, coverageByCategory, phonesRaw, phonesInvalidDropped, skippedNoName, categories` (category to icon).
- Categories (short list, with icon names) are defined in `pipeline/categories.py`.
- **Coverage is partial.** `coveragePercent` is the share of named, business-like OSM elements that have a mapped
  phone, measured per region and meant to be shown in the app. Do not promise full coverage.

`spam-<sourceId>.db`: `numbers(e164 PRIMARY KEY, label, category, source_id)`, `prefix_rules(prefix PRIMARY KEY, label,
source_id)` (prefix as `+<country code><digits>`), `meta`. `source_id` keeps the origin for "why was this flagged".

`rules-<country>.json`: `{"schema":1,"version":"<date>","rules":[{"id","country","prefix","level":"RULE","kind",
"source","sourceUrl"?,"note"}]}`, schema in `pipeline/schemas/rules.schema.json`. `prefix` is the leading digits of the
national number. The Spanish `400` rule is informational ("commercial call", BOE-A-2026-8409): a 400 caller is a
legitimate commercial call that identifies itself, **not spam** (deviation D-001 in the app repository).

## How a client verifies a release (for the Kotlin side)

1. Download `manifest.json` and `manifest.json.sig` from the same release (or from `releases/latest/download/`).
2. **Algorithm**: Ed25519 (RFC 8032, pure Ed25519, no prehash, no context).
3. **Public key**: 32 raw bytes, base64: `93NQ1gRJSj3HNkz7IqVhq+BMDCbpiKuKNdFothEGvEk=` (also in
   `keys/manifest-public-key.txt`). Embed it in the app. On the JVM, wrap the raw key in an X.509 SubjectPublicKeyInfo
   by prefixing the bytes `30 2a 30 05 06 03 2b 65 70 03 21 00`, or use a library that takes raw keys.
4. **What is signed**: the exact bytes of `manifest.json` as downloaded (no re-serialisation, no newline changes).
5. **Signature encoding**: `manifest.json.sig` is the standard base64 (RFC 4648, with padding) of the 64-byte
   signature, followed by one `\n`. Trim whitespace, base64-decode, require exactly 64 bytes, verify.
6. Reject the manifest if verification fails. Only then parse it (UTF-8 JSON, `schema` must be `1`).
7. For each pack to install: download `url`, check `bytes` and `sha256` (hex, lower-case, of the file as served, i.e. the
   compressed file for `compression: "xz"`), then decompress.
8. **Compression** `xz`: standard `.xz` container, LZMA2, CRC64 check, dictionary of at most 8 MiB (a pure-Java reader
   such as `org.tukaani:xz` is enough). After decompression check `uncompressedBytes` and `uncompressedSha256`
   (hex SHA-256 of the `.db`). `compression: "none"` packs (rules) are used as downloaded.
9. Installing a pack means replacing its file. Compare `version` (`YYYY.MM.DD`) per pack id to decide what to download.

`python -m pipeline verify --dir <release dir>` does all of this (plus `SHA256SUMS`, a schema check and a smoke test
that every pack opens and answers a known-number query and an FTS query) and runs in CI before anything is published.

## Pipeline

```
sources/                  what to build (cards; no code)
  businesses/osm.yaml       regions, stable Geofabrik extract URLs, OSM tags
  businesses/other-open.yaml  other open sources (empty: each needs a verified licence)
  spam/*.yaml               one card per spam source: id, name, url, format, licence, redistribution, level, frequency
  rules/*.yaml              prefix rules per country
pipeline/                 Python 3.12 (python -m pipeline <command>)
tests/                    pytest with tiny committed fixtures (tests/fixtures, regenerate with tests/make_fixtures.py)
scripts/                  next-tag.sh and publish.sh (used by the build workflows, syntax-checked in CI)
keys/manifest-public-key.txt
LICENSES/                 ODbL text and one licence note per source
```

Commands: `audit`, `businesses --region ES [--prefilter] [--input file.osm.pbf]`, `spam`, `rules`,
`fetch-previous`, `assemble`, `verify`. Work files go to `work/`, output to `dist/` (both git-ignored).

### OSM reading: pyosmium, with osmium-tool as an optional prefilter

The pipeline reads extracts with **pyosmium** (`osmium` wheel, pinned), streaming. Reason: it needs no system binary
for the tests and fixtures, reads `.osm.pbf` and `.osm` identically, and we only need tags and ids (no geometry), so
memory stays flat. Candidates go to an on-disk SQLite staging table (never a Python dict); dedupe is a sorted
`GROUP`-style pass. In CI the large extracts are first shrunk with **osmium-tool** (`osmium tags-filter nwr/shop
nwr/amenity ...`, `--prefilter`), which is much faster on Germany-sized files; the filter keeps every element with a
business key regardless of phone, so the coverage denominator stays correct. The Overpass API is never used.

### Build rules

- Keep elements with `phone`, `contact:phone` or `contact:mobile` and a business tag (`amenity`, `shop`, `office`,
  `craft`, `healthcare`, `tourism`, `leisure`) that maps to a category. Name is `name`, falling back to `brand`, then
  `operator`; elements with no name at all are skipped and counted.
- Split on `;` and `,`, normalise to E.164 with `phonenumbers` using the region's country as default (numbers with an
  explicit `+` keep their own country); invalid numbers are dropped and counted (`phonesInvalidDropped`).
- Adding a region (or splitting a large country into several `extracts`) is a change to `osm.yaml`, not to code.

### Workflows

| Workflow | When | What |
|---|---|---|
| `verify.yml` | PRs, pushes to `main` | workflow YAML + `bash -n` of every `run:` block and `scripts/*.sh`; yamllint; **licence audit** (fails if any source card lacks `licence` or `redistribution`, a licence note, or fits no schema); pytest |
| `build-businesses.yml` | monthly (day 1) and manual (`regions`, `dry_run`) | frees disk, installs osmium-tool, rebuilds the chosen regions, carries over everything else from the latest release, signs, verifies, publishes `data-<date>` and prunes to the 2 newest |
| `build-spam.yml` | daily and manual (`dry_run`) | rebuilds spam packs (only `package` sources) and rules, carries over business packs, signs, verifies, publishes; publishes nothing when nothing changed |

Both build workflows share the concurrency group `data-release` (never simultaneous) and each publishes a **complete**
manifest: they download the latest release (`fetch-previous`, which first verifies its signature), reuse the unchanged
pack assets by copying them into the new release (their URLs and `bytes`/`sha256` are rewritten to the new tag; they
are copied rather than linked because the older release will be pruned), and re-sign. The secret
`MANIFEST_SIGNING_KEY` (PEM, PKCS#8 Ed25519 private key) is read only from the environment of the assemble step; if it
is missing the build fails loudly, and a key that does not match the public key above is detected right after signing.
No secret is ever written to disk.

### Local use

```
python3 -m venv .venv && .venv/bin/pip install -r pipeline/requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m pipeline audit
```

## Licensing and attribution

- **Code** in this repository: GPL-3.0-or-later (`LICENSE`).
- **Business packs** are derived from OpenStreetMap and published under the **Open Database License 1.0**,
  attribution "© OpenStreetMap contributors" (https://www.openstreetmap.org/copyright). Text in
  `LICENSES/ODbL-1.0.txt`. They are a Derivative Database: share-alike applies, so the packs are public under ODbL and are
  never mixed with data under an incompatible licence in the same pack. If a source's licence is not clearly
  compatible, that source is excluded and the decision is recorded. The app shows the attribution and links the licence.
- **Spam sources**: a source is packaged only when its card says `redistribution: package` and the licence was verified
  against the primary source. Sources that do not permit redistribution are never downloaded or packaged here
  (`direct-download` means the app fetches the original URL itself; `excluded` means not used at all). Currently
  PhoneBlock (no data licence found; token-based API) and dontobi/SpamCalllist (archived 2024, stale) are `excluded`, so
  there are no spam packs yet and releases carry the rules.
- **Rules** cite public legal sources (BOE-A-2026-8409 for Spain) and are under the repository licence.

No warranty. OSM data can contain errors; coverage is partial.

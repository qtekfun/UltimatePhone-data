"""Business packs from OpenStreetMap regional extracts (Geofabrik). Streaming, low memory.

Candidates are streamed into an on-disk SQLite staging table (never a Python dict), then reduced to one
row per number. The Overpass API is never used.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

from . import categories, common
from .common import PipelineError
from .phone import normalise_value

PACK_SCHEMA = 1
USER_AGENT = "UltimatePhone-data/1 (+https://github.com/qtekfun/UltimatePhone-data)"

# Tags that make a name/entry more trustworthy; used for the quality score.
_RICH_TAGS = ("brand", "operator", "website", "contact:website", "opening_hours", "addr:street",
              "addr:housenumber", "addr:city", "wikidata")


def load_config() -> dict:
    cfg = common.load_yaml(common.SOURCES / "businesses" / "osm.yaml")
    common.validate(cfg, "osm-source.schema.json", "sources/businesses/osm.yaml")
    return cfg


def region_config(cfg: dict, region_id: str) -> dict:
    for r in cfg["regions"]:
        if r["id"] == region_id:
            return r
    known = ", ".join(r["id"] for r in cfg["regions"])
    raise PipelineError(f"unknown region {region_id!r}; configured: {known}")


def quality(tags: dict[str, str]) -> int:
    """Higher is better. A real `name` beats a brand/operator fallback; richer tagging wins ties."""
    score = 100 if tags.get("name") else 0
    score += 10 * sum(1 for t in _RICH_TAGS if tags.get(t))
    if tags.get("name:en") or tags.get("name:es") or tags.get("name:de"):
        score += 1
    return score


def display_name(tags: dict[str, str]) -> str | None:
    for k in ("name", "brand", "operator"):
        v = (tags.get(k) or "").strip()
        if v:
            return v
    return None


class Stats:
    def __init__(self) -> None:
        self.elements_business = 0       # named, business-like elements (coverage denominator)
        self.elements_with_phone = 0     # of those, with a phone tag
        self.phones_raw = 0
        self.phones_invalid = 0
        self.eligible_by_cat: Counter[str] = Counter()
        self.with_phone_by_cat: Counter[str] = Counter()
        self.skipped_no_name = 0         # business-like element with phone but no name at all


def _element_id(o) -> str:
    prefix = "n" if o.is_node() else "w" if o.is_way() else "r"
    return f"{prefix}{o.id}"


def iter_elements(path: Path) -> Iterator[tuple[str, dict[str, str]]]:
    """Stream (osm_id, tags) for every tagged node/way/relation of an .osm.pbf or .osm file."""
    import osmium  # imported lazily so that the pure-Python parts work without the wheel

    fp = osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY | osmium.osm.RELATION)
    for o in fp:
        if len(o.tags) == 0:
            continue
        yield _element_id(o), {t.k: t.v for t in o.tags}


def _init_staging(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE cand(e164 TEXT NOT NULL, name TEXT NOT NULL, brand TEXT, category TEXT NOT NULL,
                          osm_id TEXT NOT NULL, q INTEGER NOT NULL);
        """
    )


def stage_candidates(elements: Iterable[tuple[str, dict[str, str]]], country: str, cfg: dict,
                     staging: sqlite3.Connection, stats: Stats) -> None:
    phone_keys = cfg["tags"]["phone_keys"]
    business_keys = cfg["tags"]["business_keys"]
    batch: list[tuple] = []
    for osm_id, tags in elements:
        cat = categories.category_for(tags, business_keys)
        if cat is None:
            continue
        name = display_name(tags)
        phone_values = [tags[k] for k in phone_keys if tags.get(k)]
        if name is None:
            if phone_values:
                stats.skipped_no_name += 1
            continue
        stats.elements_business += 1
        stats.eligible_by_cat[cat] += 1
        if not phone_values:
            continue
        stats.elements_with_phone += 1
        stats.with_phone_by_cat[cat] += 1
        numbers: list[str] = []
        for value in phone_values:
            parts, invalid = normalise_value(value, country)
            stats.phones_raw += len(parts) + invalid
            stats.phones_invalid += invalid
            numbers.extend(n for n in parts if n not in numbers)
        q = quality(tags)
        brand = (tags.get("brand") or "").strip() or None
        for n in numbers:
            batch.append((n, name, brand, cat, osm_id, q))
        if len(batch) >= 20000:
            staging.executemany("INSERT INTO cand VALUES (?,?,?,?,?,?)", batch)
            batch.clear()
    if batch:
        staging.executemany("INSERT INTO cand VALUES (?,?,?,?,?,?)", batch)


def _write_pack(staging: sqlite3.Connection, out_db: Path, max_alt: int, meta: dict[str, str]) -> dict:
    if out_db.exists():
        out_db.unlink()
    db = sqlite3.connect(out_db)
    db.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE numbers(
            e164 TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            brand TEXT,
            category TEXT NOT NULL,
            osm_id TEXT NOT NULL,
            alt_names TEXT
        );
        CREATE TABLE meta(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
        """
    )
    staging.execute("CREATE INDEX cand_idx ON cand(e164, q DESC, osm_id)")
    cur = staging.execute("SELECT e164, name, brand, category, osm_id, q FROM cand ORDER BY e164, q DESC, osm_id")
    rows: list[tuple] = []
    count = 0
    by_cat: Counter[str] = Counter()
    alt_numbers = 0

    def flush() -> None:
        db.executemany("INSERT INTO numbers VALUES (?,?,?,?,?,?)", rows)
        rows.clear()

    cur_num, group = None, []

    def emit(num: str, group: list[tuple]) -> None:
        nonlocal count, alt_numbers
        best = group[0]
        alts: list[str] = []
        for g in group[1:]:
            if g[1] != best[1] and g[1] not in alts and len(alts) < max_alt:
                alts.append(g[1])
        if alts:
            alt_numbers += 1
        rows.append((num, best[1], best[2], best[3], best[4], json.dumps(alts, ensure_ascii=False) if alts else None))
        by_cat[best[3]] += 1
        count += 1
        if len(rows) >= 20000:
            flush()

    for row in cur:
        if row[0] != cur_num:
            if cur_num is not None:
                emit(cur_num, group)
            cur_num, group = row[0], []
        group.append(row)
    if cur_num is not None:
        emit(cur_num, group)
    flush()

    db.executescript(
        """
        CREATE VIRTUAL TABLE numbers_fts USING fts5(
            name, content='numbers', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2');
        INSERT INTO numbers_fts(rowid, name) SELECT rowid, name FROM numbers;
        INSERT INTO numbers_fts(numbers_fts) VALUES('optimize');
        """
    )
    meta = dict(meta)
    meta["entries"] = str(count)
    meta["entriesWithAlternatives"] = str(alt_numbers)
    meta["entriesByCategory"] = json.dumps(dict(sorted(by_cat.items())))
    db.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
    db.commit()
    db.execute("VACUUM")
    db.close()
    return {"entries": count, "by_category": dict(by_cat)}


def build_pack(region: dict, cfg: dict, inputs: list[Path], out_dir: Path, version: str, generated_at: str,
               scratch: Path, source_urls: list[str] | None = None) -> dict:
    """Build businesses-<region>.db.xz from local extract files. Returns the manifest-ready pack entry."""
    pack_id = f"businesses-{region['id'].lower()}"
    scratch.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging_path = scratch / f"{pack_id}.staging.db"
    staging_path.unlink(missing_ok=True)
    staging = sqlite3.connect(staging_path)
    staging.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;")
    _init_staging(staging)
    stats = Stats()
    for path in inputs:
        stage_candidates(iter_elements(path), region["country"], cfg, staging, stats)
    staging.commit()

    coverage = {
        c: {"withPhone": stats.with_phone_by_cat[c], "eligible": stats.eligible_by_cat[c]}
        for c in sorted(stats.eligible_by_cat)
    }
    pct = round(100.0 * stats.elements_with_phone / stats.elements_business, 2) if stats.elements_business else 0.0
    meta = {
        "packId": pack_id,
        "schema": str(PACK_SCHEMA),
        "type": "businesses",
        "version": version,
        "region": region["id"],
        "country": region["country"],
        "generatedAt": generated_at,
        "license": cfg["licence"],
        "licenseUrl": cfg["licence_url"],
        "attribution": cfg["attribution"],
        "sourceUrls": json.dumps(source_urls or []),
        "elementsBusiness": str(stats.elements_business),
        "elementsWithPhone": str(stats.elements_with_phone),
        "coveragePercent": str(pct),
        "coverageByCategory": json.dumps(coverage),
        "phonesRaw": str(stats.phones_raw),
        "phonesInvalidDropped": str(stats.phones_invalid),
        "skippedNoName": str(stats.skipped_no_name),
        "categories": json.dumps(categories.CATEGORIES),
    }
    db_path = scratch / f"{pack_id}.db"
    info = _write_pack(staging, db_path, cfg["max_alternatives"], meta)
    staging.close()
    staging_path.unlink(missing_ok=True)

    asset = out_dir / f"{pack_id}.db.xz"
    comp = common.xz_compress(db_path, asset)
    db_path.unlink()
    return {
        "id": pack_id,
        "type": "businesses",
        "region": region["id"],
        "version": version,
        "file": asset.name,
        "sha256": comp["sha256"],
        "bytes": comp["bytes"],
        "entries": info["entries"],
        "license": cfg["licence"],
        "attribution": cfg["attribution"],
        "dependsOn": [],
        "compression": "xz",
        "uncompressedBytes": comp["uncompressedBytes"],
        "uncompressedSha256": comp["uncompressedSha256"],
    }


# ---- download -----------------------------------------------------------------------------------------

def download(url: str, dest: Path, check_md5: bool = True) -> Path:
    """Download a Geofabrik extract (streamed to disk) and verify it against the published .md5 file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    md5 = hashlib.md5(usedforsecurity=False)
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        # "-latest" aliases redirect to a dated file or a mirror; the .md5 sits next to the file actually served.
        final_url = resp.geturl() or url
        while chunk := resp.read(common.CHUNK):
            md5.update(chunk)
            out.write(chunk)
    if check_md5:
        req = urllib.request.Request(final_url + ".md5", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            expected = resp.read().decode().split()[0].lower()
        if expected != md5.hexdigest():
            dest.unlink(missing_ok=True)
            raise PipelineError(f"MD5 mismatch for {url}: expected {expected}, got {md5.hexdigest()}")
    return dest


def prefilter(src: Path, dst: Path, business_keys: list[str]) -> Path:
    """Shrink a large extract with osmium-tool, keeping every element with a business key.

    The keys are kept regardless of phone so that the coverage denominator stays correct.
    """
    exe = shutil.which("osmium")
    if exe is None:
        raise PipelineError("osmium-tool is required for --prefilter but 'osmium' is not on PATH")
    cmd = [exe, "tags-filter", "--overwrite", "-o", str(dst), str(src)] + [f"nwr/{k}" for k in business_keys]
    subprocess.run(cmd, check=True)
    return dst

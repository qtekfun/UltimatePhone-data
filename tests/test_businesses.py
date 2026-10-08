import json
import lzma
import sqlite3

from pipeline import businesses, common

from .helpers import FIX, GENERATED, VERSION, es_region


def build(tmp_path):
    cfg, region = es_region()
    entry = businesses.build_pack(region, cfg, [FIX / "sample.osm"], tmp_path / "out", VERSION, GENERATED,
                                  tmp_path / "scratch")
    db_path = tmp_path / "pack.db"
    common.xz_decompress(tmp_path / "out" / entry["file"], db_path)
    return entry, sqlite3.connect(db_path)


def test_pack_content_dedupe_and_stats(tmp_path):
    entry, db = build(tmp_path)
    rows = {r[0]: r for r in db.execute("SELECT e164, name, brand, category, osm_id, alt_names FROM numbers")}
    assert set(rows) == {"+34912345678", "+34913456789", "+34915550123", "+34918765432", "+34931234567",
                         "+34612345678", "+34955123456"}
    assert entry["entries"] == 7
    shared = rows["+34913456789"]
    assert shared[1] == "Café Central" and shared[4] == "n1"          # richer element wins
    assert json.loads(shared[5]) == ["Panadería Sol"]                  # the other name is kept as alternative
    assert rows["+34931234567"][1:4] == ("SuperEjemplo", "SuperEjemplo", "grocery")   # brand fallback name
    assert rows["+34915550123"][4] == "w3" and rows["+34955123456"][4] == "r10"
    assert "+34600111222" not in rows                                   # vacant shop / unnamed office dropped


def test_meta_and_coverage(tmp_path):
    entry, db = build(tmp_path)
    meta = dict(db.execute("SELECT key, value FROM meta"))
    assert meta["packId"] == "businesses-es" and meta["version"] == VERSION and meta["region"] == "ES"
    assert meta["license"] == "ODbL-1.0" and meta["attribution"] == "© OpenStreetMap contributors"
    assert meta["entries"] == "7"
    assert meta["elementsBusiness"] == "8" and meta["elementsWithPhone"] == "7"
    assert meta["coveragePercent"] == "87.5"
    assert meta["phonesInvalidDropped"] == "1" and meta["skippedNoName"] == "1"
    assert json.loads(meta["coverageByCategory"])["shopping"] == {"withPhone": 1, "eligible": 2}
    assert json.loads(meta["categories"])["food"] == "restaurant"


def test_fts_query_and_diacritics(tmp_path):
    _, db = build(tmp_path)
    hit = db.execute("SELECT n.e164 FROM numbers_fts f JOIN numbers n ON n.rowid = f.rowid "
                     "WHERE numbers_fts MATCH 'cafe'").fetchall()
    assert ("+34912345678",) in hit                                   # 'Café' matches 'cafe'
    assert db.execute("SELECT count(*) FROM numbers_fts WHERE numbers_fts MATCH 'farmacia'").fetchone()[0] == 2   # one row per number


def test_schema_and_xz_parameters(tmp_path):
    entry, db = build(tmp_path)
    cols = [r[1] for r in db.execute("PRAGMA table_info(numbers)")]
    assert cols == ["e164", "name", "brand", "category", "osm_id", "alt_names"]
    assert db.execute("SELECT pk FROM pragma_table_info('numbers') WHERE name='e164'").fetchone()[0] == 1
    raw = (tmp_path / "out" / entry["file"]).read_bytes()
    assert raw[:6] == b"\xfd7zXZ\x00"
    assert raw[6:8] == b"\x00\x04"                                    # stream flags: check type 4 = CRC64
    assert entry["compression"] == "xz" and entry["file"] == "businesses-es.db.xz"
    assert entry["sha256"] == common.sha256_file(tmp_path / "out" / entry["file"])
    with lzma.open(tmp_path / "out" / entry["file"]) as f:
        assert f.read(16) == b"SQLite format 3\x00"


def test_prefilter_command(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(businesses.shutil, "which", lambda n: "/usr/bin/osmium")
    monkeypatch.setattr(businesses.subprocess, "run", lambda cmd, check: calls.append((cmd, check)))
    businesses.prefilter(tmp_path / "a.osm.pbf", tmp_path / "b.osm.pbf", ["shop", "amenity"])
    cmd, check = calls[0]
    assert check is True and cmd[1] == "tags-filter" and cmd[-2:] == ["nwr/shop", "nwr/amenity"]

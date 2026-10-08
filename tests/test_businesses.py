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


def test_index_is_fts4_and_answers_the_apps_prefix_queries(tmp_path):
    """Android's platform SQLite has no fts5 module; the app queries `abc* OR abd*` style prefix expressions."""
    _, db = build(tmp_path)
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'numbers_fts'").fetchone()[0].lower()
    assert "fts4" in sql and "fts5" not in sql
    rows = db.execute("SELECT n.e164 FROM numbers_fts JOIN numbers n ON n.rowid = numbers_fts.rowid "
                      "WHERE numbers_fts MATCH ?", ("far* OR cad*",)).fetchall()
    assert rows, "a prefix expression like the app's must find the fixture pharmacies"


def test_pack_versions_carry_the_format_revision():
    from pipeline import common
    assert common.date_version().endswith(f".{common.FORMAT_REVISION}")


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


def test_download_checks_md5_next_to_the_redirected_file(tmp_path, monkeypatch):
    """The .md5 of a "-latest" alias is read from the final URL, not from the alias."""
    import hashlib
    import io

    payload = b"pbf-bytes"
    requested = []

    class FakeResponse(io.BytesIO):
        def __init__(self, body, url):
            super().__init__(body)
            self._url = url

        def geturl(self):
            return self._url

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=0):
        requested.append(req.full_url)
        if req.full_url.endswith(".md5"):
            return FakeResponse((hashlib.md5(payload).hexdigest() + "  x\n").encode(), req.full_url)
        return FakeResponse(payload, "https://mirror.example/dated-file.osm.pbf")

    monkeypatch.setattr(businesses.urllib.request, "urlopen", fake_urlopen)
    businesses.download("https://example/latest.osm.pbf", tmp_path / "x.pbf")
    assert requested == ["https://example/latest.osm.pbf", "https://mirror.example/dated-file.osm.pbf.md5"]
    assert (tmp_path / "x.pbf").read_bytes() == payload

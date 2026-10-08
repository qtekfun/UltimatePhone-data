import sqlite3

import pytest

from pipeline import common, spam
from pipeline.common import PipelineError

from .helpers import FIX, GENERATED, VERSION, spam_card


def build(tmp_path, fmt, **extra):
    card = spam_card(fmt, **extra)
    entry = spam.build_pack(card, FIX / f"spam.{fmt}", tmp_path / "out", VERSION, GENERATED, tmp_path / "s")
    db_path = tmp_path / "x.db"
    common.xz_decompress(tmp_path / "out" / entry["file"], db_path)
    return entry, sqlite3.connect(db_path)


def test_txt(tmp_path):
    entry, db = build(tmp_path, "txt")
    nums = dict(db.execute("SELECT e164, label FROM numbers"))
    assert nums == {"+34600111222": "Fake survey calls", "+34931234567": None, "+493012345678": "Test entry"}
    assert db.execute("SELECT prefix, source_id FROM prefix_rules").fetchall() == [("+49900", "sample-txt")]
    assert entry["entries"] == 4 and entry["sourceId"] == "sample-txt" and entry["id"] == "spam-sample-txt"
    meta = dict(db.execute("SELECT key, value FROM meta"))
    assert meta["invalidDropped"] == "1" and meta["sourceId"] == "sample-txt"
    assert {r[0] for r in db.execute("SELECT source_id FROM numbers")} == {"sample-txt"}


def test_csv_with_named_columns(tmp_path):
    _, db = build(tmp_path, "csv", options={"number_column": "number", "label_column": "reason",
                                             "category_column": "type"})
    assert dict(db.execute("SELECT e164, category FROM numbers")) == {"+34600111222": "survey", "+34931234567": None}


def test_jsonl_dedupes_across_formats_of_same_number(tmp_path):
    entry, db = build(tmp_path, "jsonl")
    assert {r[0] for r in db.execute("SELECT e164 FROM numbers")} == {"+34600111222", "+34931234567"}
    assert dict(db.execute("SELECT key, value FROM meta"))["invalidDropped"] == "1"


def test_only_package_sources_are_downloaded(tmp_path):
    with pytest.raises(PipelineError):
        spam.download(spam_card("txt", redistribution="excluded", reason="x"), tmp_path / "x")


def test_real_cards_have_no_packageable_source_yet():
    cards = spam.load_cards()
    assert {c["id"] for c in cards} >= {"phoneblock", "dontobi-spamcalllist"}
    assert spam.packageable(cards) == []
    by_id = {c["id"]: c for c in cards}
    assert by_id["phoneblock"]["redistribution"] == "excluded"
    assert by_id["dontobi-spamcalllist"]["redistribution"] == "excluded"

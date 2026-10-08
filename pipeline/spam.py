"""Spam packs (txt: one entry per line, see parse_txt): one per source card whose redistribution policy is `package`.

Sources with `direct-download` or `excluded` are never downloaded or packaged by this repo.
With no packageable source the build succeeds and produces nothing (rules are published on their own).
"""
from __future__ import annotations

import csv
import json
import sqlite3
import urllib.request
from pathlib import Path
from typing import Iterator

import phonenumbers

from . import common
from .common import PipelineError
from .phone import to_e164

PACK_SCHEMA = 1
USER_AGENT = "UltimatePhone-data/1 (+https://github.com/qtekfun/UltimatePhone-data)"


def load_cards(directory: Path | None = None) -> list[dict]:
    directory = directory or common.SOURCES / "spam"
    cards = []
    for path in sorted(directory.glob("*.yaml")):
        card = common.load_yaml(path)
        common.validate(card, "spam-source.schema.json", str(path))
        if path.stem != card["id"] and not path.stem.endswith(card["id"]):
            raise PipelineError(f"{path}: file name should match the source id {card['id']!r}")
        card["_path"] = str(path)
        cards.append(card)
    ids = [c["id"] for c in cards]
    if len(ids) != len(set(ids)):
        raise PipelineError("duplicate spam source ids")
    return cards


def packageable(cards: list[dict]) -> list[dict]:
    return [c for c in cards if c["redistribution"] == "package"]


# ---- parsing ------------------------------------------------------------------------------------------
# Each parser yields (raw_number, label, category) tuples.

def _col(row: list[str], key, header: list[str] | None) -> str | None:
    if key is None:
        return None
    idx = header.index(key) if isinstance(key, str) and header else key
    if not isinstance(idx, int) or idx >= len(row):
        return None
    return row[idx].strip() or None


def parse_txt(path: Path, options: dict) -> Iterator[tuple[str, str | None, str | None]]:
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # "<number>", "<number>\t<label>" or "<number> # <label>"; a trailing * marks a prefix.
            if "\t" in line:
                num, label = line.split("\t", 1)
            elif " #" in line:
                num, label = line.split(" #", 1)
            else:
                num, label = line, None
            yield num.strip(), (label.strip() or None) if label else None, None


def parse_csv(path: Path, options: dict) -> Iterator[tuple[str, str | None, str | None]]:
    header = None
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=options.get("delimiter", ","))
        for i, row in enumerate(reader):
            if not row or row[0].startswith("#"):
                continue
            if i == 0 and options.get("has_header", True):
                header = [c.strip() for c in row]
                continue
            raw = _col(row, options.get("number_column", 0), header)
            if raw:
                yield raw, _col(row, options.get("label_column"), header), _col(row, options.get("category_column"), header)


def parse_jsonl(path: Path, options: dict) -> Iterator[tuple[str, str | None, str | None]]:
    nf = options.get("number_field", "number")
    with open(path, encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise PipelineError(f"{path}:{n}: invalid JSON: {e}") from e
            raw = obj.get(nf)
            if raw:
                yield str(raw), obj.get(options.get("label_field", "label")), obj.get(options.get("category_field", "category"))


PARSERS = {"txt": parse_txt, "csv": parse_csv, "jsonl": parse_jsonl}


def _prefix_to_e164(raw: str, country: str | None) -> str | None:
    """'+49900*' or (with a card country) '900*' -> '+49900'. None if unusable."""
    body = raw.rstrip("*").replace(" ", "")
    if body.startswith("+"):
        digits = body[1:]
        plus = True
    else:
        digits = body
        plus = False
    if not digits.isdigit():
        return None
    if plus:
        return "+" + digits
    if not country:
        return None
    cc = phonenumbers.country_code_for_region(country)
    return f"+{cc}{digits}" if cc else None


def build_pack(card: dict, input_path: Path, out_dir: Path, version: str, generated_at: str,
               scratch: Path) -> dict:
    parser = PARSERS.get(card["format"])
    if parser is None:
        raise PipelineError(f"{card['id']}: format {card['format']!r} cannot be parsed")
    country = card.get("country")
    pack_id = f"spam-{card['id']}"
    scratch.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = scratch / f"{pack_id}.db"
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.executescript(
        """
        PRAGMA journal_mode = OFF;
        CREATE TABLE numbers(e164 TEXT PRIMARY KEY NOT NULL, label TEXT, category TEXT, source_id TEXT NOT NULL);
        CREATE TABLE prefix_rules(prefix TEXT PRIMARY KEY NOT NULL, label TEXT, source_id TEXT NOT NULL);
        CREATE TABLE meta(key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
        """
    )
    total = invalid = dup = 0
    for raw, label, cat in parser(input_path, card.get("options", {})):
        total += 1
        if raw.endswith("*"):
            prefix = _prefix_to_e164(raw, country)
            if prefix is None:
                invalid += 1
                continue
            cur = db.execute("INSERT OR IGNORE INTO prefix_rules VALUES (?,?,?)", (prefix, label, card["id"]))
        else:
            e164 = to_e164(raw, country or "ZZ")
            if e164 is None:
                invalid += 1
                continue
            cur = db.execute("INSERT OR IGNORE INTO numbers VALUES (?,?,?,?)", (e164, label, cat, card["id"]))
        if cur.rowcount == 0:
            dup += 1
    n_numbers = db.execute("SELECT count(*) FROM numbers").fetchone()[0]
    n_prefix = db.execute("SELECT count(*) FROM prefix_rules").fetchone()[0]
    meta = {
        "packId": pack_id, "schema": str(PACK_SCHEMA), "type": "spam", "sourceId": card["id"],
        "sourceName": card["name"], "sourceUrl": card["url"], "version": version,
        "region": card["region"], "generatedAt": generated_at, "license": card["licence"],
        "licenseUrl": card.get("licence_url", ""), "attribution": card["attribution"],
        "level": card["level"], "entries": str(n_numbers + n_prefix), "numbers": str(n_numbers),
        "prefixRules": str(n_prefix), "linesTotal": str(total), "invalidDropped": str(invalid),
        "duplicatesDropped": str(dup),
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
    db.commit()
    db.execute("VACUUM")
    db.close()
    asset = out_dir / f"{pack_id}.db.xz"
    comp = common.xz_compress(db_path, asset)
    db_path.unlink()
    return {
        "id": pack_id, "type": "spam", "region": card["region"], "version": version, "file": asset.name,
        "sha256": comp["sha256"], "bytes": comp["bytes"], "entries": n_numbers + n_prefix,
        "license": card["licence"], "attribution": card["attribution"], "dependsOn": [],
        "compression": "xz", "uncompressedBytes": comp["uncompressedBytes"],
        "uncompressedSha256": comp["uncompressedSha256"], "sourceId": card["id"],
    }


def download(card: dict, dest: Path) -> Path:
    if card["redistribution"] != "package":
        raise PipelineError(f"{card['id']}: refusing to download a source with policy {card['redistribution']!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(card["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        while chunk := resp.read(common.CHUNK):
            out.write(chunk)
    return dest

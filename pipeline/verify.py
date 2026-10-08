"""Verify a release directory the way a client would, plus a smoke test of every pack.

Checks: manifest signature (Ed25519, embedded public key), manifest schema, SHA256SUMS, every pack asset
(sha256, bytes, XZ decompression, uncompressed sha256), every pack opens and answers a query.
Run: python -m pipeline.verify --dir dist/release [--public-key keys/manifest-public-key.txt]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import common
from .common import PipelineError
from .manifest import MANIFEST, SIGNATURE, SUMS, load_public_key, verify_signature


def _check_sums(directory: Path) -> int:
    n = 0
    listed = set()
    for line in (directory / SUMS).read_text(encoding="ascii").splitlines():
        digest, _, name = line.partition("  ")
        if not name or "/" in name:
            raise PipelineError(f"malformed SHA256SUMS line: {line!r}")
        if not (directory / name).is_file():
            raise PipelineError(f"SHA256SUMS lists {name} but it is missing")
        if common.sha256_file(directory / name) != digest:
            raise PipelineError(f"SHA256SUMS mismatch for {name}")
        listed.add(name)
        n += 1
    actual = {p.name for p in directory.iterdir() if p.is_file() and p.name != SUMS}
    if actual != listed:
        raise PipelineError(f"SHA256SUMS does not list exactly the assets: diff {sorted(actual ^ listed)}")
    return n


def _smoke_db(pack: dict, db_path: Path, known: dict[str, str]) -> str:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        meta = dict(db.execute("SELECT key, value FROM meta"))
        if meta.get("packId") != pack["id"] or meta.get("version") != pack["version"]:
            raise PipelineError(f"{pack['id']}: meta table does not match the manifest")
        if pack["type"] == "businesses":
            n = db.execute("SELECT count(*) FROM numbers").fetchone()[0]
            if n != pack["entries"]:
                raise PipelineError(f"{pack['id']}: {n} rows but manifest says {pack['entries']}")
            if n == 0:
                raise PipelineError(f"{pack['id']}: empty pack")
            e164 = known.get(pack["id"]) or db.execute("SELECT e164 FROM numbers ORDER BY e164 LIMIT 1").fetchone()[0]
            row = db.execute("SELECT name FROM numbers WHERE e164 = ?", (e164,)).fetchone()
            if row is None:
                raise PipelineError(f"{pack['id']}: known number {e164} not found")
            token = "".join(c for c in row[0].split()[0] if c.isalnum())
            if token:
                hit = db.execute(
                    "SELECT count(*) FROM numbers_fts WHERE numbers_fts MATCH ?", (f'"{token}"',)).fetchone()[0]
                if hit < 1:
                    raise PipelineError(f"{pack['id']}: FTS query for {token!r} found nothing")
            return f"{n} numbers, e164 {e164} -> {row[0]!r}"
        if pack["type"] == "spam":
            n = db.execute("SELECT count(*) FROM numbers").fetchone()[0]
            p = db.execute("SELECT count(*) FROM prefix_rules").fetchone()[0]
            if n + p != pack["entries"]:
                raise PipelineError(f"{pack['id']}: {n + p} rows but manifest says {pack['entries']}")
            first = db.execute("SELECT e164, source_id FROM numbers ORDER BY e164 LIMIT 1").fetchone()
            if first and first[1] != pack.get("sourceId"):
                raise PipelineError(f"{pack['id']}: sourceId mismatch")
            return f"{n} numbers, {p} prefix rules"
        raise PipelineError(f"{pack['id']}: unexpected db pack type {pack['type']}")
    finally:
        db.close()


def verify_release(directory: Path, scratch: Path, public_key_file: Path | None = None,
                   known: dict[str, str] | None = None) -> list[str]:
    """Returns human-readable report lines; raises PipelineError on the first failure."""
    known = known or {}
    report: list[str] = []
    data = (directory / MANIFEST).read_bytes()
    verify_signature(load_public_key(public_key_file), data, (directory / SIGNATURE).read_bytes())
    report.append("manifest signature OK")
    manifest = json.loads(data)
    common.validate(manifest, "manifest.schema.json", "manifest.json")
    report.append(f"manifest schema OK ({len(manifest['packs'])} packs)")
    report.append(f"SHA256SUMS OK ({_check_sums(directory)} files)")
    scratch.mkdir(parents=True, exist_ok=True)
    for pack in manifest["packs"]:
        name = pack["url"].rsplit("/", 1)[1]
        asset = directory / name
        if not asset.exists():
            raise PipelineError(f"{pack['id']}: asset {name} is missing from the release")
        if asset.stat().st_size != pack["bytes"] or common.sha256_file(asset) != pack["sha256"]:
            raise PipelineError(f"{pack['id']}: bytes/sha256 do not match the manifest")
        if pack["compression"] == "xz":
            db_path = scratch / f"{pack['id']}.db"
            info = common.xz_decompress(asset, db_path)
            if (info["uncompressedBytes"], info["uncompressedSha256"]) != (
                    pack["uncompressedBytes"], pack["uncompressedSha256"]):
                raise PipelineError(f"{pack['id']}: decompressed size/sha256 do not match the manifest")
            detail = _smoke_db(pack, db_path, known)
            db_path.unlink()
        else:
            doc = json.loads(asset.read_text(encoding="utf-8"))
            common.validate(doc, "rules.schema.json", name)
            if len(doc["rules"]) != pack["entries"] or doc["version"] != pack["version"]:
                raise PipelineError(f"{pack['id']}: rules content does not match the manifest")
            detail = f"{len(doc['rules'])} rules"
        report.append(f"{pack['id']}: OK ({detail})")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", type=Path, default=common.ROOT / "dist" / "release")
    ap.add_argument("--scratch", type=Path, default=common.ROOT / "work" / "verify")
    ap.add_argument("--public-key", type=Path, default=None)
    ap.add_argument("--known", type=Path, default=None, help="JSON {packId: e164} of numbers that must exist")
    a = ap.parse_args(argv)
    known = json.loads(a.known.read_text()) if a.known else None
    try:
        for line in verify_release(a.dir, a.scratch, a.public_key, known):
            print(line)
    except (PipelineError, OSError, KeyError, sqlite3.Error) as e:
        print(f"VERIFY FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

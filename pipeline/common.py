"""Shared helpers: paths, YAML/JSON loading, hashing, XZ streaming, schema validation."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import lzma
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = Path(__file__).resolve().parent / "schemas"
SOURCES = ROOT / "sources"
PUBLIC_KEY_FILE = ROOT / "keys" / "manifest-public-key.txt"
REPO = "qtekfun/UltimatePhone-data"
CHUNK = 1024 * 1024

# Pinned so that the Android reader (pure-Java org.tukaani:xz) never needs more than an 8 MiB dictionary.
XZ_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6, "dict_size": 8 * 1024 * 1024}]


class PipelineError(Exception):
    """A condition that must fail the build loudly."""


def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def validate(instance: Any, schema_name: str, what: str) -> None:
    validator = jsonschema.Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"  {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors]
        raise PipelineError(f"{what} does not match {schema_name}:\n" + "\n".join(lines))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(ts: dt.datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


# Bumped whenever the on-disk format of the packs changes, so clients that hold a pack of the same date replace it.
# 1 = FTS5 index (unusable on Android), 2 = FTS4 index.
FORMAT_REVISION = 2


def date_version(ts: dt.datetime | None = None) -> str:
    return (ts or utc_now()).strftime("%Y.%m.%d") + f".{FORMAT_REVISION}"


def xz_compress(src: Path, dst: Path) -> dict:
    """Stream src into dst as XZ (CRC64, LZMA2, 8 MiB dictionary). Returns sizes and hashes of both files."""
    raw = hashlib.sha256()
    n_raw = 0
    comp = lzma.LZMAFile(dst, "wb", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, filters=XZ_FILTERS)
    try:
        with open(src, "rb") as f:
            while chunk := f.read(CHUNK):
                raw.update(chunk)
                n_raw += len(chunk)
                comp.write(chunk)
    finally:
        comp.close()
    return {
        "uncompressedBytes": n_raw,
        "uncompressedSha256": raw.hexdigest(),
        "bytes": dst.stat().st_size,
        "sha256": sha256_file(dst),
    }


def xz_decompress(src: Path, dst: Path) -> dict:
    """Stream-decompress src into dst; returns the size and sha256 of the decompressed data."""
    h = hashlib.sha256()
    n = 0
    with lzma.LZMAFile(src, "rb", format=lzma.FORMAT_XZ) as comp, open(dst, "wb") as out:
        while chunk := comp.read(CHUNK):
            h.update(chunk)
            n += len(chunk)
            out.write(chunk)
    return {"uncompressedBytes": n, "uncompressedSha256": h.hexdigest()}


def write_json(path: Path, doc: Any) -> None:
    """Deterministic JSON (2-space indent, UTF-8, trailing newline)."""
    path.write_bytes(json_bytes(doc))


def json_bytes(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

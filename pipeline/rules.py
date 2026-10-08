"""Prefix rules: sources/rules/*.yaml -> rules-<country>.json (small, uncompressed, versioned)."""
from __future__ import annotations

from pathlib import Path

from . import common
from .common import PipelineError


def load_sources(directory: Path | None = None) -> list[dict]:
    directory = directory or common.SOURCES / "rules"
    out = []
    for path in sorted(directory.glob("*.yaml")):
        doc = common.load_yaml(path)
        common.validate(doc, "rules-source.schema.json", str(path))
        if path.stem.upper() != doc["country"]:
            raise PipelineError(f"{path}: file name must be the lower-case country code ({doc['country'].lower()}.yaml)")
        out.append(doc)
    return out


def to_document(source: dict, version: str) -> dict:
    rules = []
    for r in source["rules"]:
        rule = {
            "id": r["id"], "country": source["country"], "prefix": r["prefix"], "level": r["level"],
            "kind": r["kind"], "source": r["source"], "note": " ".join(r["note"].split()),
        }
        if r.get("source_url"):
            rule["sourceUrl"] = r["source_url"]
        rules.append(rule)
    doc = {"schema": 1, "version": version, "rules": rules}
    common.validate(doc, "rules.schema.json", f"rules-{source['country'].lower()}.json")
    return doc


def build(out_dir: Path, version: str, directory: Path | None = None) -> list[dict]:
    """Write rules-<country>.json files; returns manifest-ready pack entries."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ids: set[str] = set()
    packs = []
    for source in load_sources(directory):
        doc = to_document(source, version)
        for r in doc["rules"]:
            if r["id"] in ids:
                raise PipelineError(f"duplicate rule id {r['id']}")
            ids.add(r["id"])
        name = f"rules-{source['country'].lower()}.json"
        path = out_dir / name
        common.write_json(path, doc)
        packs.append({
            "id": f"rules-{source['country'].lower()}", "type": "rules", "region": source["country"],
            "version": version, "file": name, "sha256": common.sha256_file(path), "bytes": path.stat().st_size,
            "entries": len(doc["rules"]), "license": "GPL-3.0-or-later",
            "attribution": "", "dependsOn": [], "compression": "none",
        })
    return packs

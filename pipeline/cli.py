"""Command line entry point: python -m pipeline <command>."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import audit as audit_mod
from . import businesses, common, manifest, rules, spam
from .common import ROOT, PipelineError

WORK = ROOT / "work"
DIST = ROOT / "dist"


def _write_entries(stage: Path, kind: str, entries: list[dict]) -> None:
    stage.mkdir(parents=True, exist_ok=True)
    common.write_json(stage / f"entries-{kind}.json", entries)


def cmd_audit(a) -> int:
    for line in audit_mod.audit():
        print(line)
    print("licence audit OK")
    return 0


def cmd_businesses(a) -> int:
    cfg = businesses.load_config()
    ids = [r["id"] for r in cfg["regions"]] if a.region == ["all"] else a.region
    now = common.utc_now()
    version, generated = a.version or common.date_version(now), common.iso(now)
    entries = []
    for rid in ids:
        region = businesses.region_config(cfg, rid)
        if a.input:
            inputs, urls, downloaded = [Path(p) for p in a.input], [], []
        else:
            urls = region["extracts"]
            inputs, downloaded = [], []
            for i, url in enumerate(urls):
                dest = WORK / "downloads" / f"{rid.lower()}-{i}.osm.pbf"
                print(f"downloading {url}", flush=True)
                businesses.download(url, dest)
                downloaded.append(dest)
                if a.prefilter:
                    small = dest.with_name(dest.stem + ".filtered.osm.pbf")
                    businesses.prefilter(dest, small, cfg["tags"]["business_keys"])
                    dest.unlink()
                    dest = small
                    downloaded[-1] = small
                inputs.append(dest)
        print(f"building businesses-{rid.lower()} from {len(inputs)} file(s)", flush=True)
        entry = businesses.build_pack(region, cfg, inputs, a.stage, version, generated, WORK / "scratch", urls)
        for p in downloaded:
            p.unlink(missing_ok=True)
        print(f"  {entry['entries']} numbers, {entry['bytes']} bytes", flush=True)
        entries.append(entry)
    _write_entries(a.stage, "businesses", entries)
    return 0


def cmd_spam(a) -> int:
    cards = spam.load_cards()
    todo = spam.packageable(cards)
    skipped = [c["id"] for c in cards if c["redistribution"] != "package"]
    print(f"spam sources: {len(todo)} packageable; not packaged: {', '.join(skipped) or 'none'}")
    now = common.utc_now()
    version, generated = a.version or common.date_version(now), common.iso(now)
    entries = []
    for card in todo:
        src = spam.download(card, WORK / "downloads" / f"spam-{card['id']}.src")
        entries.append(spam.build_pack(card, src, a.stage, version, generated, WORK / "scratch"))
        src.unlink()
    if not todo:
        print("no packageable spam source: publishing rules only")
    _write_entries(a.stage, "spam", entries)
    return 0


def cmd_rules(a) -> int:
    version = a.version or common.date_version()
    entries = rules.build(a.stage, version)
    _write_entries(a.stage, "rules", entries)
    print(f"rules: {', '.join(e['id'] for e in entries)}")
    return 0


def cmd_fetch_previous(a) -> int:
    found = manifest.fetch_previous(a.out, set(a.skip_type or []), set(a.skip_id or []), a.repo)
    print("previous release found" if found else "no previous release (first run)")
    return 0


def _set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def cmd_assemble(a) -> int:
    entries = []
    for f in sorted(a.stage.glob("entries-*.json")):
        entries.extend(json.loads(f.read_text(encoding="utf-8")))
    prev = a.previous if a.previous and a.previous.exists() else None
    if a.skip_if_rules_unchanged:
        built_dbs = [e for e in entries if e["type"] in ("spam", "businesses")]
        rule_entries = [e for e in entries if e["type"] == "rules"]
        if not built_dbs and prev and manifest.rules_unchanged(prev, rule_entries, a.stage):
            print("nothing changed since the latest release: not publishing")
            _set_output("changed", "false")
            return 0
    now = common.utc_now()
    tag = a.tag or f"data-{common.date_version(now)}"
    doc = manifest.assemble(a.stage, prev, entries, a.out, tag, common.iso(now),
                            set(a.replace_type or []), set(a.replace_id or []), a.repo)
    _set_output("changed", "true")
    _set_output("tag", tag)
    print(f"release {tag}: {len(doc['packs'])} packs in {a.out}")
    return 0


def cmd_verify(a) -> int:
    from . import verify
    argv = ["--dir", str(a.dir)]
    if a.public_key:
        argv += ["--public-key", str(a.public_key)]
    return verify.main(argv)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("audit", help="validate sources and run the licence audit")
    p.set_defaults(fn=cmd_audit)

    for name, fn in (("businesses", cmd_businesses), ("spam", cmd_spam), ("rules", cmd_rules)):
        p = sub.add_parser(name)
        p.add_argument("--stage", type=Path, default=DIST / "stage")
        p.add_argument("--version", help="pack version YYYY.MM.DD (default: today, UTC)")
        if name == "businesses":
            p.add_argument("--region", action="append", required=True, help="region id, repeatable, or 'all'")
            p.add_argument("--input", action="append", help="use local extract file(s) instead of downloading")
            p.add_argument("--prefilter", action="store_true", help="shrink downloads with osmium-tool first")
        p.set_defaults(fn=fn)

    p = sub.add_parser("fetch-previous", help="download the latest release (signature verified) for reuse")
    p.add_argument("--out", type=Path, default=WORK / "previous")
    p.add_argument("--skip-type", action="append")
    p.add_argument("--skip-id", action="append")
    p.add_argument("--repo", default=common.REPO)
    p.set_defaults(fn=cmd_fetch_previous)

    p = sub.add_parser("assemble", help="merge this run's packs with the carried-over ones, sign, SHA256SUMS")
    p.add_argument("--stage", type=Path, default=DIST / "stage")
    p.add_argument("--previous", type=Path, default=WORK / "previous")
    p.add_argument("--out", type=Path, default=DIST / "release")
    p.add_argument("--tag")
    p.add_argument("--replace-type", action="append", help="drop previous packs of this type")
    p.add_argument("--replace-id", action="append")
    p.add_argument("--skip-if-rules-unchanged", action="store_true")
    p.add_argument("--repo", default=common.REPO)
    p.set_defaults(fn=cmd_assemble)

    p = sub.add_parser("verify")
    p.add_argument("--dir", type=Path, default=DIST / "release")
    p.add_argument("--public-key", type=Path)
    p.set_defaults(fn=cmd_verify)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except PipelineError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

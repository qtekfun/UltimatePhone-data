"""Source validation and licence audit. Fails when a source lacks a licence or a redistribution policy."""
from __future__ import annotations

from pathlib import Path

from . import common, rules, spam
from .common import PipelineError

LICENSES_DIR = common.ROOT / "LICENSES"


def audit(root: Path | None = None) -> list[str]:
    """Return a report; raise PipelineError listing every problem."""
    problems: list[str] = []
    report: list[str] = []
    lic_dir = (root / "LICENSES") if root else LICENSES_DIR
    src_dir = (root / "sources") if root else common.SOURCES

    def need_note(source_id: str) -> None:
        if not (lic_dir / "sources" / f"{source_id}.md").exists():
            problems.append(f"{source_id}: missing licence note LICENSES/sources/{source_id}.md")

    osm_path = src_dir / "businesses" / "osm.yaml"
    try:
        cfg = common.load_yaml(osm_path)
        common.validate(cfg, "osm-source.schema.json", str(osm_path))
        need_note(cfg["source_id"])
        report.append(f"osm: {cfg['licence']} / {cfg['redistribution']}")
    except PipelineError as e:
        problems.append(str(e))
    if not (lic_dir / "ODbL-1.0.txt").exists():
        problems.append("LICENSES/ODbL-1.0.txt is missing")

    other = common.load_yaml(src_dir / "businesses" / "other-open.yaml")
    try:
        common.validate(other, "other-open.schema.json", "other-open.yaml")
        for s in other["sources"]:
            need_note(s["id"])
            report.append(f"{s['id']}: {s['licence']} / {s['redistribution']}")
    except PipelineError as e:
        problems.append(str(e))

    try:
        cards = spam.load_cards(src_dir / "spam")
    except PipelineError as e:
        problems.append(str(e))
        cards = []
    for c in cards:
        need_note(c["id"])
        if c["redistribution"] == "package" and c["licence"].lower() in {"unknown", "none", ""}:
            problems.append(f"{c['id']}: policy 'package' needs a known licence")
        report.append(f"{c['id']}: {c['licence']} / {c['redistribution']}")
    try:
        rules.load_sources(src_dir / "rules")
        report.append("rules: OK")
    except PipelineError as e:
        problems.append(str(e))
    if problems:
        raise PipelineError("licence audit FAILED:\n  " + "\n  ".join(problems))
    return report

import json

import pytest

from pipeline import common, rules
from pipeline.common import PipelineError

from .helpers import VERSION


def test_es_rule_document(tmp_path):
    packs = rules.build(tmp_path, VERSION)
    doc = json.loads((tmp_path / "rules-es.json").read_text())
    assert doc["schema"] == 1 and doc["version"] == VERSION
    r = doc["rules"][0]
    assert (r["id"], r["country"], r["prefix"], r["level"], r["kind"], r["source"]) == (
        "es-400-commercial", "ES", "400", "RULE", "commercial", "BOE-A-2026-8409")
    assert "not spam" in r["note"]
    assert packs[0]["id"] == "rules-es" and packs[0]["entries"] == 1 and packs[0]["compression"] == "none"


def test_schema_rejects_bad_rule():
    bad = {"schema": 1, "version": VERSION, "rules": [{"id": "x", "country": "ES", "prefix": "4x", "level": "RULE",
                                                        "kind": "commercial", "source": "s", "note": "n"}]}
    with pytest.raises(PipelineError):
        common.validate(bad, "rules.schema.json", "bad")


def test_invalid_source_yaml_fails(tmp_path):
    (tmp_path / "xx.yaml").write_text("country: XX\nrules: []\n")
    with pytest.raises(PipelineError):
        rules.load_sources(tmp_path)

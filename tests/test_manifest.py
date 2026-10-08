import base64
import json

import pytest

from pipeline import common, manifest
from pipeline.common import PipelineError

from .helpers import ephemeral_key, make_release


def test_published_public_key_is_a_32_byte_ed25519_key():
    raw = base64.b64decode(common.PUBLIC_KEY_FILE.read_text().strip(), validate=True)
    assert len(raw) == 32 and manifest.load_public_key()


def test_manifest_schema_fields(tmp_path, monkeypatch):
    _, pem, pub = ephemeral_key()
    out = make_release(tmp_path, pub, monkeypatch, pem)
    doc = json.loads((out / "manifest.json").read_text())
    common.validate(doc, "manifest.schema.json", "m")
    assert doc["schema"] == 1 and doc["generatedAt"] == "2026-11-01T03:00:00Z"
    by_id = {p["id"]: p for p in doc["packs"]}
    assert set(by_id) == {"businesses-es", "spam-sample-txt", "rules-es"}
    b = by_id["businesses-es"]
    assert b["url"] == "https://github.com/qtekfun/UltimatePhone-data/releases/download/data-2026.11.01/businesses-es.db.xz"
    assert b["compression"] == "xz" and b["license"] == "ODbL-1.0" and b["dependsOn"] == []
    assert b["bytes"] == (out / "businesses-es.db.xz").stat().st_size
    assert by_id["rules-es"]["compression"] == "none" and "uncompressedBytes" not in by_id["rules-es"]


def test_schema_rejects_missing_uncompressed_for_xz():
    pack = {"id": "a", "type": "spam", "region": "ES", "version": "2026.11.01", "url": "https://x/y", "sha256": "0" * 64,
            "bytes": 1, "entries": 0, "license": "x", "attribution": "", "dependsOn": [], "compression": "xz"}
    with pytest.raises(PipelineError):
        common.validate({"schema": 1, "generatedAt": "2026-11-01T03:00:00Z", "packs": [pack]}, "manifest.schema.json", "m")


def test_signature_is_detached_base64_of_64_bytes_over_exact_bytes(tmp_path, monkeypatch):
    key, pem, pub = ephemeral_key()
    out = make_release(tmp_path, pub, monkeypatch, pem)
    data = (out / "manifest.json").read_bytes()
    sig_text = (out / "manifest.json.sig").read_text()
    assert sig_text.endswith("\n") and len(base64.b64decode(sig_text.strip(), validate=True)) == 64
    manifest.verify_signature(pub, data, sig_text.encode())
    with pytest.raises(PipelineError):
        manifest.verify_signature(pub, data + b" ", sig_text.encode())      # one extra byte breaks it
    with pytest.raises(PipelineError):
        manifest.verify_signature(ephemeral_key()[2], data, sig_text.encode())  # other key


def test_missing_signing_key_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.delenv(manifest.KEY_ENV, raising=False)
    with pytest.raises(PipelineError, match="MANIFEST_SIGNING_KEY is not set"):
        manifest.assemble(tmp_path, None, [], tmp_path / "o", "data-2026.11.01", "2026-11-01T03:00:00Z", set(), set())


def test_garbage_key_does_not_leak_value(monkeypatch):
    monkeypatch.setenv(manifest.KEY_ENV, "super-secret-garbage")
    with pytest.raises(PipelineError) as e:
        manifest.load_private_key_from_env()
    assert "super-secret-garbage" not in str(e.value)


def test_wrong_secret_for_embedded_public_key_is_detected(tmp_path, monkeypatch):
    _, pem, _ = ephemeral_key()
    other_pub = ephemeral_key()[2]
    with pytest.raises(PipelineError, match="does NOT verify"):
        make_release(tmp_path, other_pub, monkeypatch, pem)


def test_sha256sums_lists_every_asset(tmp_path, monkeypatch):
    _, pem, pub = ephemeral_key()
    out = make_release(tmp_path, pub, monkeypatch, pem)
    lines = (out / "SHA256SUMS").read_text().splitlines()
    names = {line.split("  ")[1] for line in lines}
    assert names == {"businesses-es.db.xz", "spam-sample-txt.db.xz", "rules-es.json", "manifest.json",
                     "manifest.json.sig"}
    for line in lines:
        digest, name = line.split("  ")
        assert common.sha256_file(out / name) == digest


def test_carry_over_reuses_previous_packs_and_rewrites_urls(tmp_path, monkeypatch):
    _, pem, pub = ephemeral_key()
    first = make_release(tmp_path / "a", pub, monkeypatch, pem, tag="data-2026.11.01")
    # second build only rebuilds rules; businesses and spam come from the previous release
    monkeypatch.setenv(manifest.KEY_ENV, pem)
    from pipeline import rules
    stage = tmp_path / "b" / "stage"
    entries = rules.build(stage, "2026.11.02")
    out = tmp_path / "b" / "release"
    doc = manifest.assemble(stage, first, entries, out, "data-2026.11.02", "2026-11-02T03:00:00Z",
                            {"rules"}, set(), public_key=pub)
    by_id = {p["id"]: p for p in doc["packs"]}
    assert by_id["businesses-es"]["url"].endswith("/data-2026.11.02/businesses-es.db.xz")
    assert by_id["businesses-es"]["version"] == "2026.11.01"
    assert by_id["rules-es"]["version"] == "2026.11.02"
    assert (out / "businesses-es.db.xz").read_bytes() == (first / "businesses-es.db.xz").read_bytes()
    assert manifest.rules_unchanged(first, entries, stage)


def test_carry_over_detects_corrupted_previous_asset(tmp_path, monkeypatch):
    _, pem, pub = ephemeral_key()
    first = make_release(tmp_path / "a", pub, monkeypatch, pem)
    (first / "businesses-es.db.xz").write_bytes(b"corrupt")
    with pytest.raises(PipelineError, match="does not match"):
        manifest.assemble(tmp_path / "x", first, [], tmp_path / "o", "data-2026.11.02", "2026-11-02T03:00:00Z",
                          set(), set(), public_key=pub)

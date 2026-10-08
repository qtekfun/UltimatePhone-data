import json

from pipeline import cli, manifest

from .helpers import ephemeral_key, FIX


def test_empty_spam_set_succeeds_and_publishes_rules_only(tmp_path, monkeypatch):
    _, pem, pub = ephemeral_key()
    monkeypatch.setenv(manifest.KEY_ENV, pem)
    monkeypatch.setattr(manifest, "load_public_key", lambda path=None: pub)
    stage = tmp_path / "stage"
    assert cli.main(["spam", "--stage", str(stage), "--version", "2026.11.01"]) == 0
    assert json.loads((stage / "entries-spam.json").read_text()) == []
    assert cli.main(["rules", "--stage", str(stage), "--version", "2026.11.01"]) == 0
    out = tmp_path / "release"
    assert cli.main(["assemble", "--stage", str(stage), "--previous", str(tmp_path / "none"), "--out", str(out),
                     "--tag", "data-2026.11.01"]) == 0
    assert [p["id"] for p in json.loads((out / "manifest.json").read_text())["packs"]] == ["rules-es"]
    assert cli.main(["verify", "--dir", str(out)]) == 1   # the real public key must reject an ephemeral signature


def test_assemble_without_key_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(manifest.KEY_ENV, raising=False)
    stage = tmp_path / "stage"
    cli.main(["rules", "--stage", str(stage)])
    assert cli.main(["assemble", "--stage", str(stage), "--out", str(tmp_path / "o")]) == 1
    assert "MANIFEST_SIGNING_KEY" in capsys.readouterr().err


def test_businesses_command_with_local_input(tmp_path, monkeypatch):
    stage = tmp_path / "stage"
    assert cli.main(["businesses", "--region", "ES", "--input", str(FIX / "sample.osm"), "--stage", str(stage),
                     "--version", "2026.11.01"]) == 0
    entries = json.loads((stage / "entries-businesses.json").read_text())
    assert entries[0]["id"] == "businesses-es" and entries[0]["entries"] == 7

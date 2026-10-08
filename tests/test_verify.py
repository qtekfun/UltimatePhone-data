import json

import pytest

from pipeline import common, manifest, verify
from pipeline.common import PipelineError

from .helpers import ephemeral_key, make_release


@pytest.fixture
def release(tmp_path, monkeypatch):
    _, pem, pub = ephemeral_key()
    out = make_release(tmp_path, pub, monkeypatch, pem)
    keyfile = tmp_path / "pub.txt"      # public key only
    import base64
    from cryptography.hazmat.primitives import serialization
    keyfile.write_text(base64.b64encode(pub.public_bytes(serialization.Encoding.Raw,
                                                         serialization.PublicFormat.Raw)).decode())
    return out, keyfile, tmp_path / "vscratch"


def test_verify_end_to_end(release):
    out, keyfile, scratch = release
    report = verify.verify_release(out, scratch, keyfile)
    assert "manifest signature OK" in report
    assert any(l.startswith("businesses-es: OK") for l in report)
    assert any(l.startswith("spam-sample-txt: OK") for l in report)
    assert any(l.startswith("rules-es: OK (1 rules)") for l in report)
    assert verify.main(["--dir", str(out), "--scratch", str(scratch), "--public-key", str(keyfile)]) == 0


def test_known_number_query(release):
    out, keyfile, scratch = release
    verify.verify_release(out, scratch, keyfile, {"businesses-es": "+34915550123"})
    with pytest.raises(PipelineError, match="not found"):
        verify.verify_release(out, scratch, keyfile, {"businesses-es": "+34999999999"})


def test_tampered_asset_fails(release):
    out, keyfile, scratch = release
    p = out / "rules-es.json"
    p.write_text(p.read_text().replace("commercial", "commerciaL", 1))
    with pytest.raises(PipelineError):
        verify.verify_release(out, scratch, keyfile)
    assert verify.main(["--dir", str(out), "--scratch", str(scratch), "--public-key", str(keyfile)]) == 1


def test_tampered_manifest_fails_signature(release):
    out, keyfile, scratch = release
    m = json.loads((out / "manifest.json").read_text())
    m["packs"][0]["entries"] += 1
    (out / "manifest.json").write_bytes(common.json_bytes(m))
    with pytest.raises(PipelineError, match="signature"):
        verify.verify_release(out, scratch, keyfile)


def test_wrong_public_key_fails(release, tmp_path):
    out, _, scratch = release
    with pytest.raises(PipelineError, match="signature"):
        verify.verify_release(out, scratch, common.PUBLIC_KEY_FILE)   # real key vs ephemeral signature


def test_missing_asset_fails(release):
    out, keyfile, scratch = release
    (out / "spam-sample-txt.db.xz").unlink()
    with pytest.raises(PipelineError):
        verify.verify_release(out, scratch, keyfile)

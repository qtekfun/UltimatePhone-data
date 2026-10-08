import shutil

import pytest

from pipeline import audit, common
from pipeline.common import PipelineError


def test_repo_audit_passes():
    report = audit.audit()
    assert any(l.startswith("phoneblock: unknown / excluded") for l in report)


@pytest.fixture
def copy_repo(tmp_path):
    shutil.copytree(common.SOURCES, tmp_path / "sources")
    shutil.copytree(common.ROOT / "LICENSES", tmp_path / "LICENSES")
    return tmp_path


def test_audit_fails_without_licence(copy_repo):
    p = copy_repo / "sources" / "spam" / "phoneblock.yaml"
    p.write_text("\n".join(l for l in p.read_text().splitlines() if not l.startswith("licence:")))
    with pytest.raises(PipelineError, match="licence"):
        audit.audit(copy_repo)


def test_audit_fails_without_redistribution_policy(copy_repo):
    p = copy_repo / "sources" / "spam" / "dontobi-spamcalllist.yaml"
    p.write_text("\n".join(l for l in p.read_text().splitlines() if not l.startswith("redistribution:")))
    with pytest.raises(PipelineError, match="redistribution"):
        audit.audit(copy_repo)


def test_audit_fails_for_package_source_with_unknown_licence(copy_repo):
    (copy_repo / "sources" / "spam" / "x.yaml").write_text(
        "id: x\nname: X\nurl: https://example.org\nformat: txt\nlicence: unknown\nlicence_url: https://e.org\n"
        "redistribution: package\nlevel: COMMUNITY\nfrequency: daily\nverified: '2026-10-08'\nregion: ES\n"
        "attribution: x\n")
    (copy_repo / "LICENSES" / "sources" / "x.md").write_text("x")
    with pytest.raises(PipelineError, match="known licence"):
        audit.audit(copy_repo)


def test_audit_fails_without_licence_note(copy_repo):
    (copy_repo / "LICENSES" / "sources" / "phoneblock.md").unlink()
    with pytest.raises(PipelineError, match="licence note"):
        audit.audit(copy_repo)


def test_osm_regions_configured():
    from pipeline import businesses
    cfg = businesses.load_config()
    assert [r["id"] for r in cfg["regions"]] == ["ES", "DE", "AT"]
    assert all(u.startswith("https://download.geofabrik.de/") for r in cfg["regions"] for u in r["extracts"])

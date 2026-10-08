"""Test helpers: build a mini release from the fixtures with an EPHEMERAL key (never written to disk)."""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipeline import businesses, common, manifest, rules, spam

FIX = Path(__file__).resolve().parent / "fixtures"
VERSION = "2026.11.01"
GENERATED = "2026-11-01T03:00:00Z"


def ephemeral_key():
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return key, pem, key.public_key()


def es_region():
    cfg = businesses.load_config()
    return cfg, businesses.region_config(cfg, "ES")


def spam_card(fmt="txt", **extra):
    card = {
        "id": f"sample-{fmt}", "name": "Sample", "url": "https://example.org/list", "format": fmt,
        "licence": "CC0-1.0", "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "redistribution": "package", "level": "COMMUNITY", "frequency": "daily", "verified": "2026-10-08",
        "region": "ES", "country": "ES", "attribution": "Sample list",
    }
    card.update(extra)
    return card


def build_stage(stage: Path, scratch: Path, with_spam=True):
    cfg, region = es_region()
    entries = [businesses.build_pack(region, cfg, [FIX / "sample.osm"], stage, VERSION, GENERATED, scratch)]
    if with_spam:
        entries.append(spam.build_pack(spam_card("txt"), FIX / "spam.txt", stage, VERSION, GENERATED, scratch))
    entries += rules.build(stage, VERSION)
    return entries


def make_release(tmp: Path, public_key, monkeypatch, pem: str, with_spam=True, previous=None,
                 replace_types=frozenset(), tag="data-2026.11.01"):
    monkeypatch.setenv(manifest.KEY_ENV, pem)
    stage = tmp / "stage"
    entries = build_stage(stage, tmp / "scratch", with_spam)
    out = tmp / "release"
    manifest.assemble(stage, previous, entries, out, tag, GENERATED, set(replace_types), set(),
                      public_key=public_key)
    return out

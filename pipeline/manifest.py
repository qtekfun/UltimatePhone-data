"""Manifest assembly, detached Ed25519 signing, SHA256SUMS, and reuse of unchanged packs.

Signature: Ed25519 (RFC 8032, pure) over the EXACT bytes of manifest.json; manifest.json.sig holds the
base64 (standard alphabet, with padding) of the 64-byte signature, followed by a newline.
The private key is read from the environment variable MANIFEST_SIGNING_KEY (PEM, PKCS#8) only.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from . import common
from .common import PipelineError

KEY_ENV = "MANIFEST_SIGNING_KEY"
MANIFEST = "manifest.json"
SIGNATURE = "manifest.json.sig"
SUMS = "SHA256SUMS"

PACK_KEYS = ["id", "type", "region", "version", "url", "sha256", "bytes", "entries", "license", "attribution",
             "dependsOn", "compression", "uncompressedBytes", "uncompressedSha256", "sourceId"]


def release_base_url(tag: str, repo: str = common.REPO) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/"


def load_public_key(path: Path | None = None) -> Ed25519PublicKey:
    text = (path or common.PUBLIC_KEY_FILE).read_text(encoding="ascii").strip()
    raw = base64.b64decode(text, validate=True)
    if len(raw) != 32:
        raise PipelineError(f"public key must be 32 raw bytes, got {len(raw)}")
    return Ed25519PublicKey.from_public_bytes(raw)


def load_private_key_from_env() -> Ed25519PrivateKey:
    pem = os.environ.get(KEY_ENV, "")
    if not pem.strip():
        raise PipelineError(f"{KEY_ENV} is not set: refusing to build an unsigned release")
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except Exception as e:  # never echo the value
        raise PipelineError(f"{KEY_ENV} is not a valid unencrypted PEM private key ({type(e).__name__})") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise PipelineError(f"{KEY_ENV} is not an Ed25519 key")
    return key


def sign_bytes(key: Ed25519PrivateKey, data: bytes) -> bytes:
    return (base64.b64encode(key.sign(data)) + b"\n")


def verify_signature(public: Ed25519PublicKey, data: bytes, sig_b64: bytes) -> None:
    try:
        sig = base64.b64decode(sig_b64.strip(), validate=True)
    except Exception:
        raise PipelineError("manifest.json.sig is not valid base64") from None
    if len(sig) != 64:
        raise PipelineError(f"signature must be 64 bytes, got {len(sig)}")
    try:
        public.verify(sig, data)
    except InvalidSignature:
        raise PipelineError("manifest signature does NOT verify against the embedded public key") from None


def pack_entry(entry: dict, base_url: str) -> dict:
    e = dict(entry)
    file = e.pop("file")
    e["url"] = base_url + file
    return {k: e[k] for k in PACK_KEYS if k in e}


def build_manifest(entries: list[dict], generated_at: str) -> dict:
    packs = sorted(entries, key=lambda p: (p["type"], p["id"]))
    ids = [p["id"] for p in packs]
    if len(ids) != len(set(ids)):
        raise PipelineError("duplicate pack ids in manifest")
    doc = {"schema": 1, "generatedAt": generated_at, "packs": packs}
    common.validate(doc, "manifest.schema.json", "manifest")
    return doc


def write_sums(release_dir: Path) -> None:
    lines = []
    for p in sorted(release_dir.iterdir()):
        if p.is_file() and p.name != SUMS:
            lines.append(f"{common.sha256_file(p)}  {p.name}")
    (release_dir / SUMS).write_text("\n".join(lines) + "\n", encoding="ascii")


def assemble(stage_dir: Path, previous_dir: Path | None, rebuilt_entries: list[dict], out_dir: Path,
             tag: str, generated_at: str, replace_types: set[str], replace_ids: set[str],
             repo: str = common.REPO, public_key: Ed25519PublicKey | None = None) -> dict:
    """Create the complete, signed release directory.

    `rebuilt_entries` are this run's packs (files in stage_dir). Packs of the previous manifest are carried
    over (asset copied into the new release so that it is self-contained, since old releases are pruned)
    unless their type is in replace_types or their id is in replace_ids or they were rebuilt.
    """
    key = load_private_key_from_env()  # fail loudly BEFORE doing any work
    base = release_base_url(tag, repo)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    entries = [pack_entry(e, base) for e in rebuilt_entries]
    for e in rebuilt_entries:
        shutil.copy2(stage_dir / e["file"], out_dir / e["file"])
    built_ids = {e["id"] for e in rebuilt_entries}
    carried = []
    if previous_dir is not None and (previous_dir / MANIFEST).exists():
        prev = json.loads((previous_dir / MANIFEST).read_text(encoding="utf-8"))
        for p in prev["packs"]:
            if p["id"] in built_ids or p["type"] in replace_types or p["id"] in replace_ids:
                continue
            name = p["url"].rsplit("/", 1)[1]
            src = previous_dir / name
            if not src.exists() or common.sha256_file(src) != p["sha256"]:
                raise PipelineError(f"previous asset {name} is missing or does not match its sha256")
            shutil.copy2(src, out_dir / name)
            q = dict(p)
            q["url"] = base + name
            carried.append(q)
    doc = build_manifest(entries + carried, generated_at)
    data = common.json_bytes(doc)
    (out_dir / MANIFEST).write_bytes(data)
    sig = sign_bytes(key, data)
    (out_dir / SIGNATURE).write_bytes(sig)
    # A wrong secret must fail here, not on every phone.
    verify_signature(public_key or load_public_key(), data, sig)
    write_sums(out_dir)
    return doc


def _get(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "UltimatePhone-data/1"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
            while chunk := resp.read(common.CHUNK):
                out.write(chunk)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def fetch_previous(out_dir: Path, skip_types: set[str], skip_ids: set[str], repo: str = common.REPO,
                   public_key: Ed25519PublicKey | None = None) -> bool:
    """Download the latest release's manifest (signature verified) and the assets that will be carried over.

    Returns False when there is no previous release (first run).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = f"https://github.com/{repo}/releases/latest/download/"
    if not _get(latest + MANIFEST, out_dir / MANIFEST):
        return False
    if not _get(latest + SIGNATURE, out_dir / SIGNATURE):
        raise PipelineError("latest release has a manifest.json but no manifest.json.sig")
    data = (out_dir / MANIFEST).read_bytes()
    verify_signature(public_key or load_public_key(), data, (out_dir / SIGNATURE).read_bytes())
    for p in json.loads(data)["packs"]:
        if p["type"] in skip_types or p["id"] in skip_ids:
            continue
        name = p["url"].rsplit("/", 1)[1]
        if not _get(p["url"], out_dir / name):
            raise PipelineError(f"previous asset {p['url']} not found")
        if common.sha256_file(out_dir / name) != p["sha256"]:
            raise PipelineError(f"previous asset {name} does not match the manifest sha256")
    return True


def rules_unchanged(previous_dir: Path | None, rebuilt_rules: list[dict], stage_dir: Path) -> bool:
    """True when the freshly built rules equal the previous ones (ignoring the version date)."""
    if previous_dir is None or not (previous_dir / MANIFEST).exists():
        return False
    prev = json.loads((previous_dir / MANIFEST).read_text(encoding="utf-8"))
    old = {p["id"]: p for p in prev["packs"] if p["type"] == "rules"}
    if set(old) != {e["id"] for e in rebuilt_rules}:
        return False
    for e in rebuilt_rules:
        new_doc = json.loads((stage_dir / e["file"]).read_text(encoding="utf-8"))
        name = old[e["id"]]["url"].rsplit("/", 1)[1]
        f = previous_dir / name
        if not f.exists():
            return False
        old_doc = json.loads(f.read_text(encoding="utf-8"))
        new_doc["version"] = old_doc["version"] = ""
        if new_doc != old_doc:
            return False
    return True

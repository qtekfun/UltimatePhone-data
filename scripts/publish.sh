#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Publish dist/release as the GitHub release $TAG (marked latest), then keep only the newest $KEEP_RELEASES
# data releases (older releases and their tags are deleted). Errors are never swallowed.
set -euo pipefail
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${TAG:?TAG is required}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
dir="${RELEASE_DIR:-dist/release}"
keep="${KEEP_RELEASES:-2}"
title="${RELEASE_TITLE:-Data ${TAG#data-}}"

notes="UltimatePhone data packs, signed manifest and checksums.
Stable manifest URL: https://github.com/${repo}/releases/latest/download/manifest.json
Verify: manifest.json.sig is a detached Ed25519 signature (base64) over manifest.json; SHA256SUMS lists every asset.
Business packs are derived from OpenStreetMap: © OpenStreetMap contributors, ODbL 1.0."

gh release create "$TAG" --repo "$repo" --latest --title "$title" --notes "$notes" "$dir"/*

# Keep only the newest $keep data releases; the one just published is always kept.
mapfile -t old < <(gh release list --repo "$repo" --limit 100 --json tagName,createdAt \
  -q "[.[]|select(.tagName|startswith(\"data-\"))]|sort_by(.createdAt)|reverse|.[${keep}:][]|.tagName")
for t in "${old[@]}"; do
  [ -n "$t" ] || continue
  [ "$t" = "$TAG" ] && continue
  echo "Deleting $t"
  gh release delete "$t" --repo "$repo" --cleanup-tag --yes
done

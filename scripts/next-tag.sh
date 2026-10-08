#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Choose the release tag: data-YYYY.MM.DD, or data-YYYY.MM.DD-2, -3 ... when that date already has a release
# (a monthly and a daily build can run on the same day). Prints TAG=<tag> to GITHUB_OUTPUT.
set -euo pipefail
: "${GH_TOKEN:?GH_TOKEN is required}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
base="data-$(date -u +%Y.%m.%d)"
tag="$base"
n=2
while true; do
  if out=$(gh release view "$tag" --repo "$repo" 2>&1); then
    tag="$base-$n"
    n=$((n + 1))
  elif grep -qi "not found" <<<"$out"; then
    break
  else
    echo "::error::cannot query releases: $out"
    exit 1
  fi
done
echo "release tag: $tag"
echo "tag=$tag" >> "${GITHUB_OUTPUT:-/dev/null}"

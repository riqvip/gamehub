#!/usr/bin/env bash
# Export images; never mount the Docker socket into the scanner.
set -euo pipefail
cd "$(dirname "$0")/.."
scan_root="$(pwd)/.validation"
mkdir -p "$scan_root/trivy-cache" "$scan_root/trivy-tmp"
scanner='aquasec/trivy@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb'
palworld='thijsvanloef/palworld-server-docker@sha256:07313feaecb42ecdea0b737ae922559dc5ab4c63d69275043f0943bd441fc35e'
docker save -o "$scan_root/gamehub-image.tar" gamehub-local:2
docker save -o "$scan_root/palworld-image.tar" "$palworld"
for artifact in gamehub palworld; do
  docker run --rm --user "$(id -u):$(id -g)" --cap-drop ALL \
    --security-opt no-new-privileges --read-only --memory 1536m --cpus 1 \
    -e TMPDIR=/scan/trivy-tmp -v "$scan_root:/scan:rw" "$scanner" image \
    --cache-dir /scan/trivy-cache --input "/scan/$artifact-image.tar" \
    --scanners vuln --format json --output "/scan/$artifact-trivy.json"
done
# Deliberately reports findings without hiding them via ignore-unfixed or severity filters.

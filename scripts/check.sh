#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/ruff check manager/app tests scripts
.venv/bin/ruff format --check manager/app tests scripts
.venv/bin/bandit -r manager/app scripts -q
.venv/bin/pytest -q
node --check manager/static/app.js
.venv/bin/pip-audit -r manager/requirements.txt --disable-pip --no-deps

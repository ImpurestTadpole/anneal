#!/usr/bin/env bash
# Anneal installer for Ubuntu 20.04 (and newer).
# Ubuntu 20.04 ships Python 3.8, which current numpy/scipy no longer support. This script
# installs uv (a single-file Python manager) and uses it to get Python 3.11 just for Anneal,
# without touching the system Python.
set -euo pipefail
cd "$(dirname "$0")"

sudo apt-get update -y
sudo apt-get install -y curl ca-certificates xdg-utils libgl1 libglib2.0-0

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

uv python install 3.11
uv venv --python 3.11 .venv
# shellcheck disable=SC1091
source .venv/bin/activate
uv pip install -e .
uv pip install cadquery-ocp || echo "STEP support not installed (no wheel for this system). Export STL from CAD instead."

echo
python -m anneal validate
echo
echo "Installed. Use:"
echo "  source $(pwd)/.venv/bin/activate"
echo "  anneal init your-part.stl        # writes your-part.anneal.json; edit the anchors"
echo "  anneal run your-part.anneal.json --open"

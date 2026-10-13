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
# Required packages (numpy, scipy, pyamg, trimesh, scikit-image, matplotlib, manifold3d) must install.
uv pip install -e .
python -c "import numpy, scipy, pyamg, trimesh, skimage, matplotlib, manifold3d"
# Optional packages: a failure does not stop the install or Anneal.
uv pip install cadquery-ocp || echo "STEP support not installed (no wheel for this system). Export STL from CAD instead."
uv pip install gmsh || echo "gmsh not installed. The CalculiX large-deformation check is skipped."

python -m anneal shortcut || true

echo
python -m anneal doctor || true
echo
python -m anneal validate || echo "The validation gate did not pass. Anneal still starts; report this result."
echo
echo "Installed. Use:"
echo "  source $(pwd)/.venv/bin/activate"
echo "  anneal gui                        # the graphical interface, in your browser"
echo "  (or open Anneal from the applications menu)"
echo "  anneal init your-part.stl        # command line: writes your-part.anneal.json"
echo "  anneal run your-part.anneal.json --open"

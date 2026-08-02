#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo apt-get update
sudo apt-get install -y \
  curl \
  git \
  python3-dev \
  swig \
  liblgpio-dev

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

export PATH="$HOME/.local/bin:$PATH"

cd "$PROJECT_ROOT"
uv sync --frozen

echo "Raspberry Pi setup completed."

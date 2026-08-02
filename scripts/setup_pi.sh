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

NVM_VERSION="v0.40.6"
export NVM_DIR="$HOME/.nvm"

if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  curl -o- \
    "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" \
    | bash
fi

"$PROJECT_ROOT/scripts/build_frontend.sh"

echo "Raspberry Pi setup completed."

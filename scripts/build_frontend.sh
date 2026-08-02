#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export NVM_DIR="$HOME/.nvm"

if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  echo "Node Version Manager is not installed."
  exit 1
fi

# Load Node Version Manager for this non-interactive script.
source "$NVM_DIR/nvm.sh"

cd "$PROJECT_ROOT"

NODE_VERSION="$(cat .nvmrc)"

nvm install "$NODE_VERSION"
nvm use "$NODE_VERSION"

cd frontend

# package-lock.json provides a repeatable dependency installation.
npm ci
npm run build

# The production server only needs the generated dist directory.
rm -rf node_modules

echo "Frontend build completed."
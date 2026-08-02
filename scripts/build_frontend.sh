#!/usr/bin/env bash

set -eo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export NVM_DIR="$HOME/.nvm"

if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  echo "Node Version Manager is not installed."
  exit 1
fi

# Node Version Manager is not fully compatible with Bash nounset mode.
source "$NVM_DIR/nvm.sh"

NODE_VERSION="$(cat "$PROJECT_ROOT/.nvmrc")"

echo "Using Node.js ${NODE_VERSION}"
nvm install "$NODE_VERSION"
nvm use "$NODE_VERSION"
nvm alias default "$NODE_VERSION"

cd "$PROJECT_ROOT/frontend"

echo "Installing frontend dependencies"
npm ci

echo "Building frontend"
npm run build

# The Raspberry Pi only needs the compiled frontend at runtime.
rm -rf node_modules

echo "Frontend build completed."
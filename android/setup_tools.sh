#!/usr/bin/env bash
# One-time setup on the Mac: downloads the two Android parts the build
# needs (about 150 MB). Google's licence is shown first; type y to accept.
#
#   bash android/setup_tools.sh

set -euo pipefail
cd "$(dirname "$0")"
source ./tools.sh

"$SDKMANAGER" --sdk_root="$SDK" \
    "platforms;$ANDROID_PLATFORM" \
    "build-tools;$ANDROID_BUILD_TOOLS"

echo
echo "Done. Build the app with: bash android/build.sh"

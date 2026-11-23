#!/usr/bin/env bash
# Builds android/build/visd-HA.apk, the file that is copied to a phone.
#
#   bash android/build.sh
#
# The app is one Java file with no libraries, so it is built with the
# Android tools directly. There is no Gradle and nothing is downloaded.

set -euo pipefail
cd "$(dirname "$0")"
source ./tools.sh

BUILD_TOOLS="$SDK/build-tools/$ANDROID_BUILD_TOOLS"
ANDROID_JAR="$SDK/platforms/$ANDROID_PLATFORM/android.jar"

if [ ! -f "$ANDROID_JAR" ] || [ ! -x "$BUILD_TOOLS/aapt2" ]; then
    echo "The Android parts are missing. Run once: bash android/setup_tools.sh" >&2
    exit 1
fi

# A phone only installs an update whose version number is not lower than
# the installed one. The build time as a number always goes up.
VERSION_CODE="$(date +%y%m%d%H%M | cut -c1-9)"
VERSION_NAME="$(date +%Y.%m.%d)"

# A phone only accepts an update signed with the same key as the app it
# already has. The key is made once and kept here, outside git.
KEYSTORE="runtime/signing.keystore"
KEY_PASSWORD="android"

if [ ! -f "$KEYSTORE" ]; then
    mkdir -p runtime
    keytool -genkeypair \
        -keystore "$KEYSTORE" \
        -storepass "$KEY_PASSWORD" -keypass "$KEY_PASSWORD" \
        -alias visd-ha -keyalg RSA -keysize 2048 -validity 10000 \
        -dname "CN=visd-HA"
    echo "Made a new signing key: android/$KEYSTORE"
fi

WORK="build/work"
rm -rf "$WORK"
mkdir -p "$WORK/classes" "$WORK/generated" "$WORK/dex"

# 1. Layouts, texts and the icon.
"$BUILD_TOOLS/aapt2" compile --dir res -o "$WORK/resources.zip"
"$BUILD_TOOLS/aapt2" link \
    -o "$WORK/unsigned.apk" \
    -I "$ANDROID_JAR" \
    --manifest AndroidManifest.xml \
    --java "$WORK/generated" \
    --min-sdk-version "$MIN_ANDROID" \
    --target-sdk-version "$TARGET_ANDROID" \
    --version-code "$VERSION_CODE" \
    --version-name "$VERSION_NAME" \
    "$WORK/resources.zip"

# 2. The Java code, checked against Android's own classes. The second
#    jar only lets the compiler accept lambdas; it is not put in the app.
javac -source 8 -target 8 -Xlint:-options \
    -bootclasspath "$ANDROID_JAR:$BUILD_TOOLS/core-lambda-stubs.jar" \
    -d "$WORK/classes" \
    $(find src "$WORK/generated" -name '*.java')

# 3. Into the form Android runs.
"$BUILD_TOOLS/d8" --release \
    --min-api "$MIN_ANDROID" \
    --lib "$ANDROID_JAR" \
    --output "$WORK/dex" \
    $(find "$WORK/classes" -name '*.class')

# 4. Put it together, align it and sign it.
(cd "$WORK/dex" && zip -q -j ../unsigned.apk classes.dex)
"$BUILD_TOOLS/zipalign" -f -p 4 "$WORK/unsigned.apk" "$WORK/aligned.apk"
"$BUILD_TOOLS/apksigner" sign \
    --ks "$KEYSTORE" --ks-pass "pass:$KEY_PASSWORD" \
    --out build/visd-HA.apk \
    "$WORK/aligned.apk"
rm -f build/visd-HA.apk.idsig

echo
echo "Built android/build/visd-HA.apk ($(du -h build/visd-HA.apk | cut -f1 | tr -d ' '))"
echo "What the phone will be told about it:"
"$BUILD_TOOLS/aapt2" dump badging build/visd-HA.apk \
    | grep -E "^(package|minSdkVersion|targetSdkVersion|uses-permission|application-label):"

#!/usr/bin/env bash
# Checks how the Android app tidies a typed Pi address (MainActivity
# .tidyAddress and .hostOf). Runs on the Mac, no phone needed.
#
#   bash android/build.sh && bash tests/check_android_address.sh

set -euo pipefail
cd "$(dirname "$0")/../android"
source ./tools.sh

CLASSES="build/work/classes"
ANDROID_JAR="$SDK/platforms/$ANDROID_PLATFORM/android.jar"

if [ ! -d "$CLASSES" ]; then
    echo "Build the app first: bash android/build.sh" >&2
    exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/com/visd/ha"

cat > "$WORK/com/visd/ha/CheckAddress.java" <<'JAVA'
package com.visd.ha;

public class CheckAddress {
    static int failures = 0;

    static void check(String typed, String expected) {
        String got = MainActivity.tidyAddress(typed);
        boolean ok = expected == null ? got == null : expected.equals(got);

        System.out.printf(
                "%s  %-34s -> %s%n", ok ? "ok  " : "FAIL", "\"" + typed + "\"", got);

        if (!ok) {
            failures++;
        }
    }

    public static void main(String[] args) {
        check("192.168.1.31:8000", "192.168.1.31:8000");
        check("192.168.1.31", "192.168.1.31:8000");
        check("  192.168.1.40:8000  ", "192.168.1.40:8000");
        check("http://192.168.1.31:8000", "192.168.1.31:8000");
        check("HTTP://192.168.1.31:8000/", "192.168.1.31:8000");
        check("https://192.168.1.31", "192.168.1.31:8000");
        check("http://192.168.1.31:8000/?tab=live", "192.168.1.31:8000");
        check("192.168.1.31:9000", "192.168.1.31:9000");
        check("raspberrypi.local", "raspberrypi.local:8000");
        check("", null);
        check("   ", null);
        check("192.168.1.31:", null);
        check("192.168.1.31:port", null);
        check("192.168 1.31", null);
        check("user@192.168.1.31", null);
        check("http://", null);

        if (!"192.168.1.31".equals(MainActivity.hostOf("192.168.1.31:8000"))) {
            System.out.println("FAIL  hostOf");
            failures++;
        }

        if (failures > 0) {
            System.out.println(failures + " check(s) failed");
            System.exit(1);
        }

        System.out.println("all address checks passed");
    }
}
JAVA

javac -source 8 -target 8 -Xlint:-options \
    -cp "$CLASSES:$ANDROID_JAR" -d "$WORK" \
    "$WORK/com/visd/ha/CheckAddress.java"
java -cp "$WORK:$CLASSES:$ANDROID_JAR" com.visd.ha.CheckAddress

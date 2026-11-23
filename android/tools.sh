# Where the build tools are on the Mac. Read by setup_tools.sh and
# build.sh; not run by itself.
#
# Both were installed with Homebrew:
#   brew install openjdk@17
#   brew install --cask android-commandlinetools

# Versions of the Android parts that setup_tools.sh downloads.
ANDROID_PLATFORM="android-35"
ANDROID_BUILD_TOOLS="35.0.0"

# The oldest Android the app installs on (26 = Android 8, 2017) and the
# version whose behaviour it asks for (34 = Android 14). Not 35 or later:
# from there Android draws an app under the status bar and the keyboard
# unless the app adds code for it. A plain page needs none of that.
MIN_ANDROID=26
TARGET_ANDROID=34

BREW_PREFIX="$(brew --prefix)"

# The Mac's own Java is version 8, too old for the Android tools.
export JAVA_HOME="$BREW_PREFIX/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"

SDK="${ANDROID_HOME:-$BREW_PREFIX/share/android-commandlinetools}"
SDKMANAGER="$SDK/cmdline-tools/latest/bin/sdkmanager"

if [ ! -x "$JAVA_HOME/bin/javac" ]; then
    echo "JDK 17 is missing. Run: brew install openjdk@17" >&2
    exit 1
fi

if [ ! -x "$SDKMANAGER" ]; then
    echo "The Android command-line tools are missing." >&2
    echo "Run: brew install --cask android-commandlinetools" >&2
    exit 1
fi

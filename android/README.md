# visd-HA for Android

A small Android app that shows the web page the Pi serves, so the phone
does not need Chrome and a typed address. It opens on the Live View tab.

It is a window onto the page and nothing more. Everything it shows comes
from the Pi; when the Pi's page changes, the app shows the new page with
no new APK. The Pi never uses this folder.

## What it does

| Thing | Detail |
|---|---|
| Page it opens | `http://<Pi address>/?tab=live` |
| Pi address | A setting, `192.168.1.31:8000` when first installed |
| Where it works | On the home Wi-Fi only. The Pi is not reachable from outside, by decision |
| Permissions | Internet only. Android grants it without asking. No camera, microphone, storage or location |
| Android versions | Android 8 (2017) and newer |
| Remembered | The ticked cameras and Main/Sub, the same way a browser remembers them |
| Full-screen button on a video | Works. The video is shown in landscape, even with the phone's auto-rotate off; leaving full screen goes back to how the phone is held |
| In the background | The page is told it is hidden and the player closes its camera connections |
| After more than 10 minutes in the background | The page is loaded afresh on return |
| A link that leaves the Pi, or a download | Handed to the phone's browser |

### The Pi address screen

It appears by itself when the Pi does not answer within 10 seconds, with
the address ready to edit and an Open button to try again. To reach it at
any other time, press and hold the app icon and choose "Pi address".

Type the address with or without the port (`192.168.1.31` means port
8000). The Pi serves plain HTTP only, so the app always uses `http://`.

Because the address is a setting, Android is told the app may use plain
HTTP with any address. The app only ever opens the address typed here.

### What decides whether a camera plays

The app uses the phone's own web engine, the same one Chrome uses. Three
of the four main streams are H.265, which needs hardware support in the
phone. If a camera plays in Chrome on a phone, expect it to play in the
app; if it does not play in Chrome, it will not play in the app either.

## Building it on the Mac

The app is one Java file with no libraries. It is built with the Android
tools directly; there is no Gradle and no Android Studio.

One time, to install the tools:

```bash
brew install openjdk@17
```

```bash
brew install --cask android-commandlinetools
```

```bash
bash android/setup_tools.sh
```

The last one downloads the two Android parts the build needs (about
150 MB) and shows Google's licence first; type `y` to accept.

Then, every time:

```bash
bash android/build.sh
```

The result is `android/build/visd-HA.apk`. It is not committed.

The tool locations and the Android versions are in `tools.sh`.

The app cannot be run on the Mac; it is tried on a phone. One part can
be checked without a phone, how a typed address is tidied:

```bash
bash tests/check_android_address.sh
```

## Putting it on a phone

1. Copy `android/build/visd-HA.apk` to the phone (USB cable, Google
   Drive, or any other way).
2. Open the file on the phone with the Files app.
3. Android asks once to allow Files to install unknown apps. Allow it,
   install, and switch that permission off again afterwards if you like.
   Play Protect may warn that it does not know the developer.
4. Developer settings are not needed. They are only for installing over
   a USB cable with `adb`.

A newer APK installs over the old one and keeps the address and the
ticked cameras.

## The signing key

Android installs an update only if it is signed with the same key as the
app already on the phone. `build.sh` makes the key on the first build and
keeps it in `android/runtime/signing.keystore`, which is not in git.

If that file is lost (a new Mac, a deleted folder), the next build makes a
new key. The phone then refuses the update: uninstall the app and install
the new APK. The only things lost are the address setting and the ticked
cameras.

## Files

```
AndroidManifest.xml              the one permission and the one screen
src/com/visd/ha/MainActivity.java  the whole app
res/                             texts, layout, colours and the icon
tools.sh                         where the tools are, Android versions
setup_tools.sh                   one-time download of the Android parts
build.sh                         builds the APK
```

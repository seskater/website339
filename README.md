# Liked Song Alarm (Android)

An Android alarm clock that wakes you with a random song from your Spotify **Liked Songs**. When that song ends, it plays another random like, and it keeps going until you tap **I'm up**.

## How it works

- **Rings on time, even when the phone is asleep.** It uses `AlarmManager.setAlarmClock`, the same mechanism the built-in Clock app uses. The alarm survives reboots and time zone changes.
- **Full-screen alarm over the lock screen.** It shows the album art and song name, with buttons for **Snooze**, **I'm up** and **Play a different song**.
- **Random pick from your likes.** It asks the Spotify Web API for songs at random positions in your Liked Songs, so it stays fast with thousands of likes. Songs you woke up to recently are skipped.
- **Plays through the Spotify app** using Spotify's App Remote SDK. It switches playback to the phone first, so a speaker Spotify was last connected to won't start playing across the house.
- **Gentle fade-in.** Media volume ramps up over 30 seconds to 5 minutes, up to the level you chose. It's set back to your previous volume afterwards.
- **Can't oversleep.** If Spotify can't play (no internet, logged out, or silent after 20 seconds), it plays your phone's normal alarm sound instead. It turns itself off after 30 minutes.
- **Settings:** repeat days, volume, fade-in length and snooze length.

## Requirements

- An Android phone running Android 8.0 or newer
- The **Spotify app**, installed and logged in
- **Spotify Premium.** Spotify requires it for playback control and for apps made in its developer dashboard.

## Install

**Option A: download a build.** Every push to this repo runs the **Build APK** workflow. Open the repo's **Actions** tab, pick the latest run and download `liked-song-alarm-apk`. Unzip it, copy `app-debug.apk` to your phone and open it. Allow installing from unknown sources when Android asks.

**Option B: build it yourself.** Open the folder in Android Studio and press Run, or use the command line:

```sh
./gradlew assembleDebug    # APK ends up in app/build/outputs/apk/debug/
```

## One-time Spotify setup (about 5 minutes)

The app's first screen walks you through this and has copy buttons for each value.

1. Go to <https://developer.spotify.com/dashboard> and click **Create app**. Tick **Web API** and **Android**.
2. Add the **Redirect URI** `likedsongalarm://callback`.
3. Under **Android packages**, add:
   - Package name: `com.likedsongalarm`
   - SHA-1 fingerprint: `71:75:C9:FA:03:B2:7B:96:0B:DA:3A:E0:14:B1:1B:C6:F8:AB:D8:DA`

   This fingerprint belongs to the signing key in `app/debug.keystore`, so it's the same for every build of this repo. If you sign with your own key, use the fingerprint shown on the app's setup screen.
4. Copy the app's **Client ID** into Liked Song Alarm and tap **Connect Spotify**.
5. Approve the login in the browser, then approve **"allow this app to control Spotify"** in the Spotify app.
6. Set a time, turn on the switch, and tap **Test alarm now** to check it.

## Getting reliable alarms

- Allow **notifications**. The alarm needs them to ring.
- On Android 14 and newer, allow **full-screen alarms** if the app shows a warning about it.
- Some phones, such as Xiaomi, Huawei and older Samsungs, kill background apps aggressively. If the alarm doesn't ring, set Liked Song Alarm's battery setting to **Unrestricted**. <https://dontkillmyapp.com> has steps for each brand.

## Project layout

| File | What it does |
| --- | --- |
| `AlarmScheduler.kt` | Works out the next ring time (repeat days, snooze) and schedules it with `AlarmManager`. Also contains the alarm and boot receivers. |
| `AlarmService.kt` | Foreground service that rings: picks songs, controls Spotify, fades in the volume, and falls back to the alarm sound. |
| `AlarmActivity.kt` | Full-screen ringing view shown over the lock screen. |
| `MainActivity.kt` | Setup screen and alarm settings (Jetpack Compose). |
| `SpotifyAuth.kt` | Spotify login using PKCE, so no client secret or server is needed. Also refreshes the token. |
| `SpotifyApi.kt` | Web API calls: profile, Liked Songs count, random liked songs. |
| `SpotifyRemote.kt` | Coroutine wrappers for the Spotify App Remote SDK. |
| `app/libs/spotify-app-remote-release-0.8.0.aar` | Spotify App Remote SDK, from [spotify/android-sdk](https://github.com/spotify/android-sdk) (Apache 2.0). It isn't published to Maven. |

Run the unit tests with `./gradlew testDebugUnitTest`.

## Privacy

Your Spotify login and settings are stored only in the app's private storage on your phone. The app talks only to Spotify: `accounts.spotify.com`, `api.spotify.com` and the Spotify app on your phone.

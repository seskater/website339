# Liked Song Alarm

A morning alarm that wakes you with a random song from your Spotify **Liked Songs**. After that song it keeps playing more random likes until you tap **I'm up**.

It's a static web page (`index.html`, `app.js`, `style.css`) with no server and no build step. It talks to Spotify from your browser.

## Features

- Picks a random liked song each morning by jumping to a random spot in your library, so it stays fast with thousands of likes. Songs you woke up to recently are skipped.
- Plays in the browser tab through the Spotify Web Playback SDK, with a volume fade-in.
- Lets you choose repeat days, volume, fade-in length and snooze length.
- Full-screen ringing view with **Snooze**, **Different song** and **I'm up** buttons.
- Backups, so it doesn't stay silent:
  1. If the tab can't play (for example on a phone browser), it plays on your other Spotify devices instead: the phone app, a desktop app or a speaker.
  2. If Spotify can't play at all, or nothing is audible after 15 seconds, it beeps.
- Keeps the screen awake while the alarm is set, where the browser supports the Wake Lock API.

## Requirements

- **Spotify Premium**, which Spotify requires for playback control and for the apps you create in its developer dashboard.
- A desktop browser (Chrome, Edge or Firefox) that stays open overnight. Mobile browsers can't run the in-tab player, so on a phone the alarm plays through your Spotify app instead. Open the Spotify app shortly before you go to sleep so it shows up as a device.

## Setup (about 5 minutes)

1. **Host the page.** Pick one:
   - **GitHub Pages:** in this repo go to *Settings → Pages*, choose *Deploy from a branch*, pick the branch and `/ (root)`. The page will be at `https://<user>.github.io/website339/`.
   - **Locally:** run `python3 -m http.server 8000 --bind 127.0.0.1` in this folder and open `http://127.0.0.1:8000/`. Spotify only allows `http://` for loopback IPs, so use `127.0.0.1` instead of `localhost`.
2. **Create a Spotify app** at <https://developer.spotify.com/dashboard>:
   - Tick **Web API** and **Web Playback SDK**.
   - Add a **Redirect URI** that exactly matches the one shown on the page's setup screen, including the trailing `/`.
   - Copy the **Client ID**. No client secret is needed because the page uses PKCE.
3. Open the page, paste the Client ID, click **Connect Spotify** and approve the request.
4. Choose a time and days, then click **Set alarm**. Use **Test alarm now** to check it.

## Tips for a reliable alarm

- Leave the tab open and in front, with the laptop plugged in and the lid open. A sleeping computer can't ring. If the page wakes up more than 30 minutes after an alarm time, it skips that alarm and schedules the next one instead of ringing late.
- Keep the system volume up. The slider on the page only sets Spotify's volume.
- After you reload the page, tap it once. Browsers block sound until you interact with the page, and an orange banner reminds you.

## Privacy

Your Client ID, your login tokens and your settings stay in this browser's `localStorage`. The page talks only to `accounts.spotify.com`, `api.spotify.com` and Spotify's player script at `sdk.scdn.co`.

'use strict';

// ---------------------------------------------------------------------------
// Config and small helpers
// ---------------------------------------------------------------------------

const SCOPES = [
  'user-library-read',          // read Liked Songs
  'streaming',                  // Web Playback SDK
  'user-read-email',
  'user-read-private',
  'user-read-playback-state',   // list devices
  'user-modify-playback-state', // start / pause playback
].join(' ');

const TRACKS_PER_ALARM = 8;          // first one is "the" song, the rest keep it ringing
const RECENT_MEMORY = 30;            // avoid repeating the last N wake-up songs
const MISSED_ALARM_GRACE_MS = 30 * 60 * 1000;
const PLAYBACK_WATCHDOG_MS = 15000;  // beep if nothing is audible by then

const REDIRECT_URI = location.origin + location.pathname;
const $ = (sel) => document.querySelector(sel);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const store = {
  get(key, fallback = null) {
    try {
      const raw = localStorage.getItem('alarm.' + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try { localStorage.setItem('alarm.' + key, JSON.stringify(value)); } catch { /* storage unavailable */ }
  },
  del(key) {
    try { localStorage.removeItem('alarm.' + key); } catch { /* storage unavailable */ }
  },
};

let toastTimer;
function toast(message, ms = 4000) {
  const el = $('#toast');
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, ms);
}

function fmtTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ---------------------------------------------------------------------------
// Spotify auth (Authorization Code with PKCE, no server needed)
// ---------------------------------------------------------------------------

function randomString(length) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => chars[b % chars.length]).join('');
}

async function pkceChallenge(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function login() {
  const clientId = $('#client-id').value.trim();
  if (!/^[0-9a-f]{32}$/i.test(clientId)) {
    toast('That doesn’t look like a Spotify Client ID (32 letters and numbers).');
    return;
  }
  const verifier = randomString(64);
  const state = randomString(16);
  store.set('clientId', clientId);
  store.set('verifier', verifier);
  store.set('oauthState', state);

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    scope: SCOPES,
    redirect_uri: REDIRECT_URI,
    code_challenge_method: 'S256',
    code_challenge: await pkceChallenge(verifier),
    state,
  });
  location.href = 'https://accounts.spotify.com/authorize?' + params;
}

async function tokenRequest(body) {
  const res = await fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error_description || data.error || `Spotify login failed (${res.status})`);
  const previous = store.get('token', {});
  const token = {
    access: data.access_token,
    refresh: data.refresh_token || previous.refresh, // Spotify may or may not rotate it
    expiresAt: Date.now() + data.expires_in * 1000,
  };
  store.set('token', token);
  return token;
}

// Finishes the login when Spotify redirects back with ?code=…
async function handleRedirect() {
  const q = new URLSearchParams(location.search);
  if (!q.has('code') && !q.has('error')) return;
  history.replaceState(null, '', REDIRECT_URI);

  if (q.has('error')) throw new Error('Spotify login was cancelled (' + q.get('error') + ').');
  if (q.get('state') !== store.get('oauthState')) throw new Error('Login check failed. Please connect again.');

  await tokenRequest({
    grant_type: 'authorization_code',
    code: q.get('code'),
    redirect_uri: REDIRECT_URI,
    client_id: store.get('clientId'),
    code_verifier: store.get('verifier'),
  });
  store.del('verifier');
  store.del('oauthState');
}

let refreshing = null;
async function getAccessToken() {
  const token = store.get('token');
  if (!token) throw new Error('Not connected to Spotify.');
  if (Date.now() < token.expiresAt - 60_000) return token.access;

  refreshing ??= tokenRequest({
    grant_type: 'refresh_token',
    refresh_token: token.refresh,
    client_id: store.get('clientId'),
  }).finally(() => { refreshing = null; });
  return (await refreshing).access;
}

function logout() {
  disarm();
  store.del('token');
  player?.disconnect();
  location.reload();
}

// ---------------------------------------------------------------------------
// Spotify Web API
// ---------------------------------------------------------------------------

async function api(path, { method = 'GET', query, body } = {}, attempt = 0) {
  const url = new URL('https://api.spotify.com/v1' + path);
  for (const [k, v] of Object.entries(query || {})) url.searchParams.set(k, v);

  const res = await fetch(url, {
    method,
    headers: {
      Authorization: 'Bearer ' + await getAccessToken(),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 429 && attempt < 3) {
    await sleep(Number(res.headers.get('Retry-After') || 1) * 1000);
    return api(path, { method, query, body }, attempt + 1);
  }
  if (res.status === 401 && attempt < 1) {
    // Token may have been revoked early; force a refresh and retry once.
    const token = store.get('token');
    if (token) store.set('token', { ...token, expiresAt: 0 });
    return api(path, { method, query, body }, attempt + 1);
  }

  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* some endpoints return plain text */ }
  if (!res.ok) {
    const err = new Error(data?.error?.message || `Spotify error ${res.status}`);
    err.status = res.status;
    err.reason = data?.error?.reason;
    throw err;
  }
  return data;
}

async function likedSongCount() {
  const page = await api('/me/tracks', { query: { limit: 1 } });
  return page.total;
}

// Picks random Liked Songs by jumping to random offsets, so it stays fast
// no matter how many songs are in the library.
async function pickRandomTracks(count) {
  const total = await likedSongCount();
  if (!total) throw new Error('Your Liked Songs list is empty.');

  const want = Math.min(count, total);
  const offsets = new Set();
  const attempts = Math.min(total, want + 4); // a few spares for unplayable/local files
  while (offsets.size < attempts) offsets.add(Math.floor(Math.random() * total));

  const tracks = await Promise.all([...offsets].map((offset) =>
    api('/me/tracks', { query: { limit: 1, offset, market: 'from_token' } })
      .then((page) => page.items[0]?.track)
      .catch(() => null)));

  const recent = new Set(store.get('recent', []));
  const playable = tracks.filter((t) => t && !t.is_local && t.is_playable !== false);
  // Songs you woke up to recently go to the back of the line.
  playable.sort((a, b) => recent.has(a.id) - recent.has(b.id));
  if (!playable.length) throw new Error('Couldn’t find a playable liked song.');
  return playable.slice(0, want);
}

function rememberWakeSong(track) {
  const recent = store.get('recent', []).filter((id) => id !== track.id);
  recent.unshift(track.id);
  store.set('recent', recent.slice(0, RECENT_MEMORY));
}

// ---------------------------------------------------------------------------
// In-browser player (Spotify Web Playback SDK, Premium only)
// ---------------------------------------------------------------------------

let player = null;
let sdkDeviceId = null;
const sdkLoaded = new Promise((resolve) => { window.onSpotifyWebPlaybackSDKReady = resolve; });

function setPlayerStatus(text, warn = false) {
  const el = $('#player-status');
  el.textContent = text;
  el.classList.toggle('warn', warn);
}

async function initPlayer() {
  const script = document.createElement('script');
  script.src = 'https://sdk.scdn.co/spotify-player.js';
  script.onerror = () => setPlayerStatus('Couldn’t load Spotify player', true);
  document.head.append(script);
  await sdkLoaded;

  player = new Spotify.Player({
    name: 'Liked Song Alarm',
    getOAuthToken: (cb) => getAccessToken().then(cb, () => cb('')),
    volume: settings().volume,
  });
  player.addListener('ready', ({ device_id }) => {
    sdkDeviceId = device_id;
    setPlayerStatus('Ready in this tab');
  });
  player.addListener('not_ready', () => {
    sdkDeviceId = null;
    setPlayerStatus('Reconnecting…', true);
  });
  player.addListener('initialization_error', ({ message }) =>
    setPlayerStatus('This browser can’t play Spotify: ' + message, true));
  player.addListener('authentication_error', ({ message }) =>
    setPlayerStatus('Login problem: ' + message, true));
  player.addListener('account_error', () =>
    setPlayerStatus('Spotify Premium is required to play here', true));
  player.addListener('playback_error', ({ message }) => console.warn('Playback error:', message));
  player.addListener('player_state_changed', (state) => {
    const track = state?.track_window?.current_track;
    if (track && ringing) showTrack(track);
  });
  await player.connect();
}

// Waits briefly for the in-tab player; it can drop and reconnect overnight.
async function inTabDevice(timeoutMs = 10000) {
  if (sdkDeviceId || !player) return sdkDeviceId;
  player.connect();
  const until = Date.now() + timeoutMs;
  while (!sdkDeviceId && Date.now() < until) await sleep(250);
  return sdkDeviceId;
}

// ---------------------------------------------------------------------------
// Backup beep (Web Audio), for when Spotify can't play
// ---------------------------------------------------------------------------

let audioCtx = null;
let beepTimer = null;

// Must run inside a click/tap so the browser allows sound later.
function unlockAudio() {
  try {
    audioCtx ??= new (window.AudioContext || window.webkitAudioContext)();
    audioCtx.resume();
  } catch { /* no Web Audio */ }
  player?.activateElement?.();
  $('#gesture-banner').hidden = true;
  needsGesture = false;
}

function startBeep() {
  if (beepTimer || !audioCtx) return;
  const beep = () => {
    audioCtx.resume();
    const t = audioCtx.currentTime;
    for (const offset of [0, 0.25, 0.5]) {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, t + offset);
      gain.gain.exponentialRampToValueAtTime(0.4, t + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + offset + 0.18);
      osc.connect(gain).connect(audioCtx.destination);
      osc.start(t + offset);
      osc.stop(t + offset + 0.2);
    }
  };
  beep();
  beepTimer = setInterval(beep, 1500);
}

function stopBeep() {
  clearInterval(beepTimer);
  beepTimer = null;
}

// ---------------------------------------------------------------------------
// Settings and scheduling
// ---------------------------------------------------------------------------

const DEFAULTS = { time: '07:00', days: [1, 2, 3, 4, 5], volume: 0.7, fadeSeconds: 60, snoozeMinutes: 9 };

function settings() {
  return { ...DEFAULTS, ...store.get('settings', {}) };
}

function saveSettingsFromForm() {
  const days = [...document.querySelectorAll('#days button[aria-pressed="true"]')].map((b) => Number(b.dataset.day));
  store.set('settings', {
    time: $('#alarm-time').value || DEFAULTS.time,
    days,
    volume: Number($('#volume').value) / 100,
    fadeSeconds: Number($('#fade').value),
    snoozeMinutes: Number($('#snooze').value),
  });
  if (store.get('armed')) scheduleNext(); // editing an armed alarm reschedules it
  render();
}

function loadSettingsIntoForm() {
  const s = settings();
  $('#alarm-time').value = s.time;
  $('#volume').value = Math.round(s.volume * 100);
  $('#volume-out').textContent = Math.round(s.volume * 100) + '%';
  $('#fade').value = String(s.fadeSeconds);
  $('#snooze').value = String(s.snoozeMinutes);
  for (const b of document.querySelectorAll('#days button')) {
    b.setAttribute('aria-pressed', String(s.days.includes(Number(b.dataset.day))));
  }
}

function nextAlarmAfter(from) {
  const s = settings();
  const [h, m] = s.time.split(':').map(Number);
  for (let i = 0; i < 8; i++) {
    const d = new Date(from);
    d.setDate(d.getDate() + i);
    d.setHours(h, m, 0, 0);
    if (d > from && (s.days.length === 0 || s.days.includes(d.getDay()))) return d.getTime();
  }
  return null;
}

function scheduleNext(from = new Date()) {
  store.set('nextFire', nextAlarmAfter(from));
  store.del('snoozeUntil');
}

let wakeLock = null;
async function keepScreenOn() {
  if (!store.get('armed') && !ringing) return;
  try { wakeLock = await navigator.wakeLock?.request('screen'); } catch { /* not allowed right now */ }
}

function arm() {
  unlockAudio();
  saveSettingsFromForm();
  store.set('armed', true);
  scheduleNext();
  keepScreenOn();
  const next = new Date(store.get('nextFire'));
  toast(`Alarm set for ${next.toLocaleDateString([], { weekday: 'long' })} at ${fmtTime(next)}.`);
  render();
}

function disarm() {
  store.set('armed', false);
  store.del('nextFire');
  store.del('snoozeUntil');
  wakeLock?.release().catch(() => {});
  wakeLock = null;
  render();
}

function render() {
  const armed = store.get('armed');
  const armBtn = $('#arm');
  armBtn.textContent = armed ? 'Turn alarm off' : 'Set alarm';
  armBtn.classList.toggle('armed', !!armed);

  const nextEl = $('#next-alarm');
  const target = store.get('snoozeUntil') || store.get('nextFire');
  if (!armed || !target) {
    nextEl.textContent = 'No alarm set';
    nextEl.classList.remove('on');
    return;
  }
  const mins = Math.max(0, Math.round((target - Date.now()) / 60000));
  const inText = mins >= 60 ? `${Math.floor(mins / 60)} h ${mins % 60} min` : `${mins} min`;
  const date = new Date(target);
  const day = date.toDateString() === new Date().toDateString()
    ? 'today' : date.toLocaleDateString([], { weekday: 'long' });
  nextEl.textContent = `${store.get('snoozeUntil') ? 'Snoozed until' : 'Alarm'} ${day} at ${fmtTime(date)} · in ${inText}`;
  nextEl.classList.add('on');
}

// Runs every second. Compares against a stored timestamp, so a throttled
// background tab still rings as soon as it gets a tick.
function tick() {
  const now = new Date();
  $('#clock').textContent = fmtTime(now);
  $('#ring-clock').textContent = fmtTime(now);

  if (store.get('armed') && !ringing) {
    const target = store.get('snoozeUntil') || store.get('nextFire');
    if (target && now.getTime() >= target) {
      scheduleNext(new Date(Math.max(target, now.getTime() - 1000)));
      if (now.getTime() - target > MISSED_ALARM_GRACE_MS) {
        toast('Missed an alarm while this device was asleep. The next one is scheduled.', 8000);
      } else {
        ring();
      }
    }
  }
  if (now.getSeconds() === 0 || !tick.rendered) { render(); tick.rendered = true; }
}

// ---------------------------------------------------------------------------
// Ringing
// ---------------------------------------------------------------------------

let ringing = false;
let playingOn = null; // device id the alarm is playing on
let fadeTimer = null;
let watchdogTimer = null;

function showTrack(track) {
  $('#ring-title').textContent = track.name;
  $('#ring-artist').textContent = track.artists.map((a) => a.name).join(', ');
  const art = track.album?.images?.[0]?.url;
  if (art) $('#ring-art').src = art; else $('#ring-art').removeAttribute('src');
}

function ringNote(text) {
  const el = $('#ring-note');
  el.textContent = text || '';
  el.hidden = !text;
}

function fadeIn(targetVolume, seconds) {
  clearInterval(fadeTimer);
  if (!seconds) { player.setVolume(targetVolume); return; }
  const start = Date.now();
  player.setVolume(0.02);
  fadeTimer = setInterval(() => {
    const p = Math.min(1, (Date.now() - start) / (seconds * 1000));
    player.setVolume(Math.max(0.02, targetVolume * p));
    if (p >= 1) clearInterval(fadeTimer);
  }, 500);
}

async function ring() {
  ringing = true;
  $('#ringing').hidden = false;
  $('#ring-title').textContent = 'Good morning';
  $('#ring-artist').textContent = 'Picking a song from your likes…';
  $('#ring-art').removeAttribute('src');
  ringNote('');
  $('#snooze-btn').textContent = `Snooze ${settings().snoozeMinutes} min`;
  keepScreenOn();
  await playRandom();
}

async function playRandom() {
  const s = settings();
  clearTimeout(watchdogTimer);
  try {
    const tracks = await pickRandomTracks(TRACKS_PER_ALARM);
    if (!ringing) return;
    showTrack(tracks[0]);
    rememberWakeSong(tracks[0]);
    const uris = tracks.map((t) => t.uri);

    const device = await inTabDevice();
    if (device) {
      await player.setVolume(s.fadeSeconds ? 0.02 : s.volume);
      await api('/me/player/play', { method: 'PUT', query: { device_id: device }, body: { uris } });
      playingOn = device;
      fadeIn(s.volume, s.fadeSeconds);
      // If the browser blocked audio, the SDK sits paused. Beep instead of staying silent.
      watchdogTimer = setTimeout(async () => {
        const state = await player.getCurrentState().catch(() => null);
        if (ringing && (!state || state.paused)) {
          ringNote('Spotify didn’t start in this tab, so here’s a beep.');
          startBeep();
        }
      }, PLAYBACK_WATCHDOG_MS);
      return;
    }

    // In-tab player unavailable: try the user's phone/speaker/desktop app.
    const { devices } = await api('/me/player/devices');
    const target = devices.find((d) => d.is_active && !d.is_restricted)
      || devices.find((d) => !d.is_restricted);
    if (!target) throw new Error('No Spotify player is available.');
    await api('/me/player/play', { method: 'PUT', query: { device_id: target.id }, body: { uris } });
    playingOn = target.id;
    ringNote(`Playing on ${target.name}`);
  } catch (err) {
    console.error(err);
    if (!ringing) return;
    ringNote(`Couldn’t play Spotify (${err.message}). Beeping instead.`);
    $('#ring-title').textContent = 'Wake up!';
    $('#ring-artist').textContent = '';
    startBeep();
  }
}

async function stopRinging({ snooze = false } = {}) {
  ringing = false;
  $('#ringing').hidden = true;
  clearInterval(fadeTimer);
  clearTimeout(watchdogTimer);
  stopBeep();

  try {
    if (playingOn && playingOn === sdkDeviceId) await player.pause();
    else if (playingOn) await api('/me/player/pause', { method: 'PUT', query: { device_id: playingOn } });
  } catch { /* already stopped */ }
  playingOn = null;

  if (snooze && store.get('armed')) {
    store.set('snoozeUntil', Date.now() + settings().snoozeMinutes * 60000);
    toast(`Snoozing for ${settings().snoozeMinutes} minutes.`);
  } else {
    store.del('snoozeUntil');
    if (!store.get('armed')) { wakeLock?.release().catch(() => {}); wakeLock = null; }
  }
  render();
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

let needsGesture = false;

function bindUi() {
  $('#redirect-uri').textContent = REDIRECT_URI;
  $('#client-id').value = store.get('clientId', '');
  $('#copy-redirect').addEventListener('click', () => {
    navigator.clipboard?.writeText(REDIRECT_URI).then(() => toast('Copied.'), () => toast('Copy it by hand.'));
  });
  $('#connect').addEventListener('click', login);
  $('#logout').addEventListener('click', logout);

  $('#arm').addEventListener('click', () => (store.get('armed') ? disarm() : arm()));
  $('#test').addEventListener('click', () => { unlockAudio(); ring(); });
  $('#stop-btn').addEventListener('click', () => stopRinging());
  $('#snooze-btn').addEventListener('click', () => stopRinging({ snooze: true }));
  $('#another-btn').addEventListener('click', () => {
    stopBeep();
    ringNote('');
    $('#ring-artist').textContent = 'Picking another song…';
    playRandom();
  });
  $('#gesture-banner').addEventListener('click', unlockAudio);

  for (const b of document.querySelectorAll('#days button')) {
    b.addEventListener('click', () => {
      b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true'));
      saveSettingsFromForm();
    });
  }
  for (const id of ['#alarm-time', '#fade', '#snooze']) $(id).addEventListener('change', saveSettingsFromForm);
  $('#volume').addEventListener('input', () => {
    $('#volume-out').textContent = $('#volume').value + '%';
  });
  $('#volume').addEventListener('change', saveSettingsFromForm);

  // Any tap re-enables sound after a reload.
  document.addEventListener('pointerdown', () => { if (needsGesture) unlockAudio(); }, { capture: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') keepScreenOn();
  });
}

async function main() {
  bindUi();
  try {
    await handleRedirect();
  } catch (err) {
    toast(err.message, 8000);
  }

  if (!store.get('token')) {
    $('#setup').hidden = false;
    return;
  }

  $('#app').hidden = false;
  $('#logout').hidden = false;
  loadSettingsIntoForm();

  if (store.get('armed')) {
    // A fresh page load has no user gesture yet, so sound is blocked until a tap.
    needsGesture = true;
    $('#gesture-banner').hidden = false;
    if (!store.get('nextFire')) scheduleNext();
  }

  tick();
  setInterval(tick, 1000);

  try {
    const [me, count] = await Promise.all([api('/me'), likedSongCount()]);
    $('#account').textContent = me.display_name || me.id;
    if (me.product && me.product !== 'premium') {
      $('#account').textContent += ' (not Premium)';
      $('#account').classList.add('warn');
    }
    $('#liked-count').textContent = count.toLocaleString();
  } catch (err) {
    $('#account').textContent = err.message;
    $('#account').classList.add('warn');
    if (err.message.includes('Not connected') || /invalid_grant|revoked/i.test(err.message)) {
      store.del('token');
      toast('Your Spotify login expired. Please connect again.', 8000);
    }
  }

  initPlayer().catch((err) => setPlayerStatus(err.message, true));
}

main();

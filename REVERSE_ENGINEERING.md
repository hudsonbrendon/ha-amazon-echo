# Amazon Echo for Home Assistant — RE findings, gap analysis and design

Date: 2026-11-15. Raw evidence (real account responses) is kept privately and is not part of this repository.

## 1. What was reverse engineered

| Source | How | Result |
|---|---|---|
| Echo devices on the LAN (7 Echos, 4 Fire TVs) | mDNS browse, SSDP, full TCP scan, banner/TLS probes | §2 |
| Alexa Android app `com.amazon.dee.app` 2.2.730155.0 | REA `inspect_android_package` (evidence `ev_d535c118…`), Hermes v96 string table (575 682 strings) | 795 `/api/*` routes (`out/api_paths.txt`), setting keys, feature ids |
| Alexa cloud, live, with the existing `alexa_media` session | read-only GETs + no-op writes (`tools/ax.py`), GraphQL introspection (`tools/gql.py`) | §3 |
| `alexa_media_player` 5.21.0 + `alexapy` | source read | `inventory-alexa_media_player.md` |
| HA core `alexa_devices` + `aioamazondevices` 17.2.12 | source read | `inventory-alexa_devices-core.md` |

## 2. Local (LAN) surface of an Echo — observed

| Port / service | What it is | Usable? |
|---|---|---|
| mDNS `_spotify-connect._tcp` → TCP 4070 `GET /spotifyConnect?action=getInfo` | Spotify Connect zeroconf. JSON: `remoteName`, `modelDisplayName` (`Echo_Dot`, `Echo_Plus`, `Echo_Pop`), `brandDisplayName: "Amazon"`, `deviceID`, `activeUser`, `groupStatus`, `aliases[]` (own name + multi-room groups, `isGroup`), `libraryVersion` | **Yes, unauthenticated.** Discovery, name→IP mapping, liveness, Spotify active user, group membership |
| mDNS `_matter._tcp` port 5541, instance `<fabric>-<node>` | Echo is a Matter **controller** node on the Alexa fabric | Discovery/fingerprint only (it is not a controllable Matter device) |
| mDNS `_meshcop._udp` (Echo Plus) | Thread border router (`vn=amazon`, `nn=AMZN-Thread-xxxx`, `tv=1.3.0`) | Fingerprint; Thread network name |
| TCP 55442 | HTTP (civetweb-like, `DAV: 1`), every path 404. Whole-home-audio distribution | Liveness only |
| TCP 55443 | TLS 1.2, self-signed `O=WHALEXA`, **requires client certificate** | No |
| TCP 55445 | TLS, resets | No |
| TCP 1080 (Echo Pop and Echo Dot 3rd gen; not on Echo Plus) | SOCKS5, accepts method `00` (no auth) on greeting. CONNECT not tested | Not used. Worth knowing as a security observation |
| TCP 8888 (Pop, Dot 3rd gen, Show 5) | resets | No |
| Fire TV: `_amzn-wplay._tcp`, `_matterd._udp` (commissioner), `_adb._tcp` | WhisperPlay device manager, ADB | ADB is already covered by HA `androidtv` |

**Conclusion (observed, not assumed):** an Echo exposes no local *control* API. "Local first" therefore means:
discovery, IP/MAC mapping, reachability and Spotify/group state come from the LAN without the cloud; state changes arrive by
push (HTTP/2) instead of polling; commands necessarily go to the cloud. The integration keeps working for local sensors when the cloud is down.

Scan coverage: full 1–65535 TCP scan completed on 3 hosts (an Echo Plus, an Echo Pop and an Echo Dot 3rd gen) before the background job hit its time limit; the other Echos and the Fire TV were checked only on the union of known ports (`out/fullscan_partial.txt`). Fire TV 4K Max: 5555 (ADB), 8009, 34997/38165 (WhisperPlay), 55442/55443/55445, 56193 (Spotify zeroconf).

## 3. Cloud API — verified live (GET unless noted)

Base `https://alexa.amazon.com.br` (cookie + `csrf` header). All shapes are in `out/live/`.

New relative to **both** existing integrations (✔ = verified live, W = write verified with a no-op write of the value just read):

| Capability | Endpoint | Status |
|---|---|---|
| Wi-Fi SSID + MAC | `GET /api/device-wifi-details?deviceSerialNumber=;deviceType=` | ✔ |
| MAC, temperature, volume, reachability, DND, Fire TV remote battery, Fire TV ambient mode for every endpoint in one call | `POST /nexus/v1/graphql` (`listEndpoints`), **introspection is enabled** (1398 types, `out/live/gql_introspect.json`) | ✔ |
| Equalizer bass/mid/treble | `GET|POST /api/equalizer/{dsn}/{type}` `{bass,mid,treble}` −6..6 | ✔ W |
| Alarm/timer volume | `GET /api/device-notification-state`, `PUT …/{type}/{sw}/{dsn}` | ✔ W |
| Wake word + available wake words | `GET /api/wake-word`, `GET /api/wake-words?deviceType=;softwareVersion=`, `PUT /api/wake-word/{dsn}` | ✔ (PUT from alexapy, not replayed) |
| Ascending alarm | `GET /api/ascending-alarm`, `PUT /api/ascending-alarm/{dsn}` | ✔ |
| Request start/end sounds | `GET|PUT /api/earcon/states/{type}/{sw}/{dsn}` `{wakeWordEarconEnabled,endOfSpeechEarconEnabled}` | ✔ W |
| AUX port direction / plugged | `GET /api/auxcontroller/{type}/{dsn}/state`, `POST …/ports/{portId}/setDirection` | ✔ (POST unverified) |
| DND schedule | `GET /api/dnd/schedule?deviceType=;deviceSerialNumber=` | ✔ |
| Alarm sounds list / default sound | `GET /api/notification/sounds?…`, `GET /api/notification/default-sound?…notificationType=ALARM` | ✔ |
| Whisper mode (account) | `GET|POST /api/response-modulation-preferences` `{whisperModulationEnabled}` | ✔ W |
| Adaptive volume (account) | `GET|POST /api/adaptive-volume` `{adaptiveVolumeEnabled}` | ✔ W |
| Brief mode (account) | `GET /api/voice-responses` → `promptModes` contains `TERSE` | ✔ read |
| Per-device settings | `GET|PUT /api/v1/devices/{deviceAccountId}/settings/{key}`, PUT body `{"value": <json-encoded string>}` | ✔ W |
| …keys that exist (Echo Show 5) | `timeZone`, `adaptiveListening`, `adaptiveVolume`, `alexaCaptions`, `alexaGestures`, `alexaSpeakingRate`, `alexaVoice`, `deviceNightMode`, `geolocation`, `guardEarcon`, `hunchesEnablement` (+ see `out/keyscan_show.txt`) | ✔ |
| Device locale | `GET /api/device-locale/{dsn}/{type}`, `GET /api/v1/devices/{acct}/availableLocales|availableVoices|availableWakeWords` | ✔ |
| Bluetooth state incl. paired list, streaming state, Echo Buds battery | `GET /api/bluetooth?cached=true` | ✔ |
| Multi-room groups | `GET /api/wholeHomeAudio/v1/groups` | ✔ |
| Media state | `GET /api/media/state?…`, `GET /api/np/player?…` | ✔ |
| Sidewalk, hunches, music providers/defaults, explicit filter | `/api/settings/sidewalk-mode`, `/api/smarthome/v1/hunches/settings`, `/api/music/settings`, `/api/music/defaults`, `/api/settings/music/explicit` | ✔ read |

Auth findings:
- `POST api.amazon.com/auth/token` with the stored `refresh_token` → new `access_token` (✔ 200).
- Registering a *new* device from that access token is refused: `InvalidToken: Auth time of the token is expired` → a fresh registration needs an interactive login.
- The OAuth authorize URL (`www.amazon.com/ap/signin`, `assoc_handle=amzn_dp_project_dee_ios`, PKCE S256) answers `302 → /ax/claim` (✔), so a "log in in your own browser, paste the redirect URL" flow is viable and needs no password storage, no HTML scraping, and supports passkeys/2FA/captcha.

## 4. Gap analysis

| Area | alexa_media_player 5.21 | core alexa_devices | **amazon_echo (this)** |
|---|---|---|---|
| Login | proxy inside HA, password + TOTP stored | scraped forms, TOTP only, password stored | import alexa_media session **or** external-browser PKCE; no password stored |
| Discovery | none | none (exempt) | zeroconf (`_spotify-connect`, `_amzn-wplay`), DHCP registered devices |
| LAN | none | none | IP/MAC, local reachability, Spotify active user, groups — works offline |
| Push | HTTP/2, 11 events, last-called by heuristic | HTTP/2, 6 events | HTTP/2, all known events routed; polling only as fallback |
| Media | play/pause/next/prev/shuffle/repeat, no seek | no shuffle/repeat/seek/source | + forward/rewind, Bluetooth source select, group members |
| Equalizer | lib only | no | 3 numbers |
| Alarm volume | number | no | number |
| Wake word / alarm sound / AUX | no | no | selects |
| Earcons, ascending alarm, whisper, adaptive volume, captions, gestures, adaptive listening | no | no | switches |
| Speaking rate | no | no | number |
| Wi-Fi SSID / IP / MAC | no | no | sensors + device connections |
| Temperature (Echo Plus/Dot) | sensor | sensor | sensor (GraphQL) |
| Fire TV remote battery / ambient mode | no | no | sensor / switch |
| Echo Buds battery | no | no | sensor |
| Alarms/timers/reminders | read + delete alarm | read next only | read all + create/delete services |
| Routines | service | button per routine | button + service |
| Lists | no | todo | todo |
| Voice history | sensor/heuristic | event entity | event entity |
| Reboot | button | button | button |
| Generic escape hatch | no | no | `call_feature` service (GraphQL `setEndpointFeatures`) |

## 5. Design

Repos (house pattern = `ha-hp-printer` + `python-hp-printer`): `~/Github/python-amazon-echo` (PyPI name `python-amazon-echo`, import `amazon_echo`) and
`~/Github/ha-amazon-echo` (domain `amazon_echo`, name "Amazon Echo"). Nothing is pushed/published without the owner's OK.

Scope guard: only Alexa-enabled devices (Echo, Fire TV, tablets, Echo Buds, speaker groups). The 300+ third-party smart-home endpoints of the
account are **not** turned into entities (they already exist in HA through their own integrations; duplicating them was rejected before).
`call_feature` covers the rare need.

## 6. Per-device setting keys (`/api/v1/devices/{deviceAccountId}/settings/{key}`) — scan result

1812 candidate names taken from the app bundle were tried read-only against an Echo Show 5; 22 exist (`out/keyscan_show.txt`):

| Key | Stored | Example value (JSON-decoded) | Entity |
|---|---|---|---|
| `adaptiveListening` | device | `"DISABLED"` / `"ENABLED"` | switch |
| `adaptiveVolume` | cloud | `"DISABLED"` | (account switch already) |
| `alexaCaptions` | device | `"DISABLED"` | switch |
| `alexaGestures` | device | `true` | switch |
| `alexaSpeakingRate` / `speakingRate` | cloud | `1.0` | number |
| `alexaVoice` | cloud | `"pt-BR_FEMALE_2_Plus"` | attribute (choices from `availableVoices`) |
| `deviceNightMode` | device | `{"nightModeEnablement":"ENABLED","nightModeType":"AUTOMATIC","nightModeSchedule":{…}}` | switch (toggle `nightModeEnablement`, keep the rest) |
| `smartMotion` | device | `"ON"` / `"OFF"` | switch |
| `visualGesture` | device | `"DISABLED"` | switch |
| `tapGestures` | device | `{"enablement":"DISABLED","gestureActionsMap":[…]}` | switch (toggle `enablement`) |
| `timeFormat` | device | `"24_HOURS"` / `"12_HOURS"` | select |
| `timeZone` | cloud | `"America/Sao_Paulo"` | sensor |
| `wakeWordSensitivity` | cloud | `0` | number (range not established — treat as −? .. ?; exposed read-only until verified) |
| `wakeWords`, `locales`, `requestedLocales`, `localeAccent` | cloud/device | `["ALEXA"]`, `["pt-BR"]` | attributes |
| `geolocation`, `guardEarcon`, `hunchesEnablement`, `sleepTrackingEnablement` | cloud/device | | diagnostics only |

Keys that exist but the device rejected on this model (`UnifiedPreferenceService` 400): `brightness`, `adaptiveBrightness`, `displayPower`, `motionSensorRange` — likely valid on other Echo Show models; not exposed.

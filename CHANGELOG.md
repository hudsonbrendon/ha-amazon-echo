# Changelog

## 0.3.5 - 2026-11-16

- Requires `python-amazon-echo` 0.3.2: music alarms and alarms Amazon sends without `alarmTime` now have their time, so the next-alarm sensor sees them.

## 0.3.4 - 2026-11-16

- `create_timer` now starts the timer on the Echo (it was started on the integration's own app registration). Alexa confirms it out loud; Portuguese and English devices only. Requires `python-amazon-echo` 0.3.1.
- The voice event and the last called device follow typed requests (`send_text_command`, `create_timer`), for which Amazon pushes nothing.
- The last called device is read again by the slow tier when the startup read failed.

## 0.3.3 - 2026-11-16

- A slow-tier fetch that fails (lists, device settings, communication preferences) is tried again after 5 minutes, up to three times, instead of waiting for the next 3-hour cycle.

## 0.3.2 - 2026-11-16

- Use `async_get_device_by_identifier` instead of the device-registry lookup Home Assistant deprecated.

## 0.3.1 - 2026-11-16

- Slow boots: the entry no longer waits for Alexa Media Player to finish its own setup, and an entry whose setup Home Assistant cancelled at a bootstrap timeout is reloaded once startup is over.

## 0.3.0 - 2026-11-16

Nothing is left in the "missing" list of [COMPARISON.md](COMPARISON.md), and
the claim that this integration has everything Alexa Media Player and the
core Alexa Devices integration have is now checked by a test. Requires
`python-amazon-echo` 0.3.0.

- **Audio files as announcements**: `media_player.play_media` with
  `announce: true` takes an `https://` address, a path of Home Assistant or a
  `media-source://` id (local media, Home Assistant's text-to-speech, so
  `tts.speak` works on an Echo). The file is converted with Home Assistant's
  ffmpeg to what Alexa plays (MP3, 48 kbit/s, 24 kHz), published under
  `/local/amazon_echo/` and spoken. Needs Home Assistant reachable over
  HTTPS; the new option **Public address for audio files** overrides the
  external URL. Converted files are reused and deleted a day after their
  last use. The media player advertises `MEDIA_ANNOUNCE`.
- **Music alarms**: `amazon_echo.create_alarm` takes `alarm_type: music`,
  `music_provider` and `music_entity`, and reuses the station of a music
  alarm that already exists on the account. `get_notifications` returns
  `music_provider` and `music_entity`.
- `play_media`: a music provider id is accepted as the media type (the way
  the other two integrations take it), and `extra: {timer: 600}` stops the
  music after that many seconds.
- Media player attribute `last_message_timestamp`. The next alarm / timer /
  reminder sensors gain `label`, `sub_label`, `recurrence`, `status`,
  `total_active` and `total_all` next to `items`.
- **The superset is verified mechanically.**
  `scripts/extract_competitor_features.py` takes an inventory of both
  competitors from their source (198 features of Alexa Media Player, 104
  features of Alexa Devices), `tests/superset_map.json` maps each one to an
  entity, action, option, event or piece of code of this integration, and
  `tests/test_superset.py` fails when one is unmapped or when a target does
  not exist. The four items above other than the first two are what that
  inventory turned up.

## 0.2.1 - 2026-11-16

- Use `UnitOfDensity` / `UnitOfRatio` instead of the unit constants Home Assistant deprecated (removed in 2027.8).

## 0.2.0 - 2026-11-16

Everything Alexa Media Player 5.21.0 and the core Alexa Devices integration
have is now here; [COMPARISON.md](COMPARISON.md) lists it feature by feature.
Requires `python-amazon-echo` 0.2.0.

- Communication preferences per device: **Drop In** select (all contacts /
  my household / off), **Announcements** and **Communications** switches.
- Sensors read from the device's own endpoint, created for whatever a device
  reports: illuminance, humidity, PM2.5, PM10, carbon monoxide, volatile
  organic compounds, air quality index, and a **Motion** binary sensor.
- **Last called device** sensor on the account device (utterance, response,
  timestamp and person as attributes), a notify entity that speaks on that
  device, and `last_called` attributes on the media players. Without push
  the voice history is read on every poll.
- **Alexa Guard** alarm panel (arm away / disarm) on accounts that have Guard.
- **Echo Glow** as a light (colour, brightness, light shows) and the **Air
  Quality Monitor** (its readings and the indicator light), always added.
- New option **Alexa smart-home devices**, off by default: lights (power,
  brightness, colour, colour temperature, effects), switches, sensors
  (temperature, humidity, battery, illuminance), contact and motion binary
  sensors and locks for the devices linked to Alexa, one device each.
  Entities that Home Assistant itself bridged to Alexa are skipped.
- **Amazon Kids** switch and profile select; Echo Show **Display** and
  **Adaptive brightness** switches and **Display brightness** number;
  **Default device for routines** select.
- Media player: `turn_on` / `turn_off`, `play_media` types `sequence` and
  `image`, more attributes (Bluetooth list, previous volume, last message,
  locale).
- Actions: `send_info_skill`, `send_mobile_push`,
  `send_drop_in_notification`, `send_announcement` (several devices; speak,
  show or both), `enable_alarm`, `disable_alarm`, `skip_next_alarm`,
  `update_last_called`, `restore_volume`, `repeat_last_message`;
  `call_feature` accepts a smart-home device.
- Events on the bus: `amazon_echo_voice_command`, `amazon_echo_last_called`,
  `amazon_echo_notification` (an alarm, timer or reminder goes off) and
  `amazon_echo_alarm_dismissed`.
- Push: smart-home state changes are applied as they arrive; "now playing"
  events refresh the player.
- Diagnostics per device; what was said to Alexa is redacted.
- The time zone sensor now exists for every device (account preferences), the
  voice command event has `person_type`.

## 0.1.2 - 2026-11-16

- The first refresh is bounded to 90 s. With a slow network at boot Home Assistant now retries the entry; before, the global bootstrap timeout cancelled the setup and left the entry in error until a manual reload.

## 0.1.1 - 2026-11-16

- Requires `python-amazon-echo` 0.1.1 (cookie refresh no longer refused within 60 s of boot).
- The LAN is browsed at startup, so local entities appear without waiting for a device announcement.
- The slow settings tier runs in the background instead of during entry setup.

## 0.1.0 - 2026-11-15

First release.

- Config flow without a password: reuse the session of an existing Alexa
  Media Player entry, or sign in to Amazon in your own browser and paste the
  final address. Reauth, reconfigure and options (polling interval, push,
  local probing).
- Discovery: zeroconf (`_spotify-connect` for Echos, `_amzn-wplay` for Fire
  TVs) and DHCP for registered devices, which keeps each device's LAN address
  up to date.
- HTTP/2 push for volume, do not disturb, playback, Bluetooth, alarms,
  lists, connectivity and voice commands; polling is only a fallback (300 s,
  60 s while push is down).
- Local probing every 60 s, independent of the cloud: IP address, local
  reachability and Spotify user keep working when Amazon is unreachable.
- One device per Echo, Echo Show, Fire TV, tablet, Echo Buds and speaker
  group, plus a service device for the account.
- Media player (transport, shuffle, repeat, forward/rewind, Bluetooth source,
  `play_media` for music, routines, sounds, skills, text commands and TTS),
  speak and announce notify entities.
- Switches: do not disturb, ascending alarm, start/end of request sounds,
  adaptive listening, captions, gestures, night mode, smart motion, visual
  gesture, tap gestures, Fire TV ambient mode; whisper mode and adaptive
  volume for the account.
- Numbers: bass, midrange, treble, alarm volume, speaking rate.
- Selects: wake word, alarm sound, AUX direction, time format.
- Sensors: next alarm / timer / reminder (with the full list as attributes),
  temperature, Wi-Fi network, IP address, Bluetooth device, battery, Fire TV
  remote battery, Spotify user, time zone, wake word sensitivity.
- Binary sensors: online, reachable on the local network, AUX cable plugged
  in, charging; real-time updates (push stream) for the account.
- Repair notice when the session is shared with Alexa Media Player (Amazon
  allows one push stream per sign-in): the account is polled instead.
- Buttons: reboot, one per enabled routine. Voice command event entity.
  To-do entity per Alexa list.
- Actions: `send_text_command`, `play_sound`, `run_routine`, `launch_skill`,
  `create_alarm`, `create_timer`, `create_reminder`, `delete_notification`,
  `get_notifications`, `get_voice_history`, `bluetooth_connect`,
  `bluetooth_disconnect`, `call_feature`.
- Diagnostics, icons, English and Brazilian Portuguese translations.

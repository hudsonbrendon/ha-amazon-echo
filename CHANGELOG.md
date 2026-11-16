# Changelog

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

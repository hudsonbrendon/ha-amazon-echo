# Amazon Echo for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/hudsonbrendon/ha-amazon-echo)](https://github.com/hudsonbrendon/ha-amazon-echo/releases)
[![Tests](https://github.com/hudsonbrendon/ha-amazon-echo/actions/workflows/tests.yml/badge.svg)](https://github.com/hudsonbrendon/ha-amazon-echo/actions/workflows/tests.yml)
[![hassfest](https://github.com/hudsonbrendon/ha-amazon-echo/actions/workflows/hassfest.yml/badge.svg)](https://github.com/hudsonbrendon/ha-amazon-echo/actions/workflows/hassfest.yml)
[![Validate](https://github.com/hudsonbrendon/ha-amazon-echo/actions/workflows/validate.yml/badge.svg)](https://github.com/hudsonbrendon/ha-amazon-echo/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/hudsonbrendon/ha-amazon-echo)](LICENSE)

<img src="assets/amazon-echo.png" alt="Amazon Echo" width="96" align="right">

Echo, Echo Show, Fire TV, Fire tablets, Echo Buds and multi-room speaker
groups in Home Assistant, through
[python-amazon-echo](https://github.com/hudsonbrendon/python-amazon-echo).
It does everything the built-in **Alexa Devices** integration and **Alexa
Media Player** do — [COMPARISON.md](COMPARISON.md) walks through both, feature
by feature, with the line of their source where each one lives, and a test
[checks the claim against their code](#how-the-superset-is-verified) — and
adds what neither has:

- **No password in Home Assistant.** Reuse the session Alexa Media Player
  already has, or sign in to Amazon in your own browser (passkeys, two-step
  verification and captchas just work) and paste the address you end on.
- **Push first.** Volume, playback, do not disturb, Bluetooth, alarms,
  lists, connectivity and voice commands arrive over Amazon's HTTP/2 push
  channel as they happen. Polling is only a fallback.
- **Local network awareness.** Echos are discovered on the LAN (zeroconf and
  DHCP). IP address, local reachability and the active Spotify user are read
  from the device itself and keep working when the Alexa cloud is down.
- **Device settings as entities**: equalizer, alarm volume, wake word, alarm
  sound, AUX direction, request sounds, ascending alarm, night mode, captions,
  gestures, speaking rate, time format, whisper mode, adaptive volume, Fire TV
  ambient mode.
- **Media player** with shuffle, repeat, forward/rewind, Bluetooth source
  selection and `play_media` for music, routines, sounds, skills, text
  commands, TTS and audio files (a URL, local media or Home Assistant's own
  text-to-speech, played as an announcement); **speak** and **announce**
  notify entities.
- **Alarms, timers and reminders**: next-occurrence sensors with the full
  list as attributes, plus actions to create and delete them.
- Routines as buttons, Alexa lists as to-do entities, a voice command event
  entity, Wi-Fi network, temperature, batteries, reboot.
- **Everything the other two have**: Drop In, announcements and
  communications per device, the last called device, Amazon Kids, Echo Show
  display settings, illuminance / motion / humidity / air-quality sensors,
  info skills, notifications to the Alexa app, Alexa Guard, Echo Glow and,
  if you ask for it, the smart-home devices linked to Alexa.

An Echo has no local control API: commands always go through Amazon. What is
local is discovery, addressing, reachability and Spotify state.

## Supported devices

Every Alexa-enabled device of the account becomes a device: Echo / Echo Dot
/ Echo Pop / Echo Plus, Echo Show, Fire TV, Fire tablets, Echo Buds and
speaker groups. Alexa app registrations are skipped. Entities are only
created for what each device reports, so an Echo Show gets night mode and
captions, an Echo Plus gets temperature and AUX, a Fire TV gets ambient mode
and remote battery.

Amazon hardware without a microphone — **Echo Glow** and the **Air Quality
Monitor** — is always added too, since nothing else in Home Assistant has it.

### Smart-home devices linked to Alexa (off by default)

The lamps, plugs, sensors and locks of other brands that you linked to Alexa
are **not** imported unless you turn on *Alexa smart-home devices* in the
options. It is off by default because those devices normally already exist
in Home Assistant through their own integrations, and importing them again
would only give you every device twice, slower and through one more cloud.
Turn it on when Alexa is the only way to reach a device (something paired
straight to an Echo over Zigbee, Matter or Bluetooth, or a brand with an
Alexa skill and no Home Assistant integration).

With the option on, every endpoint becomes a device attached to the account
device, with what it reports:

| Platform | Created for | Operations sent to Alexa |
| --- | --- | --- |
| Light | lamps, and anything with power that dims or changes colour | `turnOn`, `turnOff`, `setBrightness`, `setColor`, `setColorTemperature`, `setMode` (light shows) |
| Switch | plugs, wall switches and anything else that only turns on and off | `turnOn`, `turnOff` |
| Sensor | temperature, humidity, battery, illuminance | — |
| Binary sensor | contact (open/closed), motion | — |
| Lock | locks | `lock`, and `unlock` only for the locks where Amazon allows it |

What Home Assistant itself published to Alexa is never taken back: devices
whose manufacturer is a Home Assistant Matter bridge (Home Assistant Matter
Hub, Matterbridge) are skipped, and so are Hue lamps while the Emulated Hue
integration is loaded. Scenes, cameras and thermostats are not turned into
entities; `amazon_echo.call_feature` reaches anything else.

A command is applied to the entity at once and confirmed by push, or by the
next poll when there is no push. Turning the option off removes the devices
again.

## Installation

1. HACS → Integrations → ⋮ → *Custom repositories* → add
   `https://github.com/hudsonbrendon/ha-amazon-echo` as *Integration*.
2. Install **Amazon Echo** and restart Home Assistant.
3. An Echo on your network is discovered automatically (Settings → Devices &
   services). Otherwise *Add integration* → **Amazon Echo**.

### Signing in

One entry is one Amazon account. Two ways to connect it:

- **Reuse the Alexa Media Player session** (offered only when that
  integration is set up): nothing to type. Amazon allows one real-time
  connection per sign-in and the newest one wins, so while Alexa Media Player
  is set up an imported session is polled every 60 s instead of using push,
  and a repair notice says so. Sign in with the browser (*Reconfigure*) or
  remove Alexa Media Player to get real-time updates.
- **Sign in with Amazon in your browser**: open the link shown, sign in to Amazon as
  usual, and when you land on a blank or "page not found" page copy the full
  address from the address bar and paste it into Home Assistant.

Home Assistant stores the device registration (refresh token and cookies),
never your password. When Amazon stops accepting the session a reauth flow
offers the same two methods. *Reconfigure* replaces the session of the same
account.

### Removal

Delete the entry under Settings → Devices & services. An entry signed in
through the browser also takes its registration off the Amazon account
(`auth/deregister`), so nothing is left under *Manage Your Content and
Devices*. If Amazon cannot be reached, a warning is logged and the
registration can be removed there by hand. Sessions imported from Alexa Media
Player are never deregistered: they belong to that integration.

## Options

| Option | Default | Description |
| --- | --- | --- |
| Polling interval | 300 s | Only a fallback while push is connected. With push down the account is polled every 60 s. |
| Receive changes by push | on | The HTTP/2 push channel. |
| Probe devices on the local network | on | IP address, local reachability and Spotify user, every 60 s, without the cloud. |
| Alexa smart-home devices | **off** | Lights, switches, sensors and locks for the smart-home devices linked to Alexa. See above for why it is off. |
| Public address for audio files | empty | The HTTPS address Alexa reaches Home Assistant at, for [audio files played as announcements](#audio-files-as-announcements). Empty uses Home Assistant's external URL. |

## How data is updated

| Tier | When | What |
| --- | --- | --- |
| Push | as it happens | volume, do not disturb, playback, Bluetooth, alarms/timers/reminders, lists, online state, voice commands (and with them the last called device), smart-home and sensor state |
| Fast poll | 300 s (60 s without push) | device list, do not disturb, volumes, Bluetooth, notifications, endpoint states (temperature, illuminance, motion, humidity, air quality, remote battery), smart-home devices, Guard, media of playing devices; without push also the voice history |
| Slow poll | in the background right after startup, every 3 hours and right after a related write | Wi-Fi, equalizer, request sounds, AUX, alarm volume, wake word, alarm sounds, device settings, communication preferences, Amazon Kids, whisper mode, adaptive volume, routines, lists, locale and time zone |
| Local | 60 s | IP address, local reachability, Spotify user |

A setting one device does not support is asked once and then skipped; one
device failing never fails the whole update. The endpoint states and the
smart-home devices come from a single request.

## Entities

Per device (each one only when the device reports it):

| Platform | Entities |
| --- | --- |
| Media player | the device or speaker group |
| Notify | Speak, Announce (with title) |
| Switch | Do not disturb, Communications, Announcements, Amazon Kids, Ascending alarm, Start of request sound, End of request sound, Adaptive listening, Captions, Gestures, Night mode, Smart motion, Visual gesture, Tap gestures, Display, Adaptive brightness, Ambient mode (Fire TV) |
| Number | Bass, Midrange, Treble, Alarm volume, Speaking rate, Display brightness |
| Select | Wake word, Alarm sound, AUX direction, Time format, Drop In (all contacts / my household / off), Amazon Kids profile |
| Sensor | Next alarm, Next timer, Next reminder, Temperature, Humidity, Illuminance, PM2.5, PM10, Carbon monoxide, Volatile organic compounds, Air quality index, Wi-Fi network, IP address, Bluetooth device, Battery, Remote battery, Spotify user, Time zone, Wake word sensitivity |
| Binary sensor | Online, Reachable on the local network, AUX cable plugged in, Charging, Motion |
| Button | Reboot |
| Event | Voice command (`utterance`, `response`, `intent`, `person`, `person_type`) |

On the account device: Whisper mode and Adaptive volume switches, a
Real-time updates binary sensor (is the push stream open), one button
per enabled routine, one to-do entity per Alexa list (Shopping list,
To-do list and your custom lists), and:

- **Last called device** sensor: the name of the device that answered the
  last voice request, with `utterance`, `response`, `timestamp`, `person`
  and `intent` as attributes. It follows the same voice-history read as the
  voice command event (push, or every poll while push is down) and is filled
  at startup from the last week of history without firing events.
- **Speak on the last called device** notify entity: answers wherever you
  were just talking to Alexa.
- **Default device for routines** select: the device that stands in for
  "the device that heard the request" when a routine is started from its
  button. The choice is kept by Home Assistant.
- **Alexa Guard** alarm panel, only on accounts that have Guard: arm away,
  disarm (home).

The media player also carries `last_called`, `last_called_timestamp`,
`last_called_summary`, `last_called_response`, `bluetooth_list`,
`connected_bluetooth`, `previous_volume`, `last_message`,
`last_message_type`, `last_message_timestamp` and `locale` as attributes.
The next alarm / timer / reminder sensors describe the next one (`label`,
`sub_label`, `recurrence`, `status`), count them (`total_active`,
`total_all`) and list them all (`items`).

`media_player.play_media` content types:

| `media_content_type` | `media_content_id` |
| --- | --- |
| `music` | `PROVIDER_ID:search phrase` (for example `SPOTIFY:lo-fi beats`) or just the phrase for your default provider. `extra: {timer: 600}` stops the music after that many seconds |
| a provider id, such as `SPOTIFY` | the search phrase (the way the other two integrations take it) |
| `music` or `audio`, with `announce: true` | an audio file: an `https://` address, a path of Home Assistant such as `/local/bell.mp3`, or a `media-source://` id (local media, text-to-speech). See below |
| `routine` | routine name or id |
| `sound` | sound id, for example `amzn_sfx_doorbell_chime_01` |
| `skill` | skill id |
| `text_command` | what you would say to Alexa |
| `tts` | text to speak (SSML is passed through, so `<audio src="https://…"/>` plays a file in a format Alexa accepts) |
| `sequence` | a behavior node type such as `Alexa.Weather.Play`; `extra` becomes its payload |
| `image` | https address of a picture to show as the background of an Echo Show |

### Audio files as announcements

Alexa cannot be handed a stream. What it can do is play a short MP3 from an
HTTPS address in the middle of what it says, so an audio file is downloaded,
converted with Home Assistant's ffmpeg (MP3, 48 kbit/s, 24 kHz), published
under `/local/amazon_echo/` and spoken:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.kitchen_echo
data:
  media_content_type: music
  media_content_id: media-source://media_source/local/doorbell.wav
  announce: true
```

`tts.speak` works the same way, so any text-to-speech engine of Home
Assistant can talk through an Echo. It needs:

- Home Assistant reachable from the internet over **HTTPS** (Home Assistant
  Cloud, or your own external URL). A different address can be set in the
  options. Without one the action fails with an error that says so.
- The `ffmpeg` integration, which Home Assistant sets up by default.
- A clip of at most 240 seconds: that is where Alexa stops.

The converted files are named after their content, reused when the same
sound is played again and deleted a day after their last use. Anyone who
knows the address of a file can fetch it during that day, like everything
else under `/local`.

## Actions

Every action takes `device_id`: an Echo, or the account device where noted.

| Action | Fields | Response |
| --- | --- | --- |
| `amazon_echo.send_text_command` | `text` | — |
| `amazon_echo.play_sound` | `sound` | — |
| `amazon_echo.run_routine` | `routine` (name or id); account device = the routine's own device | — |
| `amazon_echo.create_routine` | `name`, `phrases` ("when you say"), `actions`, `enabled`; device or account | `routine_id`, `name` |
| `amazon_echo.update_routine` | `routine` (name or id) and any of `name`, `phrases`, `actions` (replace all), `enabled`, `replace_devices` (old → new); device or account | — |
| `amazon_echo.delete_routine` | `routine` (name or id); device or account | — |
| `amazon_echo.launch_skill` | `skill_id` | — |
| `amazon_echo.create_alarm` | `time`, `recurrence` (`DAILY`, `WEEKDAYS`, `WEEKENDS`, `WEEKLY`, `MO,WE,FR`); for a music alarm `alarm_type: music`, `music_provider`, `music_entity` | the alarm |
| `amazon_echo.create_timer` | `duration`, `label` | the timer (Alexa confirms it out loud) |
| `amazon_echo.create_reminder` | `time`, `label` | the reminder |
| `amazon_echo.delete_notification` | `notification_id` | — |
| `amazon_echo.get_notifications` | device or account | `notifications` (with `music_provider` and `music_entity` for music alarms) |
| `amazon_echo.get_voice_history` | `limit`; device or account | `records` |
| `amazon_echo.bluetooth_connect` | `address` (name or MAC of a paired device) | — |
| `amazon_echo.bluetooth_disconnect` | | — |
| `amazon_echo.call_feature` | `feature`, `operation`, `endpoint_id`, `instance`, `payload`; a smart-home device can be picked directly | — |
| `amazon_echo.send_info_skill` | `skill`: `weather`, `traffic`, `flash_briefing`, `national_news`, `good_morning`, `good_night`, `im_home`, `fun_fact`, `joke`, `tell_story`, `sing_a_song`, `clean_up`, `date`, `time`, `calendar_today`, `calendar_tomorrow`, `calendar_next` | — |
| `amazon_echo.send_mobile_push` | `message`, `title`; device or account. Goes to the Alexa app on your phones | — |
| `amazon_echo.send_drop_in_notification` | `message`, `title`; an Alexa app notification that opens Drop In | — |
| `amazon_echo.send_announcement` | `device_id` (several), `message`, `title`, `method` (`all`, `speak`, `show`) | — |
| `amazon_echo.enable_alarm` / `disable_alarm` / `skip_next_alarm` | `notification_id` | — |
| `amazon_echo.update_last_called` | device or account | — |
| `amazon_echo.restore_volume` | sets the device back to the volume it had before its last change | — |
| `amazon_echo.repeat_last_message` | repeats the last speak or announce Home Assistant sent to the device | — |

Routine actions run in order. Each one is `{device, action, value}`, where
`action` is `turn_on`, `turn_off`, `brightness` (0–100), `color` (a name such
as `blue`) or `temperature` (°C) and `device` is the device's name in the
Alexa app, any Home Assistant entity (matched to the Alexa device of the same
name) or an endpoint id; or
`{device, operations}` with the routine editor's own operations; or
`{speak: text}` (the Echo that heard the phrase says it); or a raw routine
node. `replace_devices` repairs routines after a device was replaced: every
action on the old device moves to the new one, the rest stays as it was.

```yaml
action: amazon_echo.create_routine
data:
  device_id: <account device>
  name: Modo leitura
  phrases: ["modo leitura"]
  actions:
    - {device: Lâmpada 1 da sala, action: brightness, value: 40}
    - {device: light.abajur_da_sala, action: turn_off}
    - {speak: Boa leitura}
```

Example: repeat on the office Echo Show what was said to the kitchen Echo.

```yaml
automation:
  - alias: Announce the voice command in the office
    triggers:
      - trigger: state
        entity_id: event.kitchen_echo_voice_command
    actions:
      - action: notify.send_message
        target:
          entity_id: notify.office_show_announce
        data:
          title: Kitchen
          message: "{{ trigger.to_state.attributes.utterance }}"
```

## Events

Besides the voice command event entity, these are fired on the event bus:

| Event | When | Data |
| --- | --- | --- |
| `amazon_echo_voice_command` | a device heard a voice request | `device_id`, `serial`, `name`, `timestamp`, `utterance`, `response`, `intent`, `person` |
| `amazon_echo_last_called` | a different device became the last called one | same as above |
| `amazon_echo_notification` | an alarm, timer or reminder goes off (its scheduled time) | `id`, `kind`, `status`, `label`, `when`, `recurrence`, `sound`, `device_id`, `name` |
| `amazon_echo_alarm_dismissed` | an alarm that was ringing or snoozed was dismissed | same as above |

```yaml
automation:
  - alias: Turn the lights on when the bedroom alarm is dismissed
    triggers:
      - trigger: event
        event_type: amazon_echo_alarm_dismissed
        event_data:
          name: Bedroom Echo
    actions:
      - action: light.turn_on
        target:
          entity_id: light.bedroom
```

## Diagnostics

Settings → Devices & services → Amazon Echo → ⋮ → *Download diagnostics*.
Tokens, cookies, e-mail, account name, serial numbers, MAC and IP addresses,
Wi-Fi name, Bluetooth addresses and what was said to Alexa are redacted;
devices appear as `device_0`, `device_1`..., smart-home devices as
`endpoint_0`... A device page has its own *Download diagnostics* with only
that device.

## Known limitations

- Commands need the Alexa cloud. Only discovery, IP address, reachability and
  Spotify user are local.
- Alexa cannot seek to a position: `media_seek` skips forward or back, and is
  only offered when the player allows it.
- There is no mute command: muting sets the volume to zero and unmuting
  restores the previous volume.
- Repeat is on/off; "repeat one" is treated as on.
- **Speaking rate** is offered from 0.75 to 2.0 in steps of 0.05. The range
  Amazon accepts was not established; a value it refuses raises an error.
- **Wake word sensitivity** is read-only until its range is known.
- **Ambient mode** (Fire TV) was verified live on a Fire TV Stick 4K Max (the
  ambient screen opens and closes). Amazon never reports whether it is on, so
  the switch shows the last value it sent (assumed state).
- Music with no provider prefix uses the provider id `DEFAULT`.
- `create_timer` is spoken: Amazon has no API to start a timer on an Echo, so the
  integration types the request with the duration in words and Alexa confirms it
  out loud. It works on devices set to Portuguese or English (verified live in
  pt-BR); other languages get a translated error.
- **Music alarms** can only reuse a station. Amazon has no public search for
  one, so `create_alarm` with `alarm_type: music` looks for an existing music
  alarm of the account with that `music_provider` and `music_entity` (create
  it once in the Alexa app; `get_notifications` shows both values) and makes
  a new alarm with the same station. This is how Alexa Media Player does it.
  Verified live on 2026-11-16: a music alarm made by voice (Spotify) was
  reused to create one on an Echo Plus at the requested date and time.
- **Audio files as announcements** were run live on 2026-11-16: a Home
  Assistant text-to-speech file was transcoded by ffmpeg to MP3 (48 kbps,
  24 kHz), published under `/local/amazon_echo`, reachable through the
  external HTTPS address, and the Echo Plus recorded the request in its voice
  history. Whether it was heard was not confirmed by a person. The music sleep
  timer (`extra.timer`) was verified live with Spotify: the music stops by
  itself, but Amazon does not honour the exact second (25 s asked → 26 s,
  20 s asked → about 38 s).
- Alarm and reminder times are read by Amazon in the Echo's own time zone;
  the integration assumes it is the time zone of Home Assistant.
- A routine button runs the routine without a target device, so routines
  that act on "the device that heard the request" need the
  `amazon_echo.run_routine` action with a device.
- A device that leaves the account and comes back gets its entities again on
  the next reload.
- **Communication preferences** (Drop In, Announcements, Communications) come
  from an Amazon service that answers HTTP 503 most of the time for some
  accounts (about nine requests in ten on the test account). Reading and
  writing them was verified live; when the read fails for a device the three
  entities are not created yet, and it is asked again after 5 minutes (up to
  three times), then every three hours.
- **Alexa Guard** follows what Alexa Media Player does and was not run against
  a real Guard: the test account has none. Amazon retired the free Guard in
  most countries.
- **Smart-home devices**: the state is what Amazon last heard from the
  device's own cloud, so it can lag; without push it is corrected by the next
  poll. Colour temperature is offered from 2200 K to 6500 K. Power,
  brightness, colour, colour temperature and mode were verified live on Tuya
  lamps linked to Alexa; locking and unlocking were not sent to a real lock.
- **Amazon Kids**: reading the profiles and the device state was verified;
  switching a device was not. A new child profile is noticed within three
  hours.
- **Info skills** were verified live (the "time" skill answered on an Echo
  Plus). **Notifications to the Alexa app** were verified live. They only
  arrive when the phone allows the Alexa app to show notifications: before
  that, Amazon accepted every request and nothing reached the phone.
  **Echo Show background image** does not work any more: Amazon accepts the
  request and keeps its own background (tried live on an Echo Show 5).
- Deleting voice history is not offered: the endpoint the other integrations'
  libraries have for it (`/api/activities`) no longer exists.
- This integration uses Amazon's private app API, which can change without
  notice.

## Troubleshooting

Enable debug logging under the integration's menu (it covers
`custom_components.amazon_echo` and `amazon_echo`) and download the
diagnostics file. If changes arrive late, look at the **Real-time updates**
binary sensor of the account device: it is off while the push stream is
closed (option turned off, session shared with Alexa Media Player, or Amazon
unreachable) and the account is then polled every 60 s. Also check that the
entry is not asking to sign in again.

## Development

```bash
uv venv --python 3.14 .venv && uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pytest
.venv/bin/ruff check .
```

Test fixtures are invented devices; nothing in this repository comes from a
real account.

### How the superset is verified

"Everything the other two have" is checked by a test, not only written down.

1. `scripts/extract_competitor_features.py` reads the source of Alexa Media
   Player and of the core Alexa Devices integration (and the push handling of
   their libraries) without importing or running any of it, and writes what
   they offer to `tests/fixtures/competitor_features.json`: platforms,
   entities, state attributes, actions and their fields, notify types,
   events, feature flags, `play_media` types, options, config-flow entry
   points, diagnostics and push commands, each with the file and line it was
   found at. For the versions compared that is **198 features** of Alexa
   Media Player and **104 features** of Alexa Devices.
2. `tests/superset_map.json` says, for every one of them, what amazon_echo
   has for it: an entity, an action (and field), a feature flag, an option,
   an event, a push command or a named piece of code.
3. `tests/test_superset.py` fails when a feature of the fixture has no entry
   in the map, and when an entry points at something that is not there: an
   entity must be in `strings.json` and in a description of its platform
   file, an action in `services.yaml` and registered, a field in the action's
   schema, an option in the options flow.

Of the 302, 9 are marked not applicable — a stored password, a debug toggle,
the settings of the other integration's own login proxy and command queue —
each with its reason, and the test does not let that number grow. Six more
are entities the core integration deletes itself.

To check against newer versions of the other two, clone them and run:

```bash
python scripts/extract_competitor_features.py path/to/src-amp path/to/src-core
.venv/bin/pytest tests/test_superset.py
```

(`src-amp` holds `alexa_media_player` and `alexapy`, `src-core` holds `core`
and `aioamazondevices`.) Whatever is new shows up as a failing test.

## License

MIT

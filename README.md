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
Media Player** do, and adds what neither has:

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
  commands and TTS; **speak** and **announce** notify entities.
- **Alarms, timers and reminders**: next-occurrence sensors with the full
  list as attributes, plus actions to create and delete them.
- Routines as buttons, Alexa lists as to-do entities, a voice command event
  entity, Wi-Fi network, temperature, batteries, reboot.

An Echo has no local control API: commands always go through Amazon. What is
local is discovery, addressing, reachability and Spotify state.

## Supported devices

Every Alexa-enabled device of the account becomes a device: Echo / Echo Dot
/ Echo Pop / Echo Plus, Echo Show, Fire TV, Fire tablets, Echo Buds and
speaker groups. Alexa app registrations are skipped. Entities are only
created for what each device reports, so an Echo Show gets night mode and
captions, an Echo Plus gets temperature and AUX, a Fire TV gets ambient mode
and remote battery.

The smart-home devices linked to your Alexa account (lamps, plugs, cameras)
are **not** imported: they already exist in Home Assistant through their own
integrations. The `amazon_echo.call_feature` action covers the rare case
where you need one.

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

Delete the entry under Settings → Devices & services. To also remove the
registration from Amazon (browser sign-in only), remove "Amazon Echo for
Home Assistant" under *Manage Your Content and Devices* on the Amazon site.

## Options

| Option | Default | Description |
| --- | --- | --- |
| Polling interval | 300 s | Only a fallback while push is connected. With push down the account is polled every 60 s. |
| Receive changes by push | on | The HTTP/2 push channel. |
| Probe devices on the local network | on | IP address, local reachability and Spotify user, every 60 s, without the cloud. |

## How data is updated

| Tier | When | What |
| --- | --- | --- |
| Push | as it happens | volume, do not disturb, playback, Bluetooth, alarms/timers/reminders, lists, online state, voice commands |
| Fast poll | 300 s (60 s without push) | device list, do not disturb, volumes, Bluetooth, notifications, endpoint states (temperature, remote battery), media of playing devices |
| Slow poll | in the background right after startup, every 3 hours and right after a related write | Wi-Fi, equalizer, request sounds, AUX, alarm volume, wake word, alarm sounds, device settings, whisper mode, adaptive volume, routines, lists |
| Local | 60 s | IP address, local reachability, Spotify user |

A setting one device does not support is asked once and then skipped; one
device failing never fails the whole update.

## Entities

Per device (each one only when the device reports it):

| Platform | Entities |
| --- | --- |
| Media player | the device or speaker group |
| Notify | Speak, Announce (with title) |
| Switch | Do not disturb, Ascending alarm, Start of request sound, End of request sound, Adaptive listening, Captions, Gestures, Night mode, Smart motion, Visual gesture, Tap gestures, Ambient mode (Fire TV) |
| Number | Bass, Midrange, Treble, Alarm volume, Speaking rate |
| Select | Wake word, Alarm sound, AUX direction, Time format |
| Sensor | Next alarm, Next timer, Next reminder, Temperature, Wi-Fi network, IP address, Bluetooth device, Battery, Remote battery, Spotify user, Time zone, Wake word sensitivity |
| Binary sensor | Online, Reachable on the local network, AUX cable plugged in, Charging |
| Button | Reboot |
| Event | Voice command (`utterance`, `response`, `intent`, `person`) |

On the account device: Whisper mode and Adaptive volume switches, a
Real-time updates binary sensor (is the push stream open), one button
per enabled routine and one to-do entity per Alexa list (Shopping list,
To-do list and your custom lists).

`media_player.play_media` content types:

| `media_content_type` | `media_content_id` |
| --- | --- |
| `music` | `PROVIDER_ID:search phrase` (for example `SPOTIFY:lo-fi beats`) or just the phrase for your default provider |
| `routine` | routine name or id |
| `sound` | sound id, for example `amzn_sfx_doorbell_chime_01` |
| `skill` | skill id |
| `text_command` | what you would say to Alexa |
| `tts` | text to speak |

## Actions

Every action takes `device_id`: an Echo, or the account device where noted.

| Action | Fields | Response |
| --- | --- | --- |
| `amazon_echo.send_text_command` | `text` | — |
| `amazon_echo.play_sound` | `sound` | — |
| `amazon_echo.run_routine` | `routine` (name or id); account device = the routine's own device | — |
| `amazon_echo.launch_skill` | `skill_id` | — |
| `amazon_echo.create_alarm` | `time`, `recurrence` (`DAILY`, `WEEKDAYS`, `WEEKENDS`, `WEEKLY`, `MO,WE,FR`) | the alarm |
| `amazon_echo.create_timer` | `duration`, `label` | the timer |
| `amazon_echo.create_reminder` | `time`, `label` | the reminder |
| `amazon_echo.delete_notification` | `notification_id` | — |
| `amazon_echo.get_notifications` | device or account | `notifications` |
| `amazon_echo.get_voice_history` | `limit`; device or account | `records` |
| `amazon_echo.bluetooth_connect` | `address` (name or MAC of a paired device) | — |
| `amazon_echo.bluetooth_disconnect` | | — |
| `amazon_echo.call_feature` | `feature`, `operation`, `endpoint_id`, `instance`, `payload` | — |

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

## Diagnostics

Settings → Devices & services → Amazon Echo → ⋮ → *Download diagnostics*.
Tokens, cookies, e-mail, account name, serial numbers, MAC and IP addresses,
Wi-Fi name and Bluetooth addresses are redacted; devices appear as
`device_0`, `device_1`...

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
- **Ambient mode** (Fire TV) is written through the generic endpoint feature
  call and was not verified on a real device.
- Music with no provider prefix uses the provider id `DEFAULT`.
- `create_timer` uses an endpoint inferred from the Alexa app and was not
  verified live. Alarms have no label on Amazon's side.
- Alarm and reminder times are read by Amazon in the Echo's own time zone;
  the integration assumes it is the time zone of Home Assistant.
- A routine button runs the routine without a target device, so routines
  that act on "the device that heard the request" need the
  `amazon_echo.run_routine` action with a device.
- A device that leaves the account and comes back gets its entities again on
  the next reload.
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

## License

MIT

# Amazon Echo compared with Alexa Media Player and Alexa Devices

The claim of this integration is that it does everything the two existing
Alexa integrations for Home Assistant do, and more. This file is the proof:
one row per feature, built by reading the source of all three.

| | Version read | Where the citations point |
| --- | --- | --- |
| **AMP** — Alexa Media Player (HACS) | 5.21.0, commit `b7b6c72` (2026-11-15) | `AMP file:line` = `custom_components/alexa_media/file`; `apy file:line` = its library `alexapy/file` (dev `7c4d3b0`) |
| **Core** — Alexa Devices (Home Assistant core) | `dev` at `016643d` (2026-11) | `core file:line` = `homeassistant/components/alexa_devices/file`; `aio file:line` = its library `aioamazondevices` 17.2.12, `src/aioamazondevices/file` |
| **amazon_echo** — this integration | 0.2.0 | files in `custom_components/amazon_echo/`; an entity is named by its translation key, `entity.<platform>.<key>`, an action as `amazon_echo.<name>` |

How to read it: a cell with a citation means the feature is there, at that
line; "—" means it is not; plain words say how the same thing is reached
another way. `tests/test_comparison.py` fails if this file
names an entity key, an action or a source file of amazon_echo that does not
exist, or if amazon_echo gains an entity key or an action that is not listed
here — so the last column cannot drift from the code.

The two lists that matter are at the end: [Only in amazon_echo](#only-in-amazon_echo)
and [In a competitor but not in amazon_echo](#in-a-competitor-but-not-in-amazon_echo).

## Authentication

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Sign in | Amazon's login page proxied through Home Assistant (`AMP config_flow.py:383`), device registration `apy alexalogin.py:1408` | e-mail and password typed into Home Assistant, Amazon's HTML forms scraped (`core config_flow.py:102`, `aio login.py:88`) | sign in to Amazon in your own browser and paste the final address, or reuse the AMP session: `config_flow.py` |
| Password kept by Home Assistant | yes, in the config entry (`AMP config_flow.py:475`) | yes, in the config entry (`core config_flow.py:157`) | no: only the device registration (refresh token, cookies) |
| Two-step verification | TOTP key stored and filled in for you; anything else by hand in the proxied page (`AMP config_flow.py:656`) | a TOTP code is mandatory, nothing else is handled (`aio login.py:331`) | whatever Amazon asks in your browser: passkey, TOTP, SMS, approval, captcha |
| Session kept alive | token refresh and cookie exchange (`apy alexalogin.py:1895`) | token refresh every poll, cookies never renewed (`aio login.py:471`) | token refresh, one cookie exchange on 401/403, saved through `__init__.py` |
| Reauthentication flow | `AMP config_flow.py:688` | `core config_flow.py:160` | `config_flow.py` (same two sign-in methods) |
| Reconfigure (replace the session) | — | `core config_flow.py:205` (new password) | `config_flow.py` |
| Several Amazon accounts | one entry per account (`AMP config_flow.py:168`) | one entry per account (`core config_flow.py:152`) | one entry per account: `config_flow.py` |
| Import of another integration's session | — | — | the Alexa Media Player session: `config_flow.py` |

## Discovery

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Devices found on the network | — (`AMP manifest.json:8`, no discovery keys) | — (`core manifest.json:13`, discovery exempt) | zeroconf (`_spotify-connect` for Echos, `_amzn-wplay` for Fire TVs) and DHCP: `manifest.json`, `config_flow.py` |
| Startup browse of the LAN | — | — | `coordinator.py` |
| New devices of the account | noticed by push, then a refresh (`AMP __init__.py:3048`) | daily device list (`aio api.py:273`) | every poll, entities added without a reload: `entity.py` |
| Devices that left the account | removed (`AMP __init__.py:1572`) | removed (`core coordinator.py:291`) | removed from the registry: `coordinator.py` |

## Local network

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| IP address of a device | — | — | `entity.sensor.ip_address` |
| Reachability on the LAN, independent of the cloud | — | — | `entity.binary_sensor.local_reachable` |
| Active Spotify user | — | — | `entity.sensor.spotify_user` |
| MAC address in the device registry | — | — | `entity.py` |
| Works while the Alexa cloud is down | — | — | the local entities stay available: `entity.py` |

## How data is updated

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Push channel (HTTP/2) | `apy alexahttp2.py:43` | `core __init__.py:83`, `aio implementation/http2.py:108` | `coordinator.py` |
| Polling interval | 60 s, ×10 while push is up (`AMP const.py:87`) | 300 s fixed (`core coordinator.py:47`) | 300 s, 60 s while push is down, configurable: `coordinator.py` |
| Push reconnect with back-off | gives up after 5 errors (`AMP __init__.py:3073`) | 5·2ⁿ s up to 600 s (`aio implementation/http2.py:263`) | 5·2ⁿ s up to 600 s, never gives up |
| "Is push connected" entity | — | — | `entity.binary_sensor.push_connected` |
| Repair notice when push cannot work | — | — | shared AMP session: `coordinator.py` |
| Settings tier that does not slow the poll down | — | — | slow tier every 3 h: `coordinator.py` |

## Push events handled

| Event | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| `PUSH_VOLUME_CHANGE` | `AMP __init__.py:2824` | `aio api.py:465` | applied in place: `coordinator.py` |
| `PUSH_AUDIO_PLAYER_STATE` | `AMP __init__.py:2801` | `aio api.py:470` | state in place, metadata re-read |
| `PUSH_MEDIA_CHANGE`, `PUSH_MEDIA_PROGRESS_CHANGE` | `AMP __init__.py:2802` | — (ignored, `aio structures.py:186`) | media re-read |
| `PUSH_MEDIA_QUEUE_CHANGE` | `AMP __init__.py:2935` | — | media re-read |
| `NotifyMediaSessionsUpdated`, `NotifyNowPlayingUpdated` | `AMP __init__.py:2804` | — (ignored, `aio structures.py:190`) | media re-read |
| `PUSH_CONTENT_FOCUS_CHANGE` | — (ignored, `AMP __init__.py:2984`) | — | media re-read |
| `PUSH_DND_STATE_CHANGE` | — (a volume/equalizer heuristic instead, `AMP __init__.py:3030`) | `aio api.py:474` | applied in place |
| `PUSH_DOPPLER_CONNECTION_CHANGE` | `AMP __init__.py:2850` | — (ignored, `aio structures.py:175`) | online state in place |
| `PUSH_BLUETOOTH_STATE_CHANGE` | `AMP __init__.py:2892` | — (ignored, `aio structures.py:176`) | Bluetooth re-read |
| `PUSH_NOTIFICATION_CHANGE` | `AMP __init__.py:2948` | — (ignored, `aio structures.py:180`) | alarms, timers and reminders re-read |
| `PUSH_EQUALIZER_STATE_CHANGE` | only as a hint that someone spoke (`AMP __init__.py:2863`) | only as a hint that someone spoke (`aio api.py:468`) | equalizer bands in place, and voice history read |
| `PUSH_ACTIVITY` | — | — (ignored, `aio structures.py:174`) | voice history read |
| `PUSH_LIST_ITEM_CHANGE`, `PUSH_LIST_CHANGE` | — (ignored, `AMP __init__.py:2976`) | item changes (`aio api.py:472`) | lists re-read |
| Smart-home state (`EventBus:AlexaMobile::FDAL`) | — | `aio api.py:476` | applied in place, for Alexa devices and smart-home devices |
| Anything else | logged | logged | logged, never dropped |

## Entities

### Media player

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| One player per device | `AMP media_player.py:233` | `core media_player.py:73` | `media_player.py` |
| Speaker groups as players | `AMP media_player.py:264` | speaker groups are devices (`aio const/devices.py:14`) | `media_player.py` (members and groups as attributes) |
| Play, pause, stop, next, previous | `AMP media_player.py:67` | `core media_player.py:110` | `media_player.py` |
| Volume set, step, mute | `AMP media_player.py:1541` | `core media_player.py:31` | `media_player.py` |
| Shuffle, repeat | `AMP media_player.py:1498` | — | `media_player.py` |
| Seek | advertised, no handler (`AMP media_player.py:69`) | — | forward / rewind: `media_player.py` |
| Turn on, turn off | `AMP media_player.py:1720` | — | `media_player.py` |
| Bluetooth source selection | `AMP media_player.py:1073` | — | `media_player.py` |
| Title, artist, album, art, position | `AMP media_player.py:1168` | `core media_player.py:73` | `media_player.py`, plus the music provider |
| `play_media`: music by provider and search phrase | `AMP media_player.py:1942` (any other type) | `core media_player.py:216` | `music`: `media_player.py` |
| `play_media`: routine | `AMP media_player.py:1983` | — | `routine` |
| `play_media`: sound | `AMP media_player.py:2003` | — | `sound` |
| `play_media`: skill | `AMP media_player.py:2027` | — | `skill` |
| `play_media`: text command | `AMP media_player.py:2058` (`custom`) | — | `text_command` |
| `play_media`: any sequence node type | `AMP media_player.py:1959` | — | `sequence` |
| `play_media`: Echo Show background image | `AMP media_player.py:2047` | — | `image` |
| `play_media`: speak a text | through notify | through notify | `tts` |
| `play_media`: audio file as an announcement | `AMP media_player.py:1951` (downloads, transcodes with ffmpeg, serves from a public URL) | — | **no transcoding**, see the last section |
| Attributes: last called, timestamp, summary, response | `AMP media_player.py:2129` | — | `last_called`, `last_called_timestamp`, `last_called_summary`, `last_called_response` |
| Attributes: Bluetooth list and connected device | `AMP media_player.py:2122` | — | `bluetooth_list`, `connected_bluetooth` |
| Attributes: previous volume, last message, locale | `AMP media_player.py:2127` | — | `previous_volume`, `last_message`, `last_message_type`, `locale` |

### Notify

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Speak on a device | `AMP notify.py:301` (`type: tts`) | `core notify.py:38` | `entity.notify.speak` |
| Announce with a chime and a title | `AMP notify.py:317` (`type: announce`) | `core notify.py:47` | `entity.notify.announce` |
| Announce on a speaker group | targets expanded (`AMP notify.py:213`) | members of the group (`aio implementation/sequence.py:185`) | `entity.notify.announce` on the group |
| One announcement for several devices | `AMP notify.py:317` | — | `amazon_echo.send_announcement` |
| Announce spoken only / shown only | `data.method` (`AMP notify.py:317`) | — | `amazon_echo.send_announcement`, `method` |
| Speak on the last called device | `notify.alexa_media_last_called` (`AMP notify.py:181`) | — | `entity.notify.speak_last_called` |
| Notification to the Alexa app | `AMP notify.py:354` (`type: push`), `apy alexaapi.py:1210` | — | `amazon_echo.send_mobile_push` |
| Drop In notification to the Alexa app | `AMP notify.py:369`, `apy alexaapi.py:1249` | — | `amazon_echo.send_drop_in_notification` |

### Switch

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Do not disturb | `AMP switch.py:412` | `core switch.py:72` | `entity.switch.do_not_disturb` |
| Announcements allowed | — | `core switch.py:89` | `entity.switch.announcements` |
| Communications allowed | — | `core switch.py:104` | `entity.switch.communications` |
| Amazon Kids | `AMP switch.py:572` | — | `entity.switch.amazon_kids` |
| Echo Show display on/off | `AMP display.py:254` | — | `entity.switch.display_power` |
| Echo Show adaptive brightness | `AMP display.py:296` | — | `entity.switch.adaptive_brightness` |
| Air Quality Monitor indicator light | — | `core switch.py:119` | `entity.switch.aqm_led` |
| Smart plugs and wall switches | `AMP switch.py:487` (Echo-hub devices only, opt-in) | — | `switch.py` (main entity of the device, opt-in) |
| Shuffle, repeat as switches | `AMP switch.py:455`, `AMP switch.py:471` | — | on the media player, see the last section |
| Ascending alarm | — | — | `entity.switch.ascending_alarm` |
| Start / end of request sounds | — | — | `entity.switch.wake_word_sound`, `entity.switch.end_of_request_sound` |
| Fire TV ambient mode | — | — | `entity.switch.ambient_mode` |
| Adaptive listening, captions, gestures, night mode | — | — | `entity.switch.adaptive_listening`, `entity.switch.captions`, `entity.switch.gestures`, `entity.switch.night_mode` |
| Smart motion, visual gesture, tap gestures | — | — | `entity.switch.smart_motion`, `entity.switch.visual_gesture`, `entity.switch.tap_gestures` |
| Whisper mode, adaptive volume (account) | — | — | `entity.switch.whisper_mode`, `entity.switch.adaptive_volume` |

### Select

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Drop In: all / home / off | — | `core select.py:32` | `entity.select.drop_in` |
| Default device for routines | — | `core select.py:46` | `entity.select.default_device` |
| Amazon Kids child profile | `AMP select.py:85` | — | `entity.select.amazon_kids_profile` |
| Wake word | — | — | `entity.select.wake_word` |
| Alarm sound | — | — | `entity.select.alarm_sound` |
| AUX direction | — | — | `entity.select.aux_direction` |
| Time format | — | — | `entity.select.time_format` |

### Number

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Alarm and timer volume | `AMP number.py:97` | — | `entity.number.alarm_volume` |
| Echo Show display brightness | `AMP display.py:338` | — | `entity.number.display_brightness` |
| Equalizer: bass, midrange, treble | — | — | `entity.number.bass`, `entity.number.mid`, `entity.number.treble` |
| Speaking rate | — | — | `entity.number.speaking_rate` |

### Sensor

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Next alarm | `AMP sensor.py:1185` | `core sensor.py:127` | `entity.sensor.next_alarm` (all alarms as attributes) |
| Next timer | `AMP sensor.py:1205` | `core sensor.py:137` | `entity.sensor.next_timer` |
| Next reminder | `AMP sensor.py:1268` | `core sensor.py:132` | `entity.sensor.next_reminder` |
| Temperature | `AMP sensor.py:340` | `core sensor.py:72` | `entity.sensor.temperature` |
| Illuminance | — | `core sensor.py:83` | `entity.sensor.illuminance` |
| Humidity | `AMP sensor.py:464` (Air Quality Monitor) | `core sensor.py:89` | `entity.sensor.humidity` |
| PM2.5 | `AMP sensor.py:464` | `core sensor.py:101` | `entity.sensor.pm25` |
| PM10 | `AMP sensor.py:464` | `core sensor.py:95` | `entity.sensor.pm10` |
| Carbon monoxide | `AMP sensor.py:464` | `core sensor.py:107` | `entity.sensor.co` |
| Volatile organic compounds | `AMP sensor.py:464` | `core sensor.py:113` | `entity.sensor.voc` |
| Air quality index | `AMP sensor.py:464` | `core sensor.py:119` | `entity.sensor.air_quality` |
| Last called device | attribute and event only (`AMP media_player.py:2129`) | — | `entity.sensor.last_called` |
| Battery (Echo Buds, smart-home sensors and locks) | — | — | `entity.sensor.battery` |
| Fire TV remote battery | — | — | `entity.sensor.remote_battery` |
| Wi-Fi network | — | — | `entity.sensor.wifi_ssid` |
| Connected Bluetooth device | attribute (`AMP media_player.py:2122`) | — | `entity.sensor.bluetooth_device` |
| Time zone | — | — | `entity.sensor.time_zone` |
| Wake word sensitivity | — | — | `entity.sensor.wake_word_sensitivity` |

### Binary sensor

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Online | availability of the player (`AMP media_player.py:1198`) | `core binary_sensor.py:39` | `entity.binary_sensor.online` |
| Motion | — | `core binary_sensor.py:45` | `entity.binary_sensor.motion` |
| Contact sensors linked to Alexa | `AMP binary_sensor.py:115` (Echo-hub devices only, opt-in) | — | `entity.binary_sensor.contact` (opt-in) |
| Amazon Kids active | `AMP binary_sensor.py:160` | — | state of `entity.switch.amazon_kids` |
| AUX cable plugged in | — | — | `entity.binary_sensor.aux_plugged` |
| Charging | — | — | `entity.binary_sensor.charging` |

### Button, event, to-do

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Restart a device | `AMP button.py:90` | `core button.py:33` | `entity.button.reboot` |
| One button per routine | — | `core button.py:78` | `entity.button.routine` |
| Voice command event entity | — | `core event.py:24` | `entity.event.voice` |
| Event attributes: intent, command, reply, person, person type | — | `core event.py:111` | `intent`, `utterance`, `response`, `person`, `person_type` |
| Alexa lists as to-do lists | — | `core todo.py:59` | `entity.todo.shopping_list`, `entity.todo.todo_list`, `entity.todo.list` |

### Light, lock, alarm panel

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Echo Glow: on/off, brightness, colour, light shows | — | `core light.py:55` | `light.py` (always added) |
| Lamps linked to Alexa: on/off, brightness | `AMP light.py:127` (Echo-hub devices only, opt-in) | — | `light.py` (opt-in) |
| Lamp colour | nearest of 140 named colours (`AMP light.py:286`) | — | hue and saturation as given: `light.py` |
| Lamp colour temperature | named temperatures, 2200–6500 K (`AMP light.py:286`) | — | kelvin as given, 2200–6500 K: `light.py` |
| Lamp effects | — | Echo Glow only | any lamp with a mode feature: `light.py` |
| Loop guard for what Home Assistant bridged to Alexa | Emulated Hue, Matter bridges (`AMP alexa_entity.py:68`) | — | Emulated Hue, Matter bridges: `coordinator.py` |
| Locks linked to Alexa | — | — | `lock.py` (opt-in) |
| Alexa Guard: arm away, disarm | `AMP alarm_control_panel.py:133`, `apy alexaapi.py:2097` | — | `entity.alarm_control_panel.guard` |

## Actions

| Action | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Send a text command | `play_media` `custom` (`AMP media_player.py:2058`) | `send_text_command` (`core services.py:119`) | `amazon_echo.send_text_command` |
| Play a built-in sound | `play_media` `sound` (`AMP media_player.py:2003`) | `send_sound` (`core services.py:114`) | `amazon_echo.play_sound` |
| Info skill (weather, traffic, news, joke…) | `play_media` `sequence` (`AMP media_player.py:1959`) | `send_info_skill` (`core services.py:124`), 17 skills in `aio const/metadata.py:6` | `amazon_echo.send_info_skill`, the same 17 |
| Run a routine | `play_media` `routine` (`AMP media_player.py:1983`) | button only | `amazon_echo.run_routine` |
| Launch a skill | `play_media` `skill` (`AMP media_player.py:2027`) | — | `amazon_echo.launch_skill` |
| Notification to the Alexa app | `notify` `type: push` (`AMP notify.py:354`) | — | `amazon_echo.send_mobile_push` |
| Drop In notification | `notify` `type: dropin_notification` (`AMP notify.py:369`) | — | `amazon_echo.send_drop_in_notification` |
| Announcement to several devices, speak / show | `notify` `type: announce` (`AMP notify.py:317`) | — | `amazon_echo.send_announcement` |
| Create an alarm | `create_alarm` (`AMP services.py:741`) | — | `amazon_echo.create_alarm` |
| Create a music alarm | `create_alarm` `alarm_type: music` (`AMP services.py:741`, reuses an existing music alarm) | — | **not implemented**, see the last section |
| Create a timer | — | — | `amazon_echo.create_timer` |
| Create a reminder | — | — | `amazon_echo.create_reminder` |
| List alarms | `list_alarms` (`AMP services.py:801`, alarms only, no ids) | — | `amazon_echo.get_notifications` (alarms, timers, reminders, with ids) |
| Enable an alarm | `enable_alarm` (`AMP services.py:831`) | — | `amazon_echo.enable_alarm` |
| Disable an alarm | `disable_alarm` (`AMP services.py:866`) | — | `amazon_echo.disable_alarm` |
| Skip the next ring of an alarm | `skip_next_alarm` (`AMP services.py:886`) | — | `amazon_echo.skip_next_alarm` |
| Delete an alarm | `delete_alarm` (`AMP services.py:909`) | — | `amazon_echo.delete_notification` (timers and reminders too) |
| Read the voice history | `get_history_records` (`AMP services.py:936`, into an entity attribute) | — | `amazon_echo.get_voice_history` (as the action's response) |
| Refresh the last called device | `update_last_called` (`AMP services.py:399`) | — | `amazon_echo.update_last_called` |
| Restore the previous volume | `restore_volume` (`AMP services.py:460`) | — | `amazon_echo.restore_volume` |
| Repeat the last message | `repeat_last_message` (`AMP services.py:597`) | — | `amazon_echo.repeat_last_message` |
| Enable / disable Amazon Kids | `amazon_kids_enable` (`AMP services.py:559`), `amazon_kids_disable` (`AMP services.py:581`) | — | `select.select_option` on `entity.select.amazon_kids_profile`, `switch.turn_off` on `entity.switch.amazon_kids` |
| Connect / disconnect a Bluetooth device | `media_player.select_source` (`AMP media_player.py:1073`) | — | `amazon_echo.bluetooth_connect`, `amazon_echo.bluetooth_disconnect` |
| Call any feature of any Alexa endpoint | — | — | `amazon_echo.call_feature` |
| Force a new sign-in | `force_logout` (`AMP services.py:359`) | — | Reconfigure, see the last section |
| Re-run smart-home discovery | `enable_network_discovery` (`AMP services.py:1047`) | — | not needed: read on every poll |

## Events on the bus

| Event | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| A voice command was heard | `alexa_media_voice_command` (`AMP __init__.py:2124`) | — | `amazon_echo_voice_command`: `coordinator.py` |
| Another device became the last called | `alexa_media_last_called_event` (`AMP media_player.py:2280`) | — | `amazon_echo_last_called`: `coordinator.py` |
| An alarm, timer or reminder goes off | `alexa_media_notification_event` (`AMP sensor.py:868`) | — | `amazon_echo_notification`: `coordinator.py` |
| An alarm was dismissed | `alexa_media_alarm_dismissal_event` (`AMP __init__.py:1670`) | — | `amazon_echo_alarm_dismissed`: `coordinator.py` |
| Sign-in required / restored | `alexa_media_relogin_required` (`AMP helpers.py:391`), `alexa_media_relogin_success` (`AMP config_flow.py:819`) | — | Home Assistant's own reauthentication, see the last section |

## Options

| Option | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Polling interval | `scan_interval` (`AMP const.py:72`) | — | `scan_interval`: `config_flow.py` |
| Push on/off | — | — | `enable_push` |
| Local probing on/off | — | — | `enable_local` |
| Smart-home devices linked to Alexa | `extended_entity_discovery`, off by default (`AMP const.py:67`) | — | `smart_home`, off by default |
| Include / exclude devices | `include_devices`, `exclude_devices` (`AMP const.py:63`) | — | Home Assistant's own "disable device", see the last section |
| Delay to batch commands | `queue_delay` (`AMP const.py:65`) | fixed 0.3 s (`aio const/metadata.py:26`) | not needed: one request per command |
| Public URL for audio files | `public_url` (`AMP const.py:66`) | — | goes with the transcoding, see the last section |
| Debug logging | `debug` (`AMP const.py:61`) | — | Home Assistant's own "enable debug logging" |

## Diagnostics

| Feature | AMP 5.21.0 | Core alexa_devices | amazon_echo 0.2.0 |
| --- | --- | --- | --- |
| Config entry diagnostics, redacted | `AMP diagnostics.py:357` | `core diagnostics.py:34` | `diagnostics.py` (devices under aliases, voice transcripts redacted) |
| Device diagnostics | `AMP diagnostics.py:410` | `core diagnostics.py:55` | `diagnostics.py` |

## Only in amazon_echo

- Sign-in that never gives Home Assistant your password, with whatever second
  step Amazon wants; reuse of an existing Alexa Media Player session.
- Network discovery (zeroconf and DHCP) and a browse of the LAN at startup.
- Local entities that keep working without the cloud:
  `entity.sensor.ip_address`, `entity.binary_sensor.local_reachable`,
  `entity.sensor.spotify_user`.
- `entity.binary_sensor.push_connected` and a repair notice when push cannot
  work.
- Equalizer: `entity.number.bass`, `entity.number.mid`, `entity.number.treble`.
- `entity.number.speaking_rate`, `entity.select.wake_word`,
  `entity.select.alarm_sound`, `entity.select.aux_direction`,
  `entity.select.time_format`.
- `entity.switch.ascending_alarm`, `entity.switch.wake_word_sound`,
  `entity.switch.end_of_request_sound`, `entity.switch.adaptive_listening`,
  `entity.switch.captions`, `entity.switch.gestures`,
  `entity.switch.night_mode`, `entity.switch.smart_motion`,
  `entity.switch.visual_gesture`, `entity.switch.tap_gestures`,
  `entity.switch.ambient_mode`, `entity.switch.whisper_mode`,
  `entity.switch.adaptive_volume`.
- `entity.sensor.wifi_ssid`, `entity.sensor.bluetooth_device`,
  `entity.sensor.battery`, `entity.sensor.remote_battery`,
  `entity.sensor.time_zone`, `entity.sensor.wake_word_sensitivity`,
  `entity.sensor.last_called` (the other two have no entity for it),
  `entity.binary_sensor.aux_plugged`, `entity.binary_sensor.charging`.
- Timers and reminders can be created and deleted, not only alarms:
  `amazon_echo.create_timer`, `amazon_echo.create_reminder`,
  `amazon_echo.delete_notification`; `amazon_echo.get_notifications` returns
  all three with their ids.
- `amazon_echo.call_feature`, `amazon_echo.launch_skill`,
  `amazon_echo.bluetooth_connect`, `amazon_echo.bluetooth_disconnect` as
  actions of their own.
- Locks linked to Alexa, motion sensors, humidity and battery of smart-home
  devices; lamps of any kind (not only the ones paired to an Echo hub), with
  exact colours and effects.
- Media seek (forward / rewind) that does something.
- All three in one integration: Alexa Media Player has no lists, routine
  buttons, voice event entity, Drop In or illuminance; the core integration
  has no shuffle, repeat, Bluetooth, alarm actions, Guard, Kids, display
  settings, app notifications or last called device.

## In a competitor but not in amazon_echo

Missing, with the reason:

- **Audio file played as an announcement** (Alexa Media Player's `play_media`
  type `music` with `announce: true`, and its `public_url` option): Alexa
  Media Player downloads the file, transcodes it with ffmpeg into
  `/config/www` and makes Alexa speak an `<audio>` tag pointing at Home
  Assistant's public URL. The download, transcode and public-URL plumbing is
  not implemented. What is: `entity.notify.speak` and the `tts` media type
  pass SSML through, so `<audio src="https://…"/>` plays a file that is
  already in a format Alexa accepts and reachable from the internet.
- **Music alarms** (`create_alarm` with `alarm_type: music`): Alexa Media
  Player marks it experimental and can only reuse the station of a music
  alarm that already exists on the device. Existing music alarms are listed,
  enabled, disabled, skipped and deleted here like any other alarm.

Same capability on a different surface (nothing is missing, it is just not a
separate entity, action or option):

- **Shuffle and repeat switches**: `media_player.shuffle_set` and
  `media_player.repeat_set` on the media player, which is where Home
  Assistant's own cards look for them.
- **Amazon Kids binary sensor**: the state of `entity.switch.amazon_kids`.
- **`amazon_kids_enable` / `amazon_kids_disable` actions**:
  `select.select_option` on `entity.select.amazon_kids_profile` and
  `switch.turn_off` on `entity.switch.amazon_kids`.
- **`notify.alexa_media` with `data.type`**: one entity or action per type
  (`entity.notify.speak`, `entity.notify.announce`,
  `amazon_echo.send_announcement`, `amazon_echo.send_mobile_push`,
  `amazon_echo.send_drop_in_notification`).
- **`history_records` attribute**: the response of
  `amazon_echo.get_voice_history`, so the transcripts are not written to the
  recorder.
- **`force_logout` action, relogin events**: *Reconfigure* replaces the
  session at any time, and a rejected session starts Home Assistant's own
  reauthentication (with its notification and repair).
- **`enable_network_discovery` action**: the endpoint list is read on every
  poll, there is nothing to re-arm.
- **`include_devices` / `exclude_devices`, `debug`, `queue_delay` options**:
  a device is disabled from its page in Home Assistant, debug logging is
  enabled from the integration's menu, and commands are sent one by one.

Not offered by anyone any more:

- **Deleting voice history**: the only code for it is in Alexa Media Player's
  library and is not used by the integration; its endpoint
  (`/api/activities`) answers 404 since Amazon moved the history to the
  privacy hub.
- **Sound-detection binary sensors** (baby cry, dog bark…): the core
  integration removes them itself (`core binary_sensor.py:62`).

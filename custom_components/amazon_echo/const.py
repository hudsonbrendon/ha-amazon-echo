"""Constants for the Amazon Echo integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "amazon_echo"
MANUFACTURER: Final = "Amazon"
LOGGER = logging.getLogger(__package__)

PLATFORMS: Final = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TODO,
]

ALEXA_MEDIA_DOMAIN: Final = "alexa_media"

CONF_CREDENTIALS: Final = "credentials"
CONF_HOSTS: Final = "hosts"
CONF_ENTRY: Final = "entry"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_ENABLE_PUSH: Final = "enable_push"
CONF_ENABLE_LOCAL: Final = "enable_local"
CONF_SMART_HOME: Final = "smart_home"
CONF_PUBLIC_URL: Final = "public_url"
# Bridges that expose Home Assistant's own entities to Alexa (Matter hubs).
# Importing what they publish would bring every entity back as a duplicate.
HA_BRIDGE_MANUFACTURERS: Final = frozenset(
    {"home assistant", "matterbridge", "riddix", "t0bst4r"}
)
# What Home Assistant's own Emulated Hue bridge looks like to Alexa.
EMULATED_HUE: Final = "emulated_hue"
HUE_MANUFACTURER: Final = "royal philips electronics"

DEFAULT_SCAN_INTERVAL: Final = 300
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 3600
# Polling is only a fallback while push is connected; without push it speeds up.
PUSH_DOWN_SCAN_INTERVAL: Final = 60
SLOW_INTERVAL: Final = timedelta(hours=3)
LOCAL_INTERVAL: Final = timedelta(seconds=60)

# Per-device settings read through /api/v1/devices/{id}/settings/{key}.
SETTING_KEYS: Final = (
    "adaptiveBrightness",
    "adaptiveListening",
    "alexaCaptions",
    "alexaGestures",
    "alexaSpeakingRate",
    "brightness",
    "deviceNightMode",
    "displayPower",
    "smartMotion",
    "tapGestures",
    "timeFormat",
    "timeZone",
    "visualGesture",
    "wakeWordSensitivity",
)

CAP_AUDIO_PLAYER: Final = "AUDIO_PLAYER"
CAP_GUARD: Final = "GUARD_EARCON"
CAP_REBOOT: Final = "ALEXA_DEVICE_REBOOT"
CAP_REMINDERS: Final = "REMINDERS"
CAP_TIMERS_AND_ALARMS: Final = "TIMERS_AND_ALARMS"
# Device families that can be put in Amazon Kids mode.
KIDS_FAMILIES: Final = frozenset({"ECHO", "KNIGHT", "MANTIS", "REAVER", "ROOK"})

DEFAULT_MUSIC_PROVIDER: Final = "DEFAULT"
SOURCE_LOCAL_SPEAKER: Final = "Local speaker"

MEDIA_TYPE_IMAGE: Final = "image"
MEDIA_TYPE_ROUTINE: Final = "routine"
MEDIA_TYPE_SEQUENCE: Final = "sequence"
MEDIA_TYPE_SOUND: Final = "sound"
MEDIA_TYPE_SKILL: Final = "skill"
MEDIA_TYPE_TEXT_COMMAND: Final = "text_command"
MEDIA_TYPE_TTS: Final = "tts"

ATTR_DEVICE_ID: Final = "device_id"
ATTR_TEXT: Final = "text"
ATTR_SOUND: Final = "sound"
ATTR_ROUTINE: Final = "routine"
ATTR_SKILL_ID: Final = "skill_id"
ATTR_TIME: Final = "time"
ATTR_DURATION: Final = "duration"
ATTR_LABEL: Final = "label"
ATTR_RECURRENCE: Final = "recurrence"
ATTR_NOTIFICATION_ID: Final = "notification_id"
ATTR_LIMIT: Final = "limit"
ATTR_ADDRESS: Final = "address"
ATTR_ENDPOINT_ID: Final = "endpoint_id"
ATTR_FEATURE: Final = "feature"
ATTR_OPERATION: Final = "operation"
ATTR_INSTANCE: Final = "instance"
ATTR_PAYLOAD: Final = "payload"
ATTR_SKILL: Final = "skill"
ATTR_MESSAGE: Final = "message"
ATTR_TITLE: Final = "title"
ATTR_METHOD: Final = "method"
ATTR_ALARM_TYPE: Final = "alarm_type"
ATTR_MUSIC_PROVIDER: Final = "music_provider"
ATTR_MUSIC_ENTITY: Final = "music_entity"

SERVICE_SEND_TEXT_COMMAND: Final = "send_text_command"
SERVICE_PLAY_SOUND: Final = "play_sound"
SERVICE_RUN_ROUTINE: Final = "run_routine"
SERVICE_LAUNCH_SKILL: Final = "launch_skill"
SERVICE_CREATE_ALARM: Final = "create_alarm"
SERVICE_CREATE_TIMER: Final = "create_timer"
SERVICE_CREATE_REMINDER: Final = "create_reminder"
SERVICE_DELETE_NOTIFICATION: Final = "delete_notification"
SERVICE_GET_NOTIFICATIONS: Final = "get_notifications"
SERVICE_GET_VOICE_HISTORY: Final = "get_voice_history"
SERVICE_BLUETOOTH_CONNECT: Final = "bluetooth_connect"
SERVICE_BLUETOOTH_DISCONNECT: Final = "bluetooth_disconnect"
SERVICE_CALL_FEATURE: Final = "call_feature"
SERVICE_SEND_INFO_SKILL: Final = "send_info_skill"
SERVICE_SEND_MOBILE_PUSH: Final = "send_mobile_push"
SERVICE_SEND_DROP_IN_NOTIFICATION: Final = "send_drop_in_notification"
SERVICE_SEND_ANNOUNCEMENT: Final = "send_announcement"
SERVICE_ENABLE_ALARM: Final = "enable_alarm"
SERVICE_DISABLE_ALARM: Final = "disable_alarm"
SERVICE_SKIP_NEXT_ALARM: Final = "skip_next_alarm"
SERVICE_UPDATE_LAST_CALLED: Final = "update_last_called"
SERVICE_RESTORE_VOLUME: Final = "restore_volume"
SERVICE_REPEAT_LAST_MESSAGE: Final = "repeat_last_message"

ISSUE_SHARED_SESSION: Final = "shared_session"

SIGNAL_VOICE: Final = f"{DOMAIN}_voice"
EVENT_VOICE_COMMAND: Final = "voice_command"

# Events on the Home Assistant bus.
BUS_VOICE_COMMAND: Final = f"{DOMAIN}_voice_command"
BUS_LAST_CALLED: Final = f"{DOMAIN}_last_called"
BUS_NOTIFICATION: Final = f"{DOMAIN}_notification"
BUS_ALARM_DISMISSED: Final = f"{DOMAIN}_alarm_dismissed"

# Push command of a smart-home state change.
PUSH_SMART_HOME: Final = "EventBus:AlexaMobile::FDAL"

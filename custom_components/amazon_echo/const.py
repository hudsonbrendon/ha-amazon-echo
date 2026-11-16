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
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
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

DEFAULT_SCAN_INTERVAL: Final = 300
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 3600
# Polling is only a fallback while push is connected; without push it speeds up.
PUSH_DOWN_SCAN_INTERVAL: Final = 60
SLOW_INTERVAL: Final = timedelta(minutes=30)
LOCAL_INTERVAL: Final = timedelta(seconds=60)

# Per-device settings read through /api/v1/devices/{id}/settings/{key}.
SETTING_KEYS: Final = (
    "adaptiveListening",
    "alexaCaptions",
    "alexaGestures",
    "alexaSpeakingRate",
    "deviceNightMode",
    "smartMotion",
    "tapGestures",
    "timeFormat",
    "timeZone",
    "visualGesture",
    "wakeWordSensitivity",
)

CAP_AUDIO_PLAYER: Final = "AUDIO_PLAYER"
CAP_REBOOT: Final = "ALEXA_DEVICE_REBOOT"
CAP_REMINDERS: Final = "REMINDERS"
CAP_TIMERS_AND_ALARMS: Final = "TIMERS_AND_ALARMS"

DEFAULT_MUSIC_PROVIDER: Final = "DEFAULT"
SOURCE_LOCAL_SPEAKER: Final = "Local speaker"

MEDIA_TYPE_ROUTINE: Final = "routine"
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

ISSUE_SHARED_SESSION: Final = "shared_session"

SIGNAL_VOICE: Final = f"{DOMAIN}_voice"
EVENT_VOICE_COMMAND: Final = "voice_command"

"""Lights: Echo Glow and, when asked for, the lamps linked to Alexa."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityDescription,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.color import brightness_to_value, value_to_brightness

from amazon_echo import Endpoint

from . import AmazonEchoConfigEntry
from .coordinator import AmazonEchoCoordinator
from .entity import AmazonEchoEndpointEntity, async_add_dynamic

PARALLEL_UPDATES = 0

DESCRIPTION = LightEntityDescription(key="light", name=None)
BRIGHTNESS_SCALE = (1, 100)
# What Alexa calls warm white and daylight; lamps accept anything in between.
MIN_KELVIN = 2200
MAX_KELVIN = 6500
LIGHT_FEATURES = ("brightness", "color", "color_temperature")


def is_light(endpoint: Endpoint) -> bool:
    """A light is something with power that is a lamp or can be dimmed/coloured."""
    state = endpoint.state
    return "power" in state and (
        endpoint.category == "LIGHT" or any(key in state for key in LIGHT_FEATURES)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmazonEchoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one light per smart-home lamp."""
    async_add_dynamic(
        entry,
        async_add_entities,
        lambda data: (e.id for e in data.smart_home.values() if is_light(e)),
        lambda endpoint_id: AmazonEchoLight(
            entry.runtime_data, DESCRIPTION, endpoint_id
        ),
    )


class AmazonEchoLight(AmazonEchoEndpointEntity, LightEntity):
    """A lamp controlled through Alexa."""

    _attr_min_color_temp_kelvin = MIN_KELVIN
    _attr_max_color_temp_kelvin = MAX_KELVIN

    def __init__(
        self,
        coordinator: AmazonEchoCoordinator,
        description: LightEntityDescription,
        endpoint_id: str,
    ) -> None:
        """Work out what the lamp can do from its features and operations."""
        super().__init__(coordinator, description, endpoint_id)
        endpoint = self.endpoint
        modes: set[ColorMode] = set()
        if "color" in endpoint.state and endpoint.supports("color", "setColor"):
            modes.add(ColorMode.HS)
        if "color_temperature" in endpoint.state and endpoint.supports(
            "colorTemperature", "setColorTemperature"
        ):
            modes.add(ColorMode.COLOR_TEMP)
        if not modes:
            dimmable = "brightness" in endpoint.state
            modes.add(ColorMode.BRIGHTNESS if dimmable else ColorMode.ONOFF)
        self._attr_supported_color_modes = modes
        # Light shows (Echo Glow) and the like are one "mode" feature.
        self._effects: dict[str, str] = (
            endpoint.state.get("mode_options") or {}
            if endpoint.supports("mode", "setMode")
            else {}
        )
        if self._effects:
            self._attr_supported_features = LightEntityFeature.EFFECT
            self._attr_effect_list = list(self._effects)

    @property
    def color_mode(self) -> ColorMode:
        """Colour while the lamp reports one, otherwise white."""
        modes = self._attr_supported_color_modes or set()
        if modes == {ColorMode.HS, ColorMode.COLOR_TEMP}:
            # a lamp in white mode stops reporting a colour
            white = self.value("color") is None
            return ColorMode.COLOR_TEMP if white else ColorMode.HS
        return next(iter(modes))

    @property
    def is_on(self) -> bool | None:
        """Whether the lamp is on."""
        power: bool | None = self.value("power")
        return power

    @property
    def brightness(self) -> int | None:
        """Brightness 1..255."""
        if (brightness := self.value("brightness")) is None:
            return None
        return value_to_brightness(BRIGHTNESS_SCALE, brightness)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Hue and saturation."""
        if (color := self.value("color")) is None:
            return None
        return (color["hue"], color["saturation"] * 100)

    @property
    def color_temp_kelvin(self) -> int | None:
        """Colour temperature."""
        kelvin: int | None = self.value("color_temperature")
        return kelvin

    @property
    def effect(self) -> str | None:
        """Current light show."""
        mode = self.value("mode")
        return next((name for name, v in self._effects.items() if v == mode), None)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, then apply brightness, colour and effect."""
        if not self.is_on:
            await self._async_call("power", "turnOn", state={"power": True})
        if ATTR_BRIGHTNESS in kwargs:
            level = max(
                1, round(brightness_to_value(BRIGHTNESS_SCALE, kwargs[ATTR_BRIGHTNESS]))
            )
            await self._async_call(
                "brightness",
                "setBrightness",
                payload={"brightness": level},
                state={"brightness": level},
            )
        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            color = {"hue": hue, "saturation": saturation / 100, "brightness": 1.0}
            await self._async_call(
                "color", "setColor", payload={"color": color}, state={"color": color}
            )
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            await self._async_call(
                "colorTemperature",
                "setColorTemperature",
                payload={"colorTemperatureInKelvin": kelvin},
                # a lamp in white mode stops reporting a colour
                state={"color_temperature": kelvin, "color": None},
            )
        if ATTR_EFFECT in kwargs:
            mode = self._effects[kwargs[ATTR_EFFECT]]
            await self._async_call(
                "mode",
                "setMode",
                instance=self.value("mode_instance"),
                payload={"mode": mode},
                state={"mode": mode},
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._async_call("power", "turnOff", state={"power": False})

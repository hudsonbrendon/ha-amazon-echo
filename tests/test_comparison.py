"""COMPARISON.md cannot drift from the code, and translations stay in parity."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "amazon_echo"
COMPARISON = (ROOT / "COMPARISON.md").read_text()
STRINGS: dict[str, Any] = json.loads((COMPONENT / "strings.json").read_text())
SERVICES: dict[str, Any] = yaml.safe_load((COMPONENT / "services.yaml").read_text())

# How the document names things of amazon_echo (see its first table).
ENTITY = re.compile(r"`entity\.([a-z_]+)\.([a-z0-9_]+)`")
ACTION = re.compile(r"`amazon_echo\.([a-z0-9_]+)`")
SOURCE = re.compile(r"`([a-z_]+\.(?:py|json|yaml))`")
CITATION = re.compile(r"`(?:AMP|apy|core|aio) [\w/.]+:\d+`")


def _keys(data: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        if isinstance(value, dict):
            keys |= _keys(value, f"{prefix}{key}.")
        else:
            keys.add(prefix + key)
    return keys


def test_named_entities_exist() -> None:
    named = set(ENTITY.findall(COMPARISON))
    assert len(named) > 60
    for platform, key in sorted(named):
        assert key in STRINGS["entity"].get(platform, {}), (
            f"COMPARISON.md names entity.{platform}.{key}, "
            "which has no translation key in strings.json"
        )


def test_named_actions_exist() -> None:
    named = set(ACTION.findall(COMPARISON))
    assert len(named) > 20
    for action in sorted(named):
        assert action in SERVICES, f"amazon_echo.{action} is not in services.yaml"
        assert action in STRINGS["services"], f"amazon_echo.{action} has no strings"


def test_everything_the_integration_has_is_listed() -> None:
    """A new entity key or action must be added to the comparison too."""
    entities = {
        (platform, key) for platform, keys in STRINGS["entity"].items() for key in keys
    }
    assert entities - set(ENTITY.findall(COMPARISON)) == set()
    assert set(SERVICES) - set(ACTION.findall(COMPARISON)) == set()
    assert set(SERVICES) == set(STRINGS["services"])


def test_named_source_files_exist() -> None:
    named = set(SOURCE.findall(COMPARISON))
    assert {"coordinator.py", "config_flow.py", "light.py", "lock.py"} <= named
    for name in sorted(named):
        assert (COMPONENT / name).is_file(), f"COMPARISON.md names {name}"


def test_document_shape() -> None:
    """Three products per table, competitor claims cited, both closing lists."""
    header = "| AMP 5.21.0 | Core alexa_devices | amazon_echo 0.3 |"
    assert COMPARISON.count(header) >= 15
    for section in (
        "## Authentication",
        "## Discovery",
        "## Local network",
        "## Push events handled",
        "## Entities",
        "## Actions",
        "## Events on the bus",
        "## Options",
        "## Diagnostics",
        "## Only in amazon_echo",
        "## In a competitor but not in amazon_echo",
        "## How the superset is verified",
    ):
        assert f"\n{section}\n" in COMPARISON, section
    assert len(CITATION.findall(COMPARISON)) > 150
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    # major.minor only, so a patch release does not need a document edit
    minor = ".".join(manifest["version"].split(".")[:2])
    assert f"amazon_echo {minor} |" in COMPARISON


@pytest.mark.parametrize("language", ["en", "pt-BR", "pt"])
def test_translations_are_in_parity(language: str) -> None:
    translation = json.loads(
        (COMPONENT / "translations" / f"{language}.json").read_text()
    )
    assert _keys(translation) == _keys(STRINGS)
    if language == "en":
        assert translation == STRINGS
    else:
        # really translated, not a copy of the English file
        names = translation["entity"]
        assert names["sensor"]["last_called"]["name"] == "Último dispositivo acionado"
        assert names["sensor"]["illuminance"]["name"] == "Iluminância"
        assert names["sensor"]["humidity"]["name"] == "Umidade"
        assert names["binary_sensor"]["motion"]["name"] == "Movimento"
        assert names["switch"]["announcements"]["name"] == "Anúncios"
        assert names["switch"]["communications"]["name"] == "Comunicações"
        assert names["select"]["drop_in"]["name"] == "Drop In"
        assert names["alarm_control_panel"]["guard"]["name"] == "Alexa Guard"
        assert (
            translation["options"]["step"]["init"]["data"]["smart_home"]
            == "Dispositivos smart home da Alexa"
        )

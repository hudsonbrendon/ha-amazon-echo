"""The superset claim, checked instead of asserted.

``tests/fixtures/competitor_features.json`` is what
``scripts/extract_competitor_features.py`` found in the source of Alexa Media
Player and of the core Alexa Devices integration. ``tests/superset_map.json``
says, for each of those features, what amazon_echo has for it. These tests
fail when a competitor feature has no entry, or when an entry points at
something that is not in the code.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any

from homeassistant.helpers.entity import EntityDescription
import pytest
import yaml

from custom_components.amazon_echo.config_flow import OPTIONS_SCHEMA
from custom_components.amazon_echo.services import SCHEMAS

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "amazon_echo"
FIXTURE: dict[str, Any] = json.loads(
    (ROOT / "tests" / "fixtures" / "competitor_features.json").read_text()
)
FEATURES: dict[str, dict[str, Any]] = FIXTURE["features"]
MAP: dict[str, dict[str, str]] = json.loads(
    (ROOT / "tests" / "superset_map.json").read_text()
)
STRINGS: dict[str, Any] = json.loads((COMPONENT / "strings.json").read_text())
SERVICES: dict[str, Any] = yaml.safe_load((COMPONENT / "services.yaml").read_text())
COMPARISON = (ROOT / "COMPARISON.md").read_text()
README = (ROOT / "README.md").read_text()

# What a map entry may point at; "note" and "field" only qualify a target.
TARGETS = (
    "entity",
    "action",
    "media_feature",
    "entity_feature",
    "play_media_type",
    "option",
    "event",
    "push",
    "attribute",
    "code",
    "removed",
    "not_applicable",
)
# Competitor features that are not capabilities (a stored password, a debug
# toggle, the tuning of the competitor's own plumbing). The list may shrink,
# never grow: a new competitor feature gets implemented, not waved away.
MAX_NOT_APPLICABLE = 9
PREFIXES = ("amp", "core")
MIN_REASON = 30
SOURCE = re.compile(r"^(?:AMP|apy|core|aio) [\w/.]+:\d+$")


def _load_extractor() -> ModuleType:
    """Import the extraction script: the same parser reads amazon_echo."""
    name = "extract_competitor_features"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


EXTRACTOR = _load_extractor()
MODULES = {module.name: module for module in EXTRACTOR.load(COMPONENT, "ours")}
OURS: dict[str, dict[str, Any]] = EXTRACTOR.extract("ours", COMPONENT, "ours").features


def _ours(kind: str) -> set[str]:
    return {f["name"] for f in OURS.values() if f["kind"] == kind}


def _strings(nodes: Iterable[ast.AST], env: dict[str, str]) -> set[str]:
    """Return every string constant (or known constant name) under ``nodes``."""
    found: set[str] = set()
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
            elif isinstance(node, ast.Name) and node.id in env:
                found.add(env[node.id])
    return found


def _named(tree: ast.AST, *names: str) -> list[ast.AST]:
    """Return the functions and assignments of a module called ``names``."""
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in names:
                found.append(node)
        elif isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) in names:
            found.append(node)
    return found


def _description_keys(platform: str) -> set[str]:
    """Translation keys of the entity descriptions a platform file builds."""
    keys: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, EntityDescription):
            keys.add(value.translation_key or value.key)
        elif isinstance(value, (tuple, list, set, frozenset)):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    module = importlib.import_module(f"custom_components.amazon_echo.{platform}")
    for value in vars(module).values():
        collect(value)
    # entities made per item at run time (one per list, per routine) name
    # their translation key themselves, straight or through a module table
    tree = MODULES[f"{platform}.py"].tree
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "translation_key":
            keys |= _strings([node.value], {})
        elif isinstance(node, ast.Assign) and ast.unparse(node.targets[0]).endswith(
            "_attr_translation_key"
        ):
            tables = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            keys |= _strings([node.value, *_named(tree, *tables)], {})
    return keys


def _registered_actions() -> set[str]:
    """Names ``services.py`` hands to ``hass.services.async_register``."""
    module = MODULES["services.py"]
    names: set[str] = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.For) and "async_register" in ast.unparse(node):
            assert isinstance(node.iter, ast.Tuple)
            for pair in node.iter.elts:
                assert isinstance(pair, ast.Tuple)
                names |= _strings([pair.elts[0]], module.env)
    return names


REGISTERED = _registered_actions()
MEDIA_PLAYER = MODULES["media_player.py"]
COORDINATOR = MODULES["coordinator.py"]
# Flags inside the expression the media player reports as supported.
MEDIA_FEATURES = {
    node.attr
    for root in _named(MEDIA_PLAYER.tree, "BASE_FEATURES", "supported_features")
    for node in ast.walk(root)
    if isinstance(node, ast.Attribute)
    and ast.unparse(node.value) == "MediaPlayerEntityFeature"
}
# Commands the push handler acts on: its two tables and its comparisons.
PUSH_COMMANDS = _strings(
    _named(COORDINATOR.tree, "PUSH_REFETCH", "PUSH_IN_PLACE", "_handle_push"),
    COORDINATOR.env,
)


def _identifiers(path: Path) -> set[str]:
    """Every name a Python file defines or refers to."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        for attribute in ("id", "attr", "name", "arg"):
            if isinstance(value := getattr(node, attribute, None), str):
                names.add(value)
    return names


def problem(target: dict[str, str], feature: dict[str, Any] | None = None) -> str:
    """Return why a map entry is wrong, or an empty string when it holds."""
    kinds = [kind for kind in TARGETS if kind in target]
    if len(kinds) != 1 or set(target) - {*TARGETS, "note", "field"}:
        return f"needs exactly one of {', '.join(TARGETS)}"
    kind, value = kinds[0], target[kinds[0]]
    if "field" in target and kind != "action":
        return "only an action has a field"

    if kind == "entity":
        platform, _, key = value.partition(".")
        if key not in STRINGS["entity"].get(platform, {}):
            return f"no entity.{value} in strings.json"
        if key not in _description_keys(platform):
            return f"no entity description with key {key} in {platform}.py"
    elif kind == "action":
        if value not in SERVICES or value not in STRINGS["services"]:
            return f"amazon_echo.{value} is not in services.yaml / strings.json"
        if value not in REGISTERED:
            return f"amazon_echo.{value} is not registered in services.py"
        if (field := target.get("field")) is not None:
            if field not in (SERVICES[value].get("fields") or {}):
                return f"amazon_echo.{value} has no field {field} in services.yaml"
            if field not in {str(key) for key in SCHEMAS[value].schema}:
                return f"the schema of amazon_echo.{value} has no {field}"
    elif kind == "media_feature":
        if value not in MEDIA_FEATURES:
            return f"MediaPlayerEntityFeature.{value} is not a supported feature"
    elif kind == "entity_feature":
        if value not in _ours("feature"):
            return f"{value} is not used by any platform"
    elif kind == "play_media_type":
        if value not in _ours("play_media"):
            return f"play_media does not handle the type {value}"
    elif kind == "option":
        if value not in {str(key) for key in OPTIONS_SCHEMA.schema}:
            return f"{value} is not in the options flow schema"
        if value not in STRINGS["options"]["step"]["init"]["data"]:
            return f"the option {value} has no label in strings.json"
    elif kind == "event":
        if value not in _ours("event"):
            return f"{value} is never fired on the bus"
    elif kind == "push":
        if value not in PUSH_COMMANDS:
            return f"the push handler does not know {value}"
    elif kind == "attribute":
        platform, _, key = value.partition(".")
        module = MODULES.get(f"{platform}.py")
        keys = {
            constant.value
            for node in ast.walk(module.tree if module else ast.Module([], []))
            if isinstance(node, ast.Dict)
            for constant in node.keys
            if isinstance(constant, ast.Constant)
        }
        if key not in keys:
            return f"{platform}.py builds no attribute {key}"
    elif kind == "code":
        relative, _, symbol = value.partition("::")
        path = ROOT / relative
        if not symbol or not path.is_file() or ROOT not in path.resolve().parents:
            return f"{relative} is not a file of this repository"
        if path.suffix == ".py":
            if symbol not in _identifiers(path):
                return f"{relative} has no {symbol}"
        elif symbol not in path.read_text():
            return f"{relative} does not mention {symbol}"
    elif kind == "removed":
        if not (feature or {}).get("deprecated"):
            return "only what the competitor itself removed can be 'removed'"
    elif len(value) < MIN_REASON:
        return f"a not_applicable needs a reason of {MIN_REASON} characters or more"
    return ""


# --------------------------------------------------------------------------- #
# (a) nothing of a competitor is left unmapped
# --------------------------------------------------------------------------- #
def test_every_competitor_feature_is_mapped() -> None:
    unmapped = sorted(set(FEATURES) - set(MAP))
    assert not unmapped, (
        "Competitor features with no entry in tests/superset_map.json "
        "(implement them, then map them):\n" + "\n".join(unmapped)
    )
    stale = sorted(set(MAP) - set(FEATURES))
    assert not stale, "Map entries for features no competitor has:\n" + "\n".join(stale)


# --------------------------------------------------------------------------- #
# (b) every target is really there
# --------------------------------------------------------------------------- #
def test_every_target_exists() -> None:
    problems = [
        f"{key} -> {json.dumps(target)}: {reason}"
        for key, target in MAP.items()
        if (reason := problem(target, FEATURES.get(key)))
    ]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    "target",
    [
        {"entity": "sensor.does_not_exist"},
        {"entity": "sensor.items"},  # an attribute, not an entity
        {"action": "does_not_exist"},
        {"action": "create_alarm", "field": "does_not_exist"},
        {"media_feature": "BROWSE_MEDIA"},
        {"entity_feature": "LightEntityFeature.FLASH"},
        {"play_media_type": "video"},
        {"option": "queue_delay"},
        {"event": "amazon_echo_does_not_exist"},
        {"push": "PUSH_DOES_NOT_EXIST"},
        {"attribute": "media_player.does_not_exist"},
        {"code": "custom_components/amazon_echo/light.py::DoesNotExist"},
        {"code": "custom_components/amazon_echo/missing.py::AmazonEchoLight"},
        {"code": "../outside.py::anything"},
        {"removed": "says who"},
        {"not_applicable": "too short"},
        {"entity": "switch.amazon_kids", "action": "create_alarm"},
        {"entity": "switch.amazon_kids", "field": "device_id"},
        {"note": "nothing at all"},
    ],
)
def test_a_wrong_target_is_caught(target: dict[str, str]) -> None:
    """The checks above are not vacuous."""
    assert problem(target, {"deprecated": False})


def test_the_parser_sees_what_the_integration_has() -> None:
    """Run on amazon_echo, the extractor finds what the other tests rely on."""
    assert _ours("play_media") == {
        *("music", "routine", "sound", "skill", "text_command", "tts"),
        *("sequence", "image", EXTRACTOR.DYNAMIC),
    }
    assert _ours("event") == {
        "amazon_echo_voice_command",
        "amazon_echo_last_called",
        "amazon_echo_notification",
        "amazon_echo_alarm_dismissed",
    }
    assert _ours("service") == set(SERVICES) == REGISTERED
    assert {"SEEK", "SELECT_SOURCE", "MEDIA_ANNOUNCE", "SHUFFLE_SET"} <= MEDIA_FEATURES
    assert {"PUSH_VOLUME_CHANGE", "EventBus:AlexaMobile::FDAL"} <= PUSH_COMMANDS
    assert "PUSH_DOES_NOT_EXIST" not in PUSH_COMMANDS


# --------------------------------------------------------------------------- #
# (c) "not applicable" stays short and explained
# --------------------------------------------------------------------------- #
def test_not_applicable_is_short_and_explained() -> None:
    excused = {
        key: target["not_applicable"]
        for key, target in MAP.items()
        if "not_applicable" in target
    }
    listing = "\n".join(f"{key}: {reason}" for key, reason in excused.items())
    assert len(excused) <= MAX_NOT_APPLICABLE, (
        f"{len(excused)} features are marked not applicable, "
        f"{MAX_NOT_APPLICABLE} are allowed:\n{listing}"
    )
    for key, reason in excused.items():
        assert len(reason) >= MIN_REASON, f"{key} needs a real reason:\n{listing}"
    # what a competitor dropped itself is not ours to implement, and only that
    for key, feature in FEATURES.items():
        if feature.get("deprecated"):
            assert set(MAP[key]) - {"note"} == {"removed"}, key


# --------------------------------------------------------------------------- #
# (d) the fixture is the inventory of the versions COMPARISON.md cites
# --------------------------------------------------------------------------- #
def test_fixture_matches_the_versions_compared() -> None:
    amp, core = FIXTURE["competitors"]["amp"], FIXTURE["competitors"]["core"]
    for cited in (
        amp["version"],
        f"`{amp['commit'][:7]}`",
        f"`{amp['library_commit'][:7]}`",
        f"`{core['commit'][:7]}`",
        core["library_version"],
        f"`{core['library_commit'][:7]}`",
    ):
        assert cited in COMPARISON, f"COMPARISON.md does not cite {cited}"


def test_fixture_is_an_inventory_not_code() -> None:
    """Identifiers and line references only; the counts add up."""
    for prefix, competitor in FIXTURE["competitors"].items():
        keys = [key for key in FEATURES if key.startswith(f"{prefix}:")]
        assert competitor["feature_count"] == len(keys) > 90
        assert sum(competitor["features_by_kind"].values()) == len(keys)
    assert len(FEATURES) == sum(
        c["feature_count"] for c in FIXTURE["competitors"].values()
    )
    allowed = {
        *("kind", "name", "source"),
        *("translation_key", "deprecated", "flows", "options"),
    }
    for key, feature in FEATURES.items():
        assert set(feature) <= allowed, key
        assert key == f"{key.split(':')[0]}:{feature['kind']}:{feature['name']}"
        assert SOURCE.match(feature["source"]), key
        assert len(feature["name"]) < 80 and "\n" not in feature["name"], key
    for key, source in FIXTURE["ignored"].items():
        assert key not in FEATURES and SOURCE.match(source)


def test_documents_quote_the_counts() -> None:
    """The numbers in the two documents are the ones in the fixture."""
    excused = sum("not_applicable" in target for target in MAP.values())
    for name, text in (("COMPARISON.md", COMPARISON), ("README.md", README)):
        for competitor in FIXTURE["competitors"].values():
            count = f"{competitor['feature_count']} features"
            assert count in text, f"{name} does not say {count}"
        assert f"{excused} are marked not applicable" in text, name
        for path in (
            "scripts/extract_competitor_features.py",
            "tests/fixtures/competitor_features.json",
            "tests/superset_map.json",
            "tests/test_superset.py",
        ):
            assert path in text, f"{name} does not point at {path}"
            assert (ROOT / path).is_file()
    assert excused <= MAX_NOT_APPLICABLE
    # the two tables of COMPARISON.md, row by row
    amp, core = (FIXTURE["competitors"][name]["features_by_kind"] for name in PREFIXES)
    rows = [
        (kind, amp.get(kind, 0), core.get(kind, 0))
        for kind in {feature["kind"] for feature in FEATURES.values()}
    ]
    rows += [
        (
            target,
            *(
                sum(
                    key.startswith(f"{prefix}:") and target in entry
                    for key, entry in MAP.items()
                )
                for prefix in PREFIXES
            ),
        )
        for target in TARGETS
    ]
    for name, in_amp, in_core in rows:
        row = rf"^\| `{name}` \| [^|]+ \| {in_amp} \| {in_core} \|$"
        assert re.search(row, COMPARISON, re.MULTILINE), f"COMPARISON.md: {name}"


# --------------------------------------------------------------------------- #
# The extractor itself, on a made-up integration
# --------------------------------------------------------------------------- #
def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_extractor_on_a_made_up_integration(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    _write(
        package,
        {
            "const.py": 'DOMAIN = "fake"\nSERVICE_PING = "ping"\nATTR_WHO = "who"\n',
            "switch.py": (
                "from .const import DOMAIN\n"
                "class Base(SwitchEntity):\n"
                "    @property\n"
                "    def extra_state_attributes(self):\n"
                '        attr = {"mode": 1, "nested": {"skipped": 2}}\n'
                '        attr["extra"] = 3\n'
                "        return attr\n"
                "class Dnd(Base):\n"
                "    _attr_supported_features = SwitchEntityFeature.FANCY\n"
                "    def turn_on(self):\n"
                '        self.hass.bus.async_fire(f"{DOMAIN}_dnd", {})\n'
            ),
            "sensor.py": (
                'OLD = "x"\n'
                'SENSORS = (SensorEntityDescription(key="temp"),\n'
                "           SensorEntityDescription(key=make_key()))\n"
                'DEPRECATED_SENSORS = (SensorEntityDescription(key="gone"),)\n'
            ),
            "media_player.py": (
                "class Player(MediaPlayerEntity):\n"
                "    async def async_play_media(self, media_type, media_id, **kwargs):\n"
                '        if media_type == "sound":\n'
                "            pass\n"
                '        elif media_type in ("a", "b") or kwargs.get("announce"):\n'
                "            pass\n"
                "        else:\n"
                "            await self.api.play(media_type, media_id)\n"
            ),
            "__init__.py": (
                "def handle(command):\n"
                '    if command == "PUSH_REAL":\n'
                "        update()\n"
                '    elif command in ("PUSH_LOGGED",):\n'
                '        _LOGGER.debug("ignored")\n'
            ),
            "services.py": (
                "from .const import ATTR_WHO, SERVICE_PING\n"
                "PING = vol.Schema({vol.Required(ATTR_WHO): str,\n"
                '                   vol.Optional("hidden"): str})\n'
                "DEFS = (ServiceDef(name=SERVICE_PING, schema=PING),\n"
                '        ServiceDef(name="unlisted", schema=None))\n'
            ),
            "services.yaml": (
                "# a comment\n"
                "ping:\n"
                "  description: >-\n"
                "    Two lines: of text\n"
                "    that are not structure.\n"
                "  fields: &who\n"
                "    who:\n"
                "      selector:\n"
                "        select:\n"
                "          options:\n"
                "            - me\n"
                '            - "you"\n'
                "pong:\n"
                "  fields: *who\n"
            ),
            "strings.json": json.dumps(
                {
                    "config": {"step": {"user": {"data": {"password": "P"}}}},
                    "options": {"step": {"init": {"data": {"delay": "D"}}}},
                    "entity": {"switch": {"dnd": {"name": "DND"}}},
                }
            ),
        },
    )
    library = tmp_path / "lib"
    _write(
        library,
        {
            "api.py": (
                "class Push(StrEnum):\n"
                '    Volume = "PUSH_LIB"\n'
                '    Other = "PUSH_LIB_IGNORED"\n'
                "async def handler(event_type):\n"
                "    match event_type:\n"
                "        case Push.Volume.value:\n"
                "            await act()\n"
                "        case Push.Other.value:\n"
                "            pass\n"
                "        case _:\n"
                "            pass\n"
            )
        },
    )
    inventory = EXTRACTOR.extract("x", package, "AMP", library, "apy")
    assert set(inventory.features) == {
        "x:platform:switch",
        "x:platform:sensor",
        "x:platform:media_player",
        "x:entity:switch.Dnd",  # Base is only a base class
        "x:entity:sensor.temp",
        f"x:entity:sensor.{EXTRACTOR.DYNAMIC}",
        "x:entity:sensor.gone",
        "x:entity:media_player.Player",
        "x:entity_key:switch.dnd",
        "x:attribute:switch.Base.mode",
        "x:attribute:switch.Base.nested",  # its own keys are not attributes
        "x:attribute:switch.Base.extra",
        "x:feature:SwitchEntityFeature.FANCY",
        "x:event:fake_dnd",
        "x:play_media:sound",
        "x:play_media:a",
        "x:play_media:b",
        f"x:play_media:{EXTRACTOR.DYNAMIC}",
        "x:play_media_option:announce",
        "x:push:PUSH_REAL",
        "x:push:PUSH_LIB",
        "x:option:password",
        "x:option:delay",
        "x:service:ping",
        "x:service:pong",
        "x:service:unlisted",
        "x:service_field:ping.who",
        "x:service_field:ping.hidden",  # in the schema, not in services.yaml
        "x:service_field:pong.who",
    }
    features = inventory.features
    assert features["x:entity:sensor.gone"]["deprecated"] is True
    assert "deprecated" not in features["x:entity:sensor.temp"]
    assert features["x:service_field:ping.who"]["options"] == ["me", "you"]
    assert features["x:service_field:ping.who"]["source"] == "AMP services.yaml:7"
    assert features["x:event:fake_dnd"]["source"] == "AMP switch.py:11"
    assert features["x:push:PUSH_LIB"]["source"] == "apy api.py:6"
    assert features["x:option:password"]["flows"] == ["config.user"]
    assert inventory.ignored == {
        "push:PUSH_LOGGED": "AMP __init__.py:4",
        "push:PUSH_LIB_IGNORED": "apy api.py:8",
    }

    # the commit comes from the files of the checkout, packed or not
    repo = tmp_path / "repo"
    _write(repo, {".git/HEAD": "ref: refs/heads/dev\n", ".git/refs/heads/dev": "abc\n"})
    assert EXTRACTOR.commit(repo) == "abc"
    _write(repo, {".git/HEAD": "ref: refs/heads/main\n"})
    _write(repo, {".git/packed-refs": "# pack-refs\ndef refs/heads/main\n"})
    assert EXTRACTOR.commit(repo) == "def"
    _write(repo, {".git/HEAD": "0123456\n"})
    assert EXTRACTOR.commit(repo) == "0123456"

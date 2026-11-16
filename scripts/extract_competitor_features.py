#!/usr/bin/env python3
"""Inventory what the other two Alexa integrations offer, by reading their source.

Usage:
    python scripts/extract_competitor_features.py SRC_AMP SRC_CORE [-o FILE]

``SRC_AMP`` holds checkouts of ``alexa_media_player`` and ``alexapy``;
``SRC_CORE`` holds ``core`` (Home Assistant) and ``aioamazondevices``.

Nothing of them is imported or run. Python is parsed with ``ast``, JSON with
``json``, ``services.yaml`` with the small parser below. The output,
``tests/fixtures/competitor_features.json``, lists identifiers and where each
was found (``file:line``): platforms, entities, state attributes, actions and
their fields, notify types, events, feature flags, ``play_media`` types,
options and push commands. ``tests/test_superset.py`` then requires every one
of them to be mapped to something amazon_echo really has.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import tomllib
from typing import Any

OUTPUT = (
    Path(__file__).parent.parent / "tests" / "fixtures" / "competitor_features.json"
)

# Entity platforms of Home Assistant an Alexa integration could implement.
PLATFORMS = frozenset(
    {
        "alarm_control_panel",
        "binary_sensor",
        "button",
        "calendar",
        "climate",
        "cover",
        "event",
        "fan",
        "light",
        "lock",
        "media_player",
        "notify",
        "number",
        "scene",
        "select",
        "sensor",
        "switch",
        "todo",
    }
)
# Names both integrations import from Home Assistant and use as keys.
HA_CONSTANTS = {
    "ATTR_DEVICE_ID": "device_id",
    "ATTR_ENTITY_ID": "entity_id",
    "ATTR_MEDIA_ANNOUNCE": "announce",
    "CONF_CODE": "code",
    "CONF_EMAIL": "email",
    "CONF_PASSWORD": "password",
    "CONF_URL": "url",
    "CONF_USERNAME": "username",
    "CommonServiceArgument.DEVICE_ID": "device_id",
    "MediaType.MUSIC": "music",
}
LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "log"})
FLAG_ENUM = re.compile(r"^(?:[A-Za-z]+EntityFeature|ColorMode)$")
DYNAMIC = "*"  # a key computed at run time (one entity per routine, per list...)


# --------------------------------------------------------------------------- #
# A YAML subset: mappings, lists of scalars, anchors, aliases and merges.
# --------------------------------------------------------------------------- #
class Node(dict[str, Any]):
    """A mapping that remembers the line of each key."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.lines: dict[str, int] = {}


def parse_yaml(text: str) -> Node:
    """Parse the subset of YAML that ``services.yaml`` files use."""
    rows = [
        (len(raw) - len(raw.lstrip(" ")), raw.strip(), number)
        for number, raw in enumerate(text.splitlines(), 1)
        if raw.strip() and not raw.strip().startswith("#") and raw.strip() != "---"
    ]
    anchors: dict[str, Any] = {}

    def scalar(value: str) -> str:
        if value[:1] in "\"'":
            return value[1:].partition(value[0])[0]
        return value.partition(" #")[0].strip()

    def block(index: int, indent: int) -> tuple[Any, int]:
        if rows[index][1].startswith("- "):
            items: list[str] = []
            while (
                index < len(rows)
                and rows[index][0] == indent
                and rows[index][1].startswith("- ")
            ):
                items.append(scalar(rows[index][1][2:].strip()))
                index += 1
                while index < len(rows) and rows[index][0] > indent:
                    index += 1
            return items, index
        node = Node()
        while index < len(rows) and rows[index][0] == indent:
            key, colon, rest = rows[index][1].partition(":")
            line = rows[index][2]
            index += 1
            if not colon:
                continue
            key, rest = scalar(key.strip()), rest.strip()
            anchor = ""
            if rest.startswith("&"):
                anchor, _, rest = rest[1:].partition(" ")
                rest = rest.strip()
            value: Any
            if rest.startswith("*"):
                value = anchors.get(rest[1:])
            elif rest:
                value = scalar(rest)
                # a block or multi-line scalar: its lines are not structure
                while index < len(rows) and rows[index][0] > indent:
                    index += 1
            elif index < len(rows) and rows[index][0] > indent:
                value, index = block(index, rows[index][0])
            else:
                value = None
            if anchor:
                anchors[anchor] = value
            if key == "<<" and isinstance(value, Node):
                node.update(value)
                node.lines.update(value.lines)
            else:
                node[key] = value
                node.lines[key] = line
        return node, index

    return block(0, rows[0][0])[0] if rows else Node()


# --------------------------------------------------------------------------- #
# Source trees
# --------------------------------------------------------------------------- #
@dataclass
class Module:
    """A parsed Python file."""

    label: str  # how COMPARISON.md cites it: AMP, apy, core, aio
    name: str  # path relative to the package
    tree: ast.Module
    env: dict[str, str] = field(default_factory=dict)

    def ref(self, node: ast.AST | int) -> str:
        """Return the citation of a node (or a line) of this file."""
        line = node if isinstance(node, int) else getattr(node, "lineno", 1)
        return f"{self.label} {self.name}:{line}"


def _is_enum(cls: ast.ClassDef) -> bool:
    return any("Enum" in ast.unparse(base) for base in cls.bases)


def _resolve(node: ast.AST | None, *envs: dict[str, str]) -> str | None:
    """Return the string a constant expression stands for, if it is known."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = [
            _resolve(v.value if isinstance(v, ast.FormattedValue) else v, *envs)
            for v in node.values
        ]
        return None if None in parts else "".join(p for p in parts if p)
    if isinstance(node, ast.Subscript):  # f"{DOMAIN}_x"[0:32]
        return _resolve(node.value, *envs)
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = ast.unparse(node).removesuffix(".value")
        for env in (*envs, HA_CONSTANTS):
            if name in env:
                return env[name]
    return None


def load(package: Path, label: str) -> list[Module]:
    """Parse every Python file of a package and collect its string constants."""
    modules = [
        Module(label, path.relative_to(package).as_posix(), ast.parse(path.read_text()))
        for path in sorted(package.rglob("*.py"))
    ]
    shared: dict[str, str] = {}
    for _ in range(2):  # twice: constants built from other constants
        for module in modules:
            for node in module.tree.body:
                targets: list[tuple[str, ast.AST | None]] = []
                if isinstance(node, ast.Assign):
                    targets = [(ast.unparse(t), node.value) for t in node.targets]
                elif isinstance(node, ast.AnnAssign):
                    targets = [(ast.unparse(node.target), node.value)]
                elif isinstance(node, ast.ClassDef) and _is_enum(node):
                    targets = [
                        (f"{node.name}.{ast.unparse(t)}", item.value)
                        for item in node.body
                        if isinstance(item, ast.Assign)
                        for t in item.targets
                    ]
                for name, value in targets:
                    resolved = _resolve(value, module.env, shared)
                    if resolved is not None:
                        module.env[name] = resolved
                        shared.setdefault(name, resolved)
    for module in modules:
        module.env = {**shared, **module.env}
    return modules


def commit(repo: Path) -> str:
    """Return the checked-out commit of a git repository, from its files."""
    git = repo / ".git"
    head = (git / "HEAD").read_text().strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    if (git / ref).is_file():
        return (git / ref).read_text().strip()
    for line in (git / "packed-refs").read_text().splitlines():
        sha, _, name = line.partition(" ")
        if name == ref:
            return sha
    raise ValueError(f"No commit for {ref} in {repo}")


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _platform_of(base: str) -> str | None:
    """Return the platform a Home Assistant base class belongs to."""
    base = base.rsplit(".", 1)[-1]
    if base == "BaseNotificationService":
        return "notify"
    for suffix in ("Entity", "Device"):
        if base.endswith(suffix):
            platform = _camel_to_snake(base.removesuffix(suffix))
            platform = platform.removesuffix("_list")  # TodoListEntity
            if platform in PLATFORMS:
                return platform
    return None


def _is_noise(statement: ast.stmt) -> bool:
    """Whether a statement does nothing: ``pass``, a docstring or a log line."""
    if isinstance(statement, ast.Pass):
        return True
    if not isinstance(statement, ast.Expr):
        return False
    value = statement.value
    return isinstance(value, ast.Constant) or (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr in LOG_METHODS
    )


def _strings(node: ast.AST, env: dict[str, str]) -> list[str]:
    """Return the strings of a constant or of a tuple/list/set of constants."""
    items = node.elts if isinstance(node, (ast.Tuple, ast.List, ast.Set)) else [node]
    return [value for item in items if (value := _resolve(item, env)) is not None]


def _compared(test: ast.AST, variable: str, env: dict[str, str]) -> list[str]:
    """Return the strings ``variable`` is compared with (``==`` or ``in``)."""
    if not (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and re.search(variable, test.left.id)
        and isinstance(test.ops[0], (ast.Eq, ast.In))
    ):
        return []
    return _strings(test.comparators[0], env)


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
class Inventory:
    """The features of one competitor."""

    def __init__(self, prefix: str) -> None:
        """Start empty; ``prefix`` namespaces the feature ids."""
        self.prefix = prefix
        self.features: dict[str, dict[str, Any]] = {}
        self.ignored: dict[str, str] = {}

    def add(self, kind: str, name: str, source: str, **extra: Any) -> None:
        """Record a feature; the first place it is found wins."""
        feature = self.features.setdefault(
            f"{self.prefix}:{kind}:{name}",
            {"kind": kind, "name": name, "source": source},
        )
        for key, value in extra.items():
            if isinstance(value, list):
                feature[key] = sorted({*feature.get(key, []), *value})
            elif value:
                feature.setdefault(key, value)


def _classes(module: Module) -> dict[str, tuple[ast.ClassDef, str]]:
    """Return the entity classes of a module with their platform."""
    found: dict[str, tuple[ast.ClassDef, str]] = {}
    classes = [n for n in module.tree.body if isinstance(n, ast.ClassDef)]
    for _ in classes:  # until inheritance inside the module is settled
        for cls in classes:
            for base in map(ast.unparse, cls.bases):
                platform = _platform_of(base) or found.get(base, (None, None))[1]
                if platform:
                    found.setdefault(cls.name, (cls, platform))
    return found


def extract_entities(inventory: Inventory, module: Module) -> None:
    """Entity descriptions, or entity classes where a module has none."""
    classes = _classes(module)
    platform = module.name.removesuffix(".py")
    described = False
    dynamic = 0
    deprecated: set[int] = set()
    for node in module.tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if ast.unparse(target).startswith("DEPRECATED"):
                deprecated |= {id(n) for n in ast.walk(node)}
    for node in ast.walk(module.tree):
        if not (
            isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith("EntityDescription")
            and platform in PLATFORMS
        ):
            continue
        keywords = {k.arg: k.value for k in node.keywords}
        if "key" not in keywords:
            continue
        described = True
        key = _resolve(keywords["key"], module.env)
        if key is None:
            dynamic += 1
            key = DYNAMIC if dynamic == 1 else f"{DYNAMIC}{dynamic}"
        inventory.add(
            "entity",
            f"{platform}.{key}",
            module.ref(node),
            translation_key=_resolve(keywords.get("translation_key"), module.env),
            deprecated=id(node) in deprecated,
        )
    subclassed = {
        base for cls, _ in classes.values() for base in map(ast.unparse, cls.bases)
    }
    for name, (cls, cls_platform) in classes.items():
        if not described and name not in subclassed:
            inventory.add("entity", f"{cls_platform}.{name}", module.ref(cls))
        extract_class(inventory, module, cls, cls_platform)


def extract_class(
    inventory: Inventory, module: Module, cls: ast.ClassDef, platform: str
) -> None:
    """State attributes and event types of an entity class."""
    for item in cls.body:
        if isinstance(item, ast.Assign) and "_attr_event_types" in ast.unparse(
            item.targets[0]
        ):
            for event_type in _strings(item.value, module.env):
                inventory.add("event_type", event_type, module.ref(item))
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "extra_state_attributes"
        ):
            for key, node in _attribute_keys(item, module.env):
                inventory.add(
                    "attribute", f"{platform}.{cls.name}.{key}", module.ref(node)
                )
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Call)
            and ast.unparse(node.func).endswith("_trigger_event")
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Dict)
        ):
            for key in node.args[1].keys:
                if (name := _resolve(key, module.env)) is not None:
                    inventory.add("event_attribute", name, module.ref(node))


def _attribute_keys(
    function: ast.FunctionDef | ast.AsyncFunctionDef, env: dict[str, str]
) -> list[tuple[str, ast.AST]]:
    """Return the top-level keys an ``extra_state_attributes`` builds."""
    keys: list[tuple[str, ast.AST]] = []

    def of_dict(node: ast.AST | None) -> None:
        if isinstance(node, ast.Dict):
            keys.extend(
                (_resolve(key, env) or DYNAMIC, key) for key in node.keys if key
            )

    def visit(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # a helper builds the items of a list, not attributes
            if isinstance(statement, ast.Return):
                of_dict(statement.value)
            elif isinstance(statement, ast.Assign):
                target = statement.targets[0]
                if isinstance(target, ast.Name):
                    of_dict(statement.value)
                elif isinstance(target, ast.Subscript):
                    keys.append((_resolve(target.slice, env) or DYNAMIC, target))
            elif (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and ast.unparse(statement.value.func).endswith(".update")
                and statement.value.args
            ):
                of_dict(statement.value.args[0])
            for name in ("body", "orelse"):
                visit(getattr(statement, name, []))

    visit(function.body)
    return keys


def extract_strings(inventory: Inventory, package: Path, label: str) -> None:
    """Entity translation keys and config / options fields of ``strings.json``."""
    path = package / "strings.json"
    strings = json.loads(path.read_text())
    lines = path.read_text().splitlines()

    def line_of(key: str, after: str = "") -> int:
        start = next((i for i, text in enumerate(lines) if f'"{after}"' in text), 0)
        return (
            next(
                (i for i in range(start, len(lines)) if f'"{key}":' in lines[i]), start
            )
            + 1
        )

    for platform, keys in strings.get("entity", {}).items():
        for key in keys:
            inventory.add(
                "entity_key",
                f"{platform}.{key}",
                f"{label} strings.json:{line_of(key, platform)}",
            )
    for flow in ("config", "options"):
        for step, content in strings.get(flow, {}).get("step", {}).items():
            for key in content.get("data", {}):
                inventory.add(
                    "option",
                    key,
                    f"{label} strings.json:{line_of(key, step)}",
                    flows=[f"{flow}.{step}"],
                )


def extract_services(
    inventory: Inventory, package: Path, modules: list[Module], label: str
) -> None:
    """Actions and their fields: ``services.yaml`` plus the registered schemas."""
    path = package / "services.yaml"
    services = parse_yaml(path.read_text())
    for name, content in services.items():
        inventory.add("service", name, f"{label} services.yaml:{services.lines[name]}")
        fields = (content or {}).get("fields") or Node()
        for field_name, spec in fields.items():
            options = (((spec or {}).get("selector") or {}).get("select") or {}).get(
                "options"
            )
            inventory.add(
                "service_field",
                f"{name}.{field_name}",
                f"{label} services.yaml:{fields.lines[field_name]}",
                options=options if isinstance(options, list) else None,
            )
    for module in modules:
        schemas = {
            ast.unparse(node.targets[0]): node.value
            for node in module.tree.body
            if isinstance(node, ast.Assign) and "Schema" in ast.unparse(node.value)
        }
        for node in ast.walk(module.tree):
            # a registration names the action and its schema side by side:
            # ServiceDef(name=…, schema=…), (name, handler, schema), register(…)
            parts: list[ast.AST] = []
            if isinstance(node, ast.Call):
                parts = [*node.args, *(k.value for k in node.keywords)]
            elif isinstance(node, ast.Tuple):
                parts = list(node.elts)
            names = [
                value
                for part in parts
                if not isinstance(part, ast.Constant) or len(parts) > 1
                if (value := _resolve(part, module.env)) in services
                or (
                    value
                    and f"{inventory.prefix}:service:{value}" in inventory.features
                )
            ]
            used = [
                ast.unparse(p)
                for p in parts
                if isinstance(p, ast.Name) and p.id in schemas
            ]
            if len(names) != 1 or len(used) != 1 or not names[0]:
                # also: an action that is registered but missing in services.yaml
                if (
                    isinstance(node, ast.Call)
                    and ast.unparse(node.func).endswith("ServiceDef")
                    and (name := _resolve(_keyword(node, "name"), module.env))
                ):
                    inventory.add("service", name, module.ref(node))
                continue
            inventory.add("service", names[0], module.ref(node))
            for call in ast.walk(schemas[used[0]]):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("Required", "Optional", "Inclusive")
                    and call.args
                    and (key := _resolve(call.args[0], module.env))
                ):
                    inventory.add(
                        "service_field", f"{names[0]}.{key}", module.ref(call)
                    )


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def extract_flags(inventory: Inventory, module: Module) -> None:
    """Feature flags (``MediaPlayerEntityFeature.SEEK``…) and colour modes."""
    for node in ast.walk(module.tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and FLAG_ENUM.match(node.value.id)
            and node.attr.isupper()
        ):
            inventory.add("feature", f"{node.value.id}.{node.attr}", module.ref(node))


def extract_events(inventory: Inventory, module: Module) -> None:
    """Events fired on the Home Assistant bus."""
    for node in ast.walk(module.tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("async_fire", "fire")
            and ast.unparse(node.func.value).endswith("bus")
            and node.args
        ):
            name = _resolve(node.args[0], module.env)
            inventory.add("event", name or DYNAMIC, module.ref(node))


def extract_play_media(inventory: Inventory, module: Module) -> None:
    """Content types ``play_media`` handles and the options it reads."""
    for function in ast.walk(module.tree):
        if not (
            isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            and function.name == "async_play_media"
        ):
            continue
        aliases = {"media_type"}
        for node in ast.walk(function):
            for media_type in _compared(node, "^media_type$", module.env):
                inventory.add("play_media", media_type, module.ref(node))
            if isinstance(node, ast.Assign) and any(
                isinstance(n, ast.Name) and n.id == "media_type"
                for n in ast.walk(node.value)
            ):
                aliases |= {ast.unparse(t) for t in node.targets}
        for node in ast.walk(function):
            # the type itself handed on: it is the music provider
            if (
                isinstance(node, ast.Call)
                and not (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in LOG_METHODS
                )
                and any(
                    isinstance(arg, ast.Name) and arg.id in aliases
                    for arg in (*node.args, *(k.value for k in node.keywords))
                )
                and "isinstance" not in ast.unparse(node.func)
            ):
                inventory.add("play_media", DYNAMIC, module.ref(node))
                break
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Call):
            continue
        function = ast.unparse(node.func)
        if function == "kwargs.get" and node.args:
            if (key := _resolve(node.args[0], module.env)) is not None:
                inventory.add("play_media_option", key, module.ref(node))
        elif (
            function.endswith("safe_get")
            and len(node.args) > 1
            and ast.unparse(node.args[0]) == "kwargs"
        ):
            path = ".".join(_strings(node.args[1], module.env))
            inventory.add("play_media_option", path, module.ref(node))


def extract_notify(inventory: Inventory, module: Module) -> None:
    """What a legacy ``notify`` service accepts: types, data keys, targets."""
    if not any(
        "BaseNotificationService" in ast.unparse(base)
        for node in module.tree.body
        if isinstance(node, ast.ClassDef)
        for base in node.bases
    ):
        return
    for node in ast.walk(module.tree):
        if isinstance(node, ast.If):
            for notify_type in _compared(node.test, "type$", module.env):
                inventory.add("notify_type", notify_type, module.ref(node))
        key: ast.AST | None = None
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "data.get":
            key = node.args[0] if node.args else None
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "data":
            key = node.slice
        if (name := _resolve(key, module.env)) is not None:
            inventory.add("notify_data", name, module.ref(node))
        text = _resolve(node, {}) if isinstance(node, ast.Constant) else None
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value
                for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
        if text and text.startswith("last_called"):
            inventory.add("notify_target", "last_called", module.ref(node))


def extract_push(inventory: Inventory, module: Module, *, library: bool) -> None:
    """Push commands with a handler that does more than log them.

    Two shapes: ``if command == "PUSH_…"`` in an integration, and
    ``match event_type`` wherever the push stream is dispatched.
    """

    def record(commands: list[str], body: list[ast.stmt], node: ast.AST) -> None:
        for command in commands:
            if all(_is_noise(statement) for statement in body):
                inventory.ignored.setdefault(f"push:{command}", module.ref(node))
            else:
                inventory.add("push", command, module.ref(node))

    for node in ast.walk(module.tree):
        if isinstance(node, ast.If) and not library:
            record(_compared(node.test, "^command$", module.env), node.body, node)
        elif isinstance(node, ast.Match) and ast.unparse(node.subject) == "event_type":
            for case in node.cases:
                pattern = case.pattern
                if isinstance(pattern, ast.MatchValue):
                    record(_strings(pattern.value, module.env), case.body, pattern)


def extract_variants(inventory: Inventory, module: Module) -> None:
    """Sensor types listed in a ``…_DEVICE_CLASS`` table (one entity each)."""
    for node in module.tree.body:
        if (
            isinstance(node, ast.Assign)
            and ast.unparse(node.targets[0]).endswith("_DEVICE_CLASS")
            and isinstance(node.value, ast.Dict)
        ):
            for key in node.value.keys:
                if (name := _resolve(key, module.env)) is not None:
                    inventory.add("sensor_type", name, module.ref(key))


# Entry points Home Assistant defines for a config flow, and for diagnostics.
FLOW_STEPS = {
    "async_step_user": "user",
    "async_step_reauth": "reauth",
    "async_step_reconfigure": "reconfigure",
    "async_step_import": "import",
    "async_step_dhcp": "dhcp",
    "async_step_zeroconf": "zeroconf",
    "async_step_ssdp": "ssdp",
    "async_get_options_flow": "options",
}
DIAGNOSTICS = {
    "async_get_config_entry_diagnostics": "config_entry",
    "async_get_device_diagnostics": "device",
}


def extract_entry_points(inventory: Inventory, module: Module) -> None:
    """Config flow sources and diagnostics a module implements."""
    for node in ast.walk(module.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if module.name == "config_flow.py" and node.name in FLOW_STEPS:
                inventory.add("flow", FLOW_STEPS[node.name], module.ref(node))
            if module.name == "diagnostics.py" and node.name in DIAGNOSTICS:
                inventory.add("diagnostics", DIAGNOSTICS[node.name], module.ref(node))


def extract(
    prefix: str,
    package: Path,
    label: str,
    library: Path | None = None,
    lib_label: str = "",
) -> Inventory:
    """Build the inventory of one integration (and the push side of its library)."""
    inventory = Inventory(prefix)
    modules = load(package, label)
    library_modules = load(library, lib_label) if library else []
    # the integration resolves names it imports from its library
    for module in modules:
        for library_module in library_modules:
            module.env = {**library_module.env, **module.env}
    for module in modules:
        stem = module.name.removesuffix(".py")
        if stem in PLATFORMS:
            inventory.add("platform", stem, module.ref(1))
        extract_entities(inventory, module)
        extract_flags(inventory, module)
        extract_events(inventory, module)
        extract_variants(inventory, module)
        extract_entry_points(inventory, module)
        if stem == "media_player":
            extract_play_media(inventory, module)
        if stem == "notify":
            extract_notify(inventory, module)
    extract_strings(inventory, package, label)
    extract_services(inventory, package, modules, label)
    for module in modules:
        extract_push(inventory, module, library=False)
    for module in library_modules:
        extract_push(inventory, module, library=True)
    # a command one file ignores and another handles is handled
    for name in [n for n in inventory.ignored if f"{prefix}:{n}" in inventory.features]:
        del inventory.ignored[name]
    return inventory


def _version(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text())
    project = data.get("project") or data.get("tool", {}).get("poetry", {})
    return str(project.get("version", ""))


def build(src_amp: Path, src_core: Path) -> dict[str, Any]:
    """Return the whole fixture."""
    amp_repo, alexapy = src_amp / "alexa_media_player", src_amp / "alexapy"
    core_repo, aio = src_core / "core", src_core / "aioamazondevices"
    amp_package = amp_repo / "custom_components" / "alexa_media"
    core_package = core_repo / "homeassistant" / "components" / "alexa_devices"
    amp = extract("amp", amp_package, "AMP", alexapy / "alexapy", "apy")
    core = extract(
        "core", core_package, "core", aio / "src" / "aioamazondevices", "aio"
    )
    features = dict(sorted({**amp.features, **core.features}.items()))

    def kinds(prefix: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for key, feature in features.items():
            if key.startswith(f"{prefix}:"):
                counts[feature["kind"]] = counts.get(feature["kind"], 0) + 1
        return dict(sorted(counts.items()))

    return {
        "generated_by": "scripts/extract_competitor_features.py",
        "competitors": {
            "amp": {
                "name": "Alexa Media Player",
                "version": json.loads((amp_package / "manifest.json").read_text())[
                    "version"
                ],
                "commit": commit(amp_repo),
                "library": "alexapy",
                "library_version": _version(alexapy / "pyproject.toml"),
                "library_commit": commit(alexapy),
                "feature_count": sum(kinds("amp").values()),
                "features_by_kind": kinds("amp"),
            },
            "core": {
                "name": "Alexa Devices (Home Assistant core)",
                "version": _version(core_repo / "pyproject.toml"),
                "commit": commit(core_repo),
                "library": "aioamazondevices",
                "library_version": _version(aio / "pyproject.toml"),
                "library_commit": commit(aio),
                "feature_count": sum(kinds("core").values()),
                "features_by_kind": kinds("core"),
            },
        },
        "features": features,
        # push commands the competitor names only to log or drop them
        "ignored": dict(
            sorted(
                {
                    **{f"amp:{k}": v for k, v in amp.ignored.items()},
                    **{f"core:{k}": v for k, v in core.ignored.items()},
                }.items()
            )
        ),
    }


def main() -> None:
    """Write the fixture."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src_amp", type=Path)
    parser.add_argument("src_core", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    fixture = build(args.src_amp, args.src_core)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
    for competitor in fixture["competitors"].values():
        print(f"{competitor['name']}: {competitor['feature_count']} features")


if __name__ == "__main__":
    main()

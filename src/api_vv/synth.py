"""Seeded value synthesis: strings matching a regex and random schema-valid instances."""

from __future__ import annotations

import importlib
import math
import random
import re
import string
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from api_vv.models import Schema

# CPython's own regex parser; stdlib, but private and unstubbed, hence the dynamic import.
_parser: Any = importlib.import_module("re._parser")

FORMATS = {
    "date": "2026-01-01",
    "date-time": "2026-01-01T00:00:00Z",
    "email": "test@example.invalid",
    "uuid": "00000000-0000-4000-8000-000000000001",
    "uri": "https://example.invalid/item",
    "hostname": "example.invalid",
    "ipv4": "192.0.2.1",
    "ipv6": "2001:db8::1",
}
ALPHABET = string.ascii_letters + string.digits
PRINTABLE = string.ascii_letters + string.digits + string.punctuation + " "
CATEGORIES = {
    "CATEGORY_DIGIT": string.digits,
    "CATEGORY_NOT_DIGIT": string.ascii_letters + string.punctuation,
    "CATEGORY_SPACE": " ",
    "CATEGORY_NOT_SPACE": ALPHABET + string.punctuation,
    "CATEGORY_WORD": ALPHABET + "_",
    "CATEGORY_NOT_WORD": string.punctuation.replace("_", "") + " ",
}
# Unbounded repeats (``*``, ``+``, ``{n,}``) add at most this many extra items.
REPEAT_SLACK = 4
MAX_DEPTH = 8


class Unsupported(Exception):
    """The regex uses a construct the sampler does not synthesize (lookarounds)."""


def _in_class(char: str, items: list[tuple[Any, Any]]) -> bool:
    for op, arg in items:
        name = str(op)
        if name == "LITERAL" and char == chr(arg):
            return True
        if name == "RANGE" and arg[0] <= ord(char) <= arg[1]:
            return True
        if name == "CATEGORY" and char in CATEGORIES.get(str(arg), ""):
            return True
    return False


def _class_char(items: list[tuple[Any, Any]], rng: random.Random | None) -> str:
    negated = bool(items) and str(items[0][0]) == "NEGATE"
    body = items[1:] if negated else items
    if negated:
        choices = [char for char in PRINTABLE if not _in_class(char, body)]
    else:
        choices = []
        for op, arg in body:
            name = str(op)
            if name == "LITERAL":
                choices.append(chr(arg))
            elif name == "RANGE":
                choices.extend(chr(code) for code in range(arg[0], min(arg[1], arg[0] + 94) + 1))
            elif name == "CATEGORY":
                choices.extend(CATEGORIES.get(str(arg), ""))
            else:
                raise Unsupported(name)
    if not choices:
        raise Unsupported("empty character class")
    return rng.choice(choices) if rng else choices[0]


def _emit(nodes: Any, rng: random.Random | None, groups: dict[int, str]) -> str:
    out: list[str] = []
    for op, arg in nodes:
        name = str(op)
        if name == "LITERAL":
            out.append(chr(arg))
        elif name == "NOT_LITERAL":
            choices = [char for char in ALPHABET if ord(char) != arg]
            out.append(rng.choice(choices) if rng else choices[0])
        elif name == "ANY":
            out.append(rng.choice(ALPHABET) if rng else "a")
        elif name == "IN":
            out.append(_class_char(arg, rng))
        elif name in {"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"}:
            low, high, sub = arg
            high = min(high, low + REPEAT_SLACK)
            count = rng.randint(low, high) if rng else low
            out.extend(_emit(sub, rng, groups) for _ in range(count))
        elif name == "SUBPATTERN":
            group, _add_flags, _del_flags, sub = arg
            text = _emit(sub, rng, groups)
            if group is not None:
                groups[group] = text
            out.append(text)
        elif name == "ATOMIC_GROUP":
            out.append(_emit(arg, rng, groups))
        elif name == "BRANCH":
            alternatives = arg[1]
            out.append(_emit(rng.choice(alternatives) if rng else alternatives[0], rng, groups))
        elif name == "GROUPREF":
            out.append(groups.get(arg, ""))
        elif name == "AT":
            continue
        else:
            raise Unsupported(name)
    return "".join(out)


def regex_example(pattern: str, rng: random.Random | None = None) -> str | None:
    """A string ``re.search`` accepts; minimal choices without ``rng``. ``None`` if unsupported.

    JSON Schema patterns are ECMA-262 and unanchored; Python's dialect agrees on the common
    subset, and the final ``re.search`` rejects anything the two disagree on.
    """
    try:
        text = _emit(_parser.parse(pattern).data, rng, {})
        return text if re.search(pattern, text) else None
    except (Unsupported, re.error, RecursionError):
        return None


def is_valid(value: Any, schema: Schema) -> bool:
    return Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)


def _number(schema: dict[str, Any], integer: bool, rng: random.Random) -> int | float:
    low = schema.get("minimum", -math.inf)
    high = schema.get("maximum", math.inf)
    if "exclusiveMinimum" in schema:
        low = max(low, schema["exclusiveMinimum"] + (1 if integer else 1e-3))
    if "exclusiveMaximum" in schema:
        high = min(high, schema["exclusiveMaximum"] - (1 if integer else 1e-3))
    if math.isinf(low) and math.isinf(high):
        low, high = -1000, 1000
    elif math.isinf(low):
        low = high - 1000
    elif math.isinf(high):
        high = low + 1000
    step = schema.get("multipleOf")
    if step:
        first, last = math.ceil(low / step), math.floor(high / step)
        if first > last:
            raise Unsupported("no multiple in range")
        value = rng.randint(first, last) * step
        return int(value) if integer else value
    if integer:
        first, last = math.ceil(low), math.floor(high)
        if first > last:
            raise Unsupported("empty integer range")
        return rng.randint(first, last)
    return round(rng.uniform(low, high), 3)


def _string(schema: dict[str, Any], rng: random.Random) -> str:
    if schema.get("format") in FORMATS:
        return FORMATS[schema["format"]]
    if "pattern" in schema:
        found = regex_example(schema["pattern"], rng)
        if found is None:
            raise Unsupported("pattern")
        return found
    low = schema.get("minLength", 0)
    high = min(schema.get("maxLength", low + 12), low + 12)
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(low, max(low, high))))


def _instance(schema: Schema, rng: random.Random, depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise Unsupported("schema too deep")
    if schema is True:
        return rng.choice([0, "x", True, None])
    if schema is False:
        raise Unsupported("false schema")
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return rng.choice(schema["enum"])
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            return _instance(rng.choice(schema[key]), rng, depth + 1)
    if "allOf" in schema:
        parts = [_instance(part, rng, depth + 1) for part in schema["allOf"]]
        if all(isinstance(part, dict) for part in parts):
            return {key: value for part in parts for key, value in part.items()}
        return parts[0]
    declared = schema.get("type", "object" if "properties" in schema else "string")
    kind = rng.choice(declared) if isinstance(declared, list) else declared
    if kind == "object":
        result = {}
        required = set(schema.get("required", []))
        for name, prop in schema.get("properties", {}).items():
            if isinstance(prop, dict) and prop.get("readOnly"):
                continue
            if name in required or rng.random() < 0.5:
                result[name] = _instance(prop, rng, depth + 1)
        return result
    if kind == "array":
        low = schema.get("minItems", 0)
        high = min(schema.get("maxItems", low + 3), low + 3)
        count = rng.randint(low, max(low, high))
        items: list[Any] = []
        for _ in range(count * 4 if schema.get("uniqueItems") else count):
            item = _instance(schema.get("items", {}), rng, depth + 1)
            if not (schema.get("uniqueItems") and item in items):
                items.append(item)
            if len(items) == count:
                break
        return items
    if kind in {"integer", "number"}:
        return _number(schema, kind == "integer", rng)
    if kind == "boolean":
        return rng.random() < 0.5
    if kind == "null":
        return None
    return _string(schema, rng)


def random_instance(schema: Schema, rng: random.Random, attempts: int = 10) -> tuple[bool, Any]:
    """``(True, value)`` with a random value that validates, else ``(False, None)``."""
    for _ in range(attempts):
        try:
            value = _instance(schema, rng, 0)
        except Unsupported:
            return False, None
        if is_valid(value, schema):
            return True, value
    return False, None

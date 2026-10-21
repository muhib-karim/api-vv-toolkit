"""Contract drift between two parsed specs, classified from an existing client's point of view.

Requests are what clients already send: anything the new contract rejects that the old one
accepted is breaking. Responses are what clients already handle: anything the new contract may
return that the old one ruled out, or no longer guarantees, is breaking. A schema change this
module cannot reason about is reported as breaking, so the gate fails closed.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from api_vv.models import Model, Operation, Parameter, Schema, Spec

Direction = Literal["request", "response"]
Format = Literal["text", "json", "md"]

LOWER_BOUNDS = (
    "minimum",
    "exclusiveMinimum",
    "minLength",
    "minItems",
    "minProperties",
    "minContains",
)
UPPER_BOUNDS = (
    "maximum",
    "exclusiveMaximum",
    "maxLength",
    "maxItems",
    "maxProperties",
    "maxContains",
)
EXACT = ("pattern", "format", "const")
ANNOTATIONS = {
    "title",
    "description",
    "example",
    "examples",
    "default",
    "deprecated",
    "readOnly",
    "writeOnly",
    "$comment",
    "externalDocs",
    "xml",
    "discriminator",
    "contentMediaType",
    "contentEncoding",
}
HANDLED = {
    "type",
    "enum",
    "properties",
    "required",
    "items",
    "additionalProperties",
    "uniqueItems",
    "multipleOf",
    "allOf",
    "anyOf",
    "oneOf",
    *LOWER_BOUNDS,
    *UPPER_BOUNDS,
    *EXACT,
}


class Change(Model):
    rule: str
    breaking: bool
    operation: str
    where: str = ""
    detail: str


def _types(schema: dict[str, Any]) -> set[str] | None:
    declared = schema.get("type")
    if declared is None:
        return None
    return {declared} if isinstance(declared, str) else set(declared)


def _covers(wide: set[str] | None, narrow: set[str] | None) -> bool:
    """Whether every value of the ``narrow`` types is also one of the ``wide`` types."""
    if wide is None:
        return True
    if narrow is None:
        return False
    return all(kind in wide or (kind == "integer" and "number" in wide) for kind in narrow)


def compare_schema(
    old: Schema, new: Schema, where: str, direction: Direction, operation: str, out: list[Change]
) -> None:
    def emit(rule: str, breaking: bool, detail: str, at: str = where) -> None:
        out.append(
            Change(rule=rule, breaking=breaking, operation=operation, where=at, detail=detail)
        )

    def constraint(key: str, tighter: bool) -> None:
        verb = "tightened" if tighter else "relaxed"
        # Tighter requests reject old input; looser responses return values clients never saw.
        emit(f"{direction}-constraint-{verb}", tighter == (direction == "request"), f"{key} {verb}")

    if old == new:
        return
    if isinstance(old, bool) or isinstance(new, bool):
        emit("schema-changed-unanalysed", True, "boolean schema changed; review manually")
        return
    request = direction == "request"

    old_types, new_types = _types(old), _types(new)
    if old_types != new_types:
        shown = f"type {sorted(old_types or ['any'])} -> {sorted(new_types or ['any'])}"
        if request:
            if _covers(new_types, old_types):
                emit("request-type-widened", False, shown)
            else:
                emit("request-type-narrowed", True, shown)
        elif _covers(old_types, new_types):
            emit("response-type-narrowed", False, shown)
        else:
            emit("response-type-changed", True, shown)

    old_enum, new_enum = old.get("enum"), new.get("enum")
    if old_enum != new_enum:
        if old_enum is None or new_enum is None:
            constraint("enum", tighter=old_enum is None)
        else:
            removed = [value for value in old_enum if value not in new_enum]
            added = [value for value in new_enum if value not in old_enum]
            if removed:
                rule = "enum-value-removed" if request else "response-enum-value-removed"
                emit(rule, request, f"enum values removed: {json.dumps(removed)}")
            if added:
                rule = "enum-value-added" if request else "response-enum-value-added"
                emit(rule, not request, f"enum values added: {json.dumps(added)}")

    for key in (*LOWER_BOUNDS, *UPPER_BOUNDS, *EXACT, "multipleOf", "uniqueItems"):
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        if after is None or after is False:
            constraint(key, tighter=False)
        elif before is None or before is False:
            constraint(key, tighter=True)
        elif key in LOWER_BOUNDS:
            constraint(key, tighter=after > before)
        elif key in UPPER_BOUNDS:
            constraint(key, tighter=after < before)
        elif key == "multipleOf":
            constraint(key, tighter=before % after != 0)
        else:
            constraint(key, tighter=True)

    before_ap, after_ap = (
        old.get("additionalProperties", True),
        new.get("additionalProperties", True),
    )
    if isinstance(before_ap, dict) and isinstance(after_ap, dict):
        compare_schema(before_ap, after_ap, f"{where}{{*}}", direction, operation, out)
    elif before_ap != after_ap:
        tighter = after_ap is False or (isinstance(after_ap, dict) and before_ap is True)
        constraint("additionalProperties", tighter=tighter)

    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    old_required, new_required = set(old.get("required", [])), set(new.get("required", []))
    closed = new.get("additionalProperties") is False
    for name in old_props.keys() - new_props.keys():
        at = f"{where}.{name}"
        if request:
            emit("request-property-removed", closed, "property removed", at)
        else:
            emit("response-schema-narrowed", True, "property removed", at)
    for name in new_props.keys() - old_props.keys():
        at = f"{where}.{name}"
        if request and name in new_required:
            emit("request-property-required", True, "required property added", at)
        elif request:
            emit("request-property-added", False, "optional property added", at)
        else:
            emit("response-property-added", False, "property added", at)
    for name in sorted(old_props.keys() & new_props.keys()):
        at = f"{where}.{name}"
        compare_schema(old_props[name], new_props[name], at, direction, operation, out)
        if name in new_required - old_required:
            if request:
                emit("request-property-required", True, "property became required", at)
            else:
                emit("response-property-required", False, "property became required", at)
        elif name in old_required - new_required:
            if request:
                emit("request-property-optional", False, "property became optional", at)
            else:
                emit("response-schema-narrowed", True, "property no longer guaranteed", at)

    if "items" in old and "items" in new:
        compare_schema(old["items"], new["items"], f"{where}[]", direction, operation, out)
    elif old.get("items") != new.get("items"):
        constraint("items", tighter="items" in new)

    for key in ("allOf", "anyOf", "oneOf"):
        before_parts, after_parts = old.get(key), new.get(key)
        if before_parts == after_parts:
            continue
        if before_parts and after_parts and len(before_parts) == len(after_parts):
            for index, (left, right) in enumerate(zip(before_parts, after_parts, strict=True)):
                compare_schema(left, right, f"{where}.{key}[{index}]", direction, operation, out)
        else:
            emit("schema-changed-unanalysed", True, f"{key} changed; review manually")

    for key in sorted((old.keys() | new.keys()) - HANDLED - ANNOTATIONS):
        if not key.startswith("x-") and old.get(key) != new.get(key):
            emit("schema-changed-unanalysed", True, f"{key} changed; review manually")


def _template(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _param_key(param: Parameter, op: Operation) -> tuple[str, str]:
    # Renaming a path placeholder is not a contract change, so path parameters key by position.
    if param.location == "path":
        return "path", str(re.findall(r"\{([^}]+)\}", op.path).index(param.name))
    return param.location, param.name.lower() if param.location == "header" else param.name


def _alternatives(op: Operation) -> set[frozenset[str]]:
    return {frozenset(group) for group in op.security}


def compare_operation(old: Operation, new: Operation, out: list[Change]) -> None:
    label = f"{new.method} {new.path}"

    def emit(rule: str, breaking: bool, detail: str, where: str = "") -> None:
        out.append(
            Change(rule=rule, breaking=breaking, operation=label, where=where, detail=detail)
        )

    old_params = {_param_key(item, old): item for item in old.parameters}
    new_params = {_param_key(item, new): item for item in new.parameters}
    for key in sorted(old_params.keys() - new_params.keys()):
        emit("parameter-removed", False, "parameter removed", f"parameter {'.'.join(key)}")
    for key in sorted(new_params.keys() - old_params.keys()):
        param = new_params[key]
        where = f"parameter {param.location}.{param.name}"
        if param.required:
            emit("required-parameter-added", True, "required parameter added", where)
        else:
            emit("optional-parameter-added", False, "optional parameter added", where)
    for key in sorted(old_params.keys() & new_params.keys()):
        before, after = old_params[key], new_params[key]
        where = f"parameter {after.location}.{after.name}"
        if after.required and not before.required:
            emit("required-parameter-added", True, "optional parameter became required", where)
        elif before.required and not after.required:
            emit("parameter-became-optional", False, "parameter became optional", where)
        compare_schema(before.schema_, after.schema_, where, "request", label, out)

    if old.request_schema is None and new.request_schema is not None:
        if new.request_required:
            emit("request-body-required", True, "required request body added", "request body")
        else:
            emit("request-body-added", False, "optional request body added", "request body")
    elif old.request_schema is not None and new.request_schema is None:
        emit("request-body-removed", False, "request body no longer documented", "request body")
    elif old.request_schema is not None and new.request_schema is not None:
        if new.request_required and not old.request_required:
            emit("request-body-required", True, "request body became required", "request body")
        elif old.request_required and not new.request_required:
            emit("request-body-optional", False, "request body became optional", "request body")
        compare_schema(
            old.request_schema, new.request_schema, "request body", "request", label, out
        )

    for code in sorted(old.responses.keys() - new.responses.keys()):
        success = code.startswith("2") or code == "default"
        emit("response-status-removed", success, f"documented {code} response removed")
    for code in sorted(new.responses.keys() - old.responses.keys()):
        emit("response-status-added", False, f"documented {code} response added")
    for code in sorted(old.responses.keys() & new.responses.keys()):
        old_response, new_response = old.responses[code], new.responses[code]
        for media in sorted(old_response.content.keys() - new_response.content.keys()):
            emit("response-media-type-removed", True, f"{media} removed", f"response {code}")
        for media in sorted(new_response.content.keys() - old_response.content.keys()):
            emit("response-media-type-added", False, f"{media} added", f"response {code}")
        for media in sorted(old_response.content.keys() & new_response.content.keys()):
            where = f"response {code} {media}"
            compare_schema(
                old_response.content[media],
                new_response.content[media],
                where,
                "response",
                label,
                out,
            )
        old_headers = {name.lower(): item for name, item in old_response.headers.items()}
        new_headers = {name.lower(): item for name, item in new_response.headers.items()}
        for name in sorted(old_headers.keys() - new_headers.keys()):
            required = old_headers[name].required
            emit("response-header-removed", required, "header removed", f"response {code} {name}")
        for name in sorted(new_headers.keys() - old_headers.keys()):
            emit("response-header-added", False, "header added", f"response {code} {name}")
        for name in sorted(old_headers.keys() & new_headers.keys()):
            where = f"response {code} header {name}"
            compare_schema(
                old_headers[name].schema_, new_headers[name].schema_, where, "response", label, out
            )

    if new.auth_required and not old.auth_required:
        emit("security-added", True, "operation now requires authentication")
    elif old.auth_required and not new.auth_required:
        emit("security-removed", False, "operation no longer requires authentication")
    elif old.auth_required:
        before_alts, after_alts = _alternatives(old), _alternatives(new)
        if before_alts - after_alts:
            emit("security-changed", True, "an accepted security requirement was removed")
        elif after_alts - before_alts:
            emit("security-alternative-added", False, "a security alternative was added")


def diff_specs(old: Spec, new: Spec) -> list[Change]:
    def keyed(spec: Spec) -> dict[str, Operation]:
        return {f"{op.method} {_template(op.path)}": op for op in spec.operations.values()}

    before, after = keyed(old), keyed(new)
    old_paths = {_template(op.path) for op in old.operations.values()}
    new_paths = {_template(op.path) for op in new.operations.values()}
    changes: list[Change] = []
    for key in before.keys() - after.keys():
        op = before[key]
        gone = _template(op.path) not in new_paths
        changes.append(
            Change(
                rule="path-removed" if gone else "operation-removed",
                breaking=True,
                operation=f"{op.method} {op.path}",
                detail="path removed" if gone else "operation removed",
            )
        )
    for key in after.keys() - before.keys():
        op = after[key]
        new_path = _template(op.path) not in old_paths
        changes.append(
            Change(
                rule="path-added" if new_path else "operation-added",
                breaking=False,
                operation=f"{op.method} {op.path}",
                detail="path added" if new_path else "operation added",
            )
        )
    for key in before.keys() & after.keys():
        compare_operation(before[key], after[key], changes)
    return sorted(
        changes, key=lambda item: (not item.breaking, item.operation, item.where, item.rule)
    )


def summary(changes: list[Change]) -> str:
    breaking = sum(item.breaking for item in changes)
    return f"{breaking} breaking, {len(changes) - breaking} non-breaking"


def render(changes: list[Change], fmt: Format) -> str:
    if fmt == "json":
        breaking = sum(item.breaking for item in changes)
        payload = {
            "breaking": breaking,
            "non_breaking": len(changes) - breaking,
            "changes": [item.model_dump() for item in changes],
        }
        return json.dumps(payload, indent=2) + "\n"
    if not changes:
        return "No contract changes.\n"
    if fmt == "md":

        def cell(value: str) -> str:
            return value.replace("|", "\\|")

        rows = [
            "| Severity | Rule | Operation | Where | Detail |",
            "| --- | --- | --- | --- | --- |",
            *(
                f"| {'**breaking**' if item.breaking else 'non-breaking'} | `{item.rule}` | "
                f"`{cell(item.operation)}` | {cell(item.where)} | {cell(item.detail)} |"
                for item in changes
            ),
        ]
        return "\n".join(rows) + f"\n\n{summary(changes)}\n"
    lines = [
        f"{'BREAKING' if item.breaking else 'non-breaking':<12}  {item.rule:<29}  "
        f"{item.operation}  {item.where + ': ' if item.where else ''}{item.detail}"
        for item in changes
    ]
    return "\n".join(lines) + f"\n\n{summary(changes)}\n"

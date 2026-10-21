"""Deterministic schema-derived cases with explicit, structural trace links."""

from __future__ import annotations

import copy
import math
import random
import re
from collections.abc import Callable, Iterator
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

from api_vv.io import fingerprint
from api_vv.models import Case, Operation, Parameter, Plan, Requirements, Schema, Spec
from api_vv.spec import validate_requirements
from api_vv.synth import FORMATS, random_instance, regex_example

MAX_PROPERTY_CASES = 100


def valid(value: Any, schema: Schema) -> bool:
    return Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)


def sample(schema: Schema) -> Any:
    """Prefer authored examples; unsupported synthesis becomes a review case."""
    if isinstance(schema, bool):
        return None
    for key in ("example", "default", "const"):
        if key in schema:
            return copy.deepcopy(schema[key])
    for key in ("examples", "enum"):
        if schema.get(key):
            return copy.deepcopy(schema[key][0])
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            return sample(schema[key][0])
    if "allOf" in schema:
        parts = [sample(part) for part in schema["allOf"]]
        if all(isinstance(part, dict) for part in parts):
            return {key: value for part in parts for key, value in part.items()}
        return parts[0]
    kind = schema.get("type", "object" if "properties" in schema else "string")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), "null")
    if kind == "object":
        return {
            name: sample(prop)
            for name, prop in schema.get("properties", {}).items()
            if not (isinstance(prop, dict) and prop.get("readOnly"))
        }
    if kind == "array":
        count = max(schema.get("minItems", 0), 1)
        if count > 1000:
            raise ValueError("schema synthesis limit: minItems exceeds 1000; supply an example")
        return [sample(schema.get("items", {})) for _ in range(count)]
    if kind in {"integer", "number"}:
        value = schema.get("minimum", 0)
        if "exclusiveMinimum" in schema:
            value = schema["exclusiveMinimum"] + 1
        if "maximum" in schema:
            value = min(value, schema["maximum"])
        if "exclusiveMaximum" in schema:
            value = min(value, schema["exclusiveMaximum"] - 1)
        if "multipleOf" in schema:
            value = math.ceil(value / schema["multipleOf"]) * schema["multipleOf"]
        return int(value) if kind == "integer" else value
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    if schema.get("format") in FORMATS:
        return FORMATS[schema["format"]]
    if "pattern" in schema:
        # Minimal match first, then a few seeded tries to also satisfy length bounds.
        candidates = [regex_example(schema["pattern"])]
        rng = random.Random(schema["pattern"])
        candidates += [regex_example(schema["pattern"], rng) for _ in range(20)]
        for candidate in candidates:
            if candidate is not None and valid(candidate, schema):
                return candidate
    length = max(schema.get("minLength", 1), 1)
    length = min(length, schema.get("maxLength", length))
    if length > 10000:
        raise ValueError("schema synthesis limit: minLength exceeds 10000; supply an example")
    return "x" * length


def mutations(value: Any, schema: Schema, path: str) -> Iterator[tuple[Any, str]]:
    if isinstance(schema, bool):
        return
    # Negative type is chosen by validation, including nullable union types.
    wrong_values: tuple[Any, ...] = ("wrong", 1, True, None, {}, [])
    for wrong in wrong_values:
        declared = schema.get("type")
        if declared and not valid(wrong, {"type": declared}):
            yield wrong, f"wrong-type:{path}"
            break
    if "enum" in schema:
        wrong_enum = "__outside_enum__"
        while wrong_enum in schema["enum"]:
            wrong_enum += "_"
        yield wrong_enum, f"enum:{path}"
    if isinstance(value, str):
        for bound in ("minLength", "maxLength"):
            if bound in schema:
                size = schema[bound]
                if size > 10000:
                    continue
                for offset, label in ((-1, "below"), (0, "at"), (1, "above")):
                    if size + offset >= 0:
                        yield "x" * (size + offset), f"boundary:{path}:{bound}:{label}"
    if isinstance(value, str) and isinstance(schema.get("pattern"), str):
        pattern = schema["pattern"]
        low, high = schema.get("minLength", 0), schema.get("maxLength", 10000)
        sizes = sorted({max(low, 1), min(max(low, 1), high), len(value)})
        candidates = [char * size for size in sizes for char in "!0a- "] + [""]
        misses = [item for item in candidates if not re.search(pattern, item)]
        # Prefer a value that breaks only the pattern, not the length bounds as well.
        in_bounds = [item for item in misses if low <= len(item) <= high]
        if misses:
            yield (in_bounds or misses)[0], f"pattern:{path}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for bound in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            if bound in schema:
                step = schema.get("multipleOf", 1)
                for offset, label in ((-1, "below"), (0, "at"), (1, "above")):
                    yield schema[bound] + offset * step, f"boundary:{path}:{bound}:{label}"
    if isinstance(value, list):
        for bound in ("minItems", "maxItems"):
            if bound in schema and schema[bound] <= 1000:
                for offset, label in ((-1, "below"), (0, "at"), (1, "above")):
                    size = schema[bound] + offset
                    if size >= 0:
                        yield (
                            [sample(schema.get("items", {})) for _ in range(size)],
                            (f"boundary:{path}:{bound}:{label}"),
                        )
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name in value:
                changed = copy.deepcopy(value)
                del changed[name]
                yield changed, f"required:{path + '.' if path else ''}{name}"
        if schema.get("additionalProperties") is False:
            changed = copy.deepcopy(value)
            key = "__unexpected__"
            while key in schema.get("properties", {}):
                key += "_"
            changed[key] = True
            yield changed, f"additional-properties:{path or 'body'}"
        for name, prop in schema.get("properties", {}).items():
            if name not in value:
                continue
            for replacement, check in mutations(
                value[name], prop, f"{path + '.' if path else ''}{name}"
            ):
                changed = copy.deepcopy(value)
                changed[name] = replacement
                yield changed, check


def matches(case: Case, operation_id: str, responses: list[str], checks: list[str]) -> bool:
    return (
        case.operation_id == operation_id
        and case.expected_status in responses
        and (not checks or bool(set(case.checks) & set(checks)))
    )


def trace_case(case: Case, requirements: Requirements) -> None:
    case.requirement_ids = sorted(
        requirement.id
        for requirement in requirements.requirements
        if requirement.verification_method in {"test", "demonstration"}
        and any(
            matches(case, cover.operation_id, cover.responses, cover.checks)
            for cover in requirement.covers
        )
    )


def case_problems(case: Case, spec: Spec, *, strict_parameters: bool = False) -> list[str]:
    """Validate request shape; negative cases may intentionally violate body schemas."""
    op = spec.operations.get(case.operation_id)
    if op is None:
        return ["unknown operation"]
    errors: list[str] = []
    if case.expected_status not in op.responses:
        errors.append("undocumented expected response")
    declared: dict[tuple[str, str], Parameter] = {
        (param.location, param.name): param for param in op.parameters
    }
    for location, values in case.parameters.items():
        for name, value in values.items():
            param = declared.get((location, name))
            if param is None:
                errors.append(f"unknown parameter: {location}.{name}")
            elif (strict_parameters or not case.negative) and not valid(value, param.schema_):
                errors.append(f"invalid parameter: {location}.{name}")
            if isinstance(value, (dict, list)):
                errors.append(f"non-scalar parameter unsupported: {location}.{name}")
            if location == "path" and (value is None or str(value) in {"", ".", ".."}):
                errors.append(f"unsafe path parameter: {name}")
    for param in op.parameters:
        missing = param.required and param.name not in case.parameters.get(param.location, {})
        if missing and (param.location == "path" or strict_parameters or not case.negative):
            errors.append(f"missing parameter: {param.location}.{param.name}")
    if case.has_body:
        if op.request_schema is None:
            errors.append("operation has no request body")
        elif not case.negative and not valid(case.body, op.request_schema):
            errors.append("invalid body requires negative=true")
    elif op.request_required and not case.negative:
        errors.append("required body is missing")
    return errors


def deduplicate(cases: list[Case]) -> list[Case]:
    merged: dict[str, Case] = {}
    for case in cases:
        key = fingerprint(case)
        # Unfinalized review templates have no established request fingerprint.
        if not case.enabled:
            key += ":review:" + case.expected_status
        if key not in merged:
            case.id = "TC-" + fingerprint(case)[:12]
            if not case.enabled:
                case.id += "-review-" + case.expected_status
            merged[key] = case
            continue
        existing = merged[key]
        if existing.expected_status != case.expected_status or existing.negative != case.negative:
            raise ValueError(f"conflicting expectations for request {existing.id}")
        existing.checks = sorted(set(existing.checks + case.checks))
        existing.generators = sorted(set(existing.generators + case.generators))
        existing.requirement_ids = sorted(set(existing.requirement_ids + case.requirement_ids))
    return list(merged.values())


def operation_cases(
    op: Operation, spec: Spec, *, rng: random.Random | None = None, property_count: int = 0
) -> list[Case]:
    success = next((code for code in op.responses if code.startswith("2")), None)
    error = next((code for code in ("422", "400", "4XX") if code in op.responses), None)
    base = Case(
        id="pending",
        name=f"{op.id}: happy path",
        operation_id=op.id,
        parameters={},
        body=sample(op.request_schema) if op.request_schema is not None else None,
        has_body=op.request_schema is not None,
        expected_status=success or next(iter(op.responses)),
        generators=["happy-path"],
        checks=["happy-path"],
    )
    for param in op.parameters:
        base.parameters.setdefault(param.location, {})[param.name] = (
            param.example if param.example is not None else sample(param.schema_)
        )
    problems = case_problems(base, spec)
    if problems or success is None:
        base.enabled = False
        base.review_reason = "; ".join(problems) or "no documented success response"
    cases = [base]

    def add(changed: Case, check: str, invalid: bool, generator: str) -> None:
        changed.name = f"{op.id}: {check}"
        changed.checks = [check]
        changed.generators = [generator]
        changed.negative = invalid
        changed.expected_status = (error if invalid else success) or base.expected_status
        if invalid and error is None:
            changed.enabled = False
            changed.review_reason = "no documented validation-error response; review expectation"
        issues = case_problems(changed, spec)
        if issues:
            changed.enabled = False
            changed.review_reason = "; ".join(issues)
        cases.append(changed)

    if base.enabled:
        if op.request_schema is not None:
            for body, check in mutations(base.body, op.request_schema, ""):
                changed = base.model_copy(deep=True)
                changed.body = body
                add(changed, check, not valid(body, op.request_schema), "schema-boundary")
            if op.request_required:
                changed = base.model_copy(deep=True)
                changed.has_body = False
                changed.body = None
                add(changed, "required:body", True, "required-omission")
        for param in op.parameters:
            value = base.parameters[param.location][param.name]
            for replacement, check in mutations(
                value, param.schema_, f"{param.location}.{param.name}"
            ):
                changed = base.model_copy(deep=True)
                changed.parameters[param.location][param.name] = replacement
                add(changed, check, not valid(replacement, param.schema_), "parameter-boundary")
            if param.required and param.location != "path":
                changed = base.model_copy(deep=True)
                del changed.parameters[param.location][param.name]
                add(changed, f"required:{param.location}.{param.name}", True, "required-omission")
    if base.enabled and rng is not None:
        property_cases(op, base, rng, property_count, add)
    if op.auth_required:
        code = next((code for code in ("401", "403") if code in op.responses), None)
        variants: tuple[tuple[Literal["omit", "invalid"], str, str], ...] = (
            ("omit", "missing authentication", "auth-required"),
            ("invalid", "invalid credentials", "auth-invalid"),
        )
        for auth, label, check in variants:
            changed = base.model_copy(deep=True)
            changed.auth = auth
            changed.negative = True
            changed.name = f"{op.id}: {label}"
            changed.checks = [check]
            changed.generators = [check]
            changed.expected_status = code or base.expected_status
            if code is None:
                changed.enabled = False
                changed.review_reason = "no documented authentication-error response"
            cases.append(changed)
    covered = {case.expected_status for case in cases if case.enabled}
    for code in op.responses.keys() - covered:
        changed = base.model_copy(deep=True)
        changed.expected_status = code
        changed.enabled = False
        changed.negative = not code.startswith("2")
        changed.name = f"{op.id}: documented {code} (review required)"
        changed.generators = ["status-coverage"]
        changed.checks = ["documented-status"]
        changed.review_reason = "supply a request that triggers this response and enable the case"
        cases.append(changed)
    return cases


def property_cases(
    op: Operation,
    base: Case,
    rng: random.Random,
    count: int,
    add: Callable[[Case, str, bool, str], None],
) -> None:
    """Random schema-valid requests expect success; one random violation each expects 4xx.

    Path parameters keep the happy-path values: a random id would mostly exercise 404s.
    """
    params = [param for param in op.parameters if param.location != "path"]
    for index in range(1, count + 1):
        changed = base.model_copy(deep=True)
        if op.request_schema is not None:
            found, body = random_instance(op.request_schema, rng)
            if not found:
                continue
            changed.body = body
        for param in params:
            if param.required or rng.random() < 0.5:
                found, value = random_instance(param.schema_, rng)
                if found and not isinstance(value, (dict, list)):
                    changed.parameters.setdefault(param.location, {})[param.name] = value
            else:
                changed.parameters.get(param.location, {}).pop(param.name, None)
        add(changed, "property:valid", False, "property")
        changed.name = f"{op.id}: property valid #{index}"
    targets: list[tuple[str, Schema, Any]] = []
    if op.request_schema is not None and base.has_body:
        targets.append(("body", op.request_schema, base.body))
    targets += [(f"{p.location}.{p.name}", p.schema_, p) for p in params]
    for index in range(1, count + 1):
        if not targets:
            break
        label, schema, _ = rng.choice(targets)
        found, value = random_instance(schema, rng)
        path = "" if label == "body" else label
        broken = [item for item in mutations(value, schema, path) if not valid(item[0], schema)]
        if not found or not broken:
            continue
        bad, check = rng.choice(broken)
        changed = base.model_copy(deep=True)
        if label == "body":
            changed.body = bad
        else:
            location, name = label.split(".", 1)
            changed.parameters.setdefault(location, {})[name] = bad
        add(changed, "property:invalid", True, "property")
        changed.name = f"{op.id}: property invalid #{index} ({check.rstrip(':') or label})"


def generate(
    spec: Spec, requirements: Requirements, *, seed: int = 0, property_cases: int = 0
) -> Plan:
    validate_requirements(requirements, spec)
    if not 0 <= property_cases <= MAX_PROPERTY_CASES:
        raise ValueError(f"property_cases must be between 0 and {MAX_PROPERTY_CASES}")

    def rng(operation: Operation) -> random.Random | None:
        # Per-operation streams: adding an operation never reshuffles another one's values.
        return random.Random(f"{seed}:{operation.id}") if property_cases else None

    cases = deduplicate(
        [
            case
            for operation in spec.operations.values()
            for case in operation_cases(
                operation, spec, rng=rng(operation), property_count=property_cases
            )
        ]
    )
    for case in cases:
        trace_case(case, requirements)
    return Plan(
        spec=spec,
        requirements=requirements,
        cases=cases,
        seed=seed if property_cases else None,
        property_cases=property_cases,
    )

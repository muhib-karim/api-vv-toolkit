from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from api_vv.generate import valid
from api_vv.models import Requirements, Spec
from api_vv.spec import (
    normalize_schema,
    parse_document,
    parse_spec,
    resolve_refs,
    schema_for,
    validate_requirements,
)


def document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Example"},
        "paths": {
            "/items": {"get": {"operationId": "list", "responses": {"200": {"description": "ok"}}}}
        },
    }


def test_demo_model(spec: Spec, requirements: Requirements) -> None:
    assert len(spec.operations) == 5
    create = spec.operations["createWidget"]
    assert create.request_required
    assert isinstance(create.request_schema, dict)
    assert create.request_schema["properties"]["name"]["maxLength"] == 8
    assert spec.operations["secure"].auth_required
    assert not spec.operations["health"].auth_required
    validate_requirements(requirements, spec)


def test_json_and_fallback_id(tmp_path: Path) -> None:
    doc = document()
    del doc["paths"]["/items"]["get"]["operationId"]
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(doc))
    assert "GET /items" in parse_spec(path).operations


def test_ref_escape_arrays_siblings() -> None:
    doc: dict[str, Any] = {
        "openapi": "3.1.0",
        "defs": {"a/b~c": [{"type": "string", "maxLength": 8}]},
        "schema": {"$ref": "#/defs/a~1b~0c/0", "minLength": 2},
    }
    resolved = resolve_refs(doc)["schema"]
    assert valid("xx", resolved)
    assert not valid("x", resolved)
    assert not valid("x" * 9, resolved)
    doc["openapi"] = "3.0.3"
    assert resolve_refs(doc)["schema"] == {"type": "string", "maxLength": 8}


@pytest.mark.parametrize(
    "ref",
    ["https://invalid.test/spec.json", "other.yaml#/x", "#anchor", "#/missing", "#/items/4", 42],
)
def test_bad_refs(ref: Any) -> None:
    with pytest.raises(ValueError, match="local|unresolved"):
        resolve_refs({"items": [], "value": {"$ref": ref}})


def test_cycle_and_boolean_siblings() -> None:
    with pytest.raises(ValueError, match="recursive"):
        resolve_refs({"a": {"$ref": "#/a"}})
    with pytest.raises(ValueError, match="object target"):
        resolve_refs({"a": False, "b": {"$ref": "#/a", "type": "string"}})


def test_normalization_and_projection() -> None:
    schema = normalize_schema(
        {
            "type": "integer",
            "nullable": True,
            "enum": [2],
            "minimum": 1,
            "exclusiveMinimum": True,
            "exclusiveMaximum": False,
        },
        legacy=True,
    )
    assert valid(None, schema)
    assert valid(2, schema)
    assert not valid(1, schema)
    assert normalize_schema(False, legacy=False) is False
    projected = schema_for(
        {
            "type": "object",
            "required": ["id", "secret", "nested"],
            "properties": {
                "id": {"type": "integer", "readOnly": True},
                "secret": {"type": "string", "writeOnly": True},
                "nested": {"type": "array", "items": {"allOf": [True]}},
            },
        },
        "request",
    )
    assert isinstance(projected, dict)
    assert projected["required"] == ["secret", "nested"]
    response = schema_for(projected, "response")
    assert isinstance(response, dict)
    assert response["required"] == ["nested"]
    normalize_schema(
        {"$defs": {"x": True}, "oneOf": [False], "items": True, "additionalProperties": False},
        legacy=False,
    )
    for keyword in ("$id", "$schema", "$dynamicRef", "$recursiveRef"):
        with pytest.raises(ValueError, match="unsupported"):
            normalize_schema({keyword: "anything"}, legacy=False)


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"openapi": "2.0"}, "OpenAPI"),
        ({"paths": {}}, "no operations"),
        ({"paths": {"//evil": {}}}, "unsafe"),
        ({"paths": {"/a/../b": {}}}, "unsafe"),
    ],
)
def test_invalid_documents(patch: dict[str, Any], message: str) -> None:
    doc = document()
    doc.update(patch)
    with pytest.raises(ValueError, match=message):
        parse_document(doc)
    with pytest.raises(ValueError, match="OpenAPI"):
        parse_document([])


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("responses", {}, "no responses"),
        ("responses", {"600": {}}, "invalid response"),
        ("security", [{"missing": []}], "unknown security"),
        ("parameters", [{"name": "q", "in": "query", "style": "deepObject"}], "style"),
        ("parameters", [{"name": "q", "in": "query", "schema": {"type": "array"}}], "scalar"),
        ("parameters", [{"name": "q", "in": "query", "schema": "bad"}], "schema must"),
        ("parameters", [{"name": "id", "in": "path"}], "placeholders"),
        ("requestBody", {"content": {"text/plain": {}}}, "JSON request"),
    ],
)
def test_invalid_operations(field: str, value: Any, message: str) -> None:
    doc = document()
    doc["paths"]["/items"]["get"][field] = value
    with pytest.raises(ValueError, match=message):
        parse_document(doc)


def test_parameter_override_body_example_duplicate() -> None:
    doc = document()
    path = doc["paths"]["/items"]
    path["parameters"] = [{"in": "query", "name": "q", "example": 1}]
    path["get"]["parameters"] = [{"in": "query", "name": "q", "example": 2}]
    path["get"]["requestBody"] = {
        "content": {"application/problem+json": {"schema": {"type": "string"}, "example": "abc"}}
    }
    op = parse_document(doc).operations["list"]
    assert len(op.parameters) == 1 and op.parameters[0].example == 2
    assert isinstance(op.request_schema, dict) and op.request_schema["example"] == "abc"
    path["post"] = path["get"].copy()
    with pytest.raises(ValueError, match="duplicate"):
        parse_document(doc)


def test_requirements_errors(spec: Spec, requirements: Requirements) -> None:
    requirements.requirements[0].covers[0].responses = ["500"]
    with pytest.raises(ValueError, match="undocumented"):
        validate_requirements(requirements, spec)
    requirements.requirements[0].covers[0].operation_id = "unknown"
    with pytest.raises(ValueError, match="unknown operation"):
        validate_requirements(requirements, spec)
    requirements.requirements.append(requirements.requirements[0])
    with pytest.raises(ValidationError, match="unique"):
        Requirements.model_validate(requirements.model_dump())


def test_unquoted_yaml_dates_stay_strings(tmp_path: Path) -> None:
    """OpenAPI YAML is JSON-compatible: 2024-01-15 is text, not a ``datetime.date``."""
    path = tmp_path / "spec.yaml"
    path.write_text(
        "openapi: 3.0.3\n"
        "info: {title: t, version: '1'}\n"
        "paths:\n"
        "  /events:\n"
        "    post:\n"
        "      operationId: createEvent\n"
        "      parameters:\n"
        "        - {name: since, in: query, schema: {type: string, format: date},"
        " example: 2024-01-15}\n"
        "      requestBody:\n"
        "        content:\n"
        "          application/json:\n"
        "            schema:\n"
        "              type: object\n"
        "              properties:\n"
        "                at: {type: string, format: date-time, default: 2024-01-15T10:00:00Z}\n"
        "      responses:\n"
        "        '201': {description: ok}\n",
        encoding="utf-8",
    )
    op = parse_spec(path).operations["createEvent"]
    assert op.parameters[0].example == "2024-01-15"
    assert isinstance(op.request_schema, dict)
    assert op.request_schema["properties"]["at"]["default"] == "2024-01-15T10:00:00Z"


def test_tab_indented_json_is_read_as_json(tmp_path: Path) -> None:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(document(), indent="\t"), encoding="utf-8")
    assert list(parse_spec(path).operations) == ["list"]
    path.write_text("\ufeff" + json.dumps(document(), indent="\t"), encoding="utf-8")
    assert list(parse_spec(path).operations) == ["list"]  # a byte order mark is not content
    # A YAML document saved under a .json name keeps loading.
    path.write_text(
        "openapi: 3.1.0\ninfo: {title: t}\npaths:\n  /items:\n    get:\n"
        "      responses:\n        '200': {description: ok}\n",
        encoding="utf-8",
    )
    assert list(parse_spec(path).operations) == ["GET /items"]


@pytest.mark.parametrize(
    "patch, title",
    [
        ({"components": None}, "Example"),
        ({"components": {"securitySchemes": None}}, "Example"),
        ({"security": None}, "Example"),
        ({"webhooks": None}, "Example"),
        ({"info": None}, "API"),
    ],
)
def test_empty_sections_read_as_absent(patch: dict[str, Any], title: str) -> None:
    """``components:`` with nothing under it is YAML null, not a crash."""
    doc = document()
    doc.update(patch)
    assert parse_document(doc).title == title


def test_empty_paths_section_is_reported_clearly() -> None:
    doc = document()
    doc["paths"] = None
    with pytest.raises(ValueError, match="no operations"):
        parse_document(doc)

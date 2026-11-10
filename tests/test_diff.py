"""Contract drift between two OpenAPI documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from api_vv.cli import main
from api_vv.diff import Change, Direction, compare_schema, diff_specs, render
from api_vv.models import Header, Operation, Response, SecurityScheme, Spec
from api_vv.spec import parse_spec

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "diff"
V1 = str(FIXTURES / "v1.yaml")
COMPATIBLE = str(FIXTURES / "v2-compatible.yaml")
BREAKING = str(FIXTURES / "v2-breaking.yaml")


def rules(changes: list[Change], *, breaking: bool) -> set[tuple[str, str]]:
    return {(item.rule, item.operation) for item in changes if item.breaking is breaking}


def schema_changes(old: Any, new: Any, direction: Direction = "request") -> list[tuple[str, bool]]:
    found: list[Change] = []
    compare_schema(old, new, "body", direction, "POST /x", found)
    return [(item.rule, item.breaking) for item in found]


def test_compatible_revision_has_only_non_breaking_changes() -> None:
    changes = diff_specs(parse_spec(V1), parse_spec(COMPATIBLE))
    assert rules(changes, breaking=True) == set()
    assert rules(changes, breaking=False) == {
        ("path-added", "GET /orders/{id}/items"),
        ("optional-parameter-added", "GET /orders"),
        ("request-constraint-relaxed", "GET /orders"),
        ("enum-value-added", "POST /orders"),
        ("request-property-added", "POST /orders"),
        ("response-property-added", "GET /orders"),
        ("response-property-added", "POST /orders"),
        ("response-property-added", "GET /orders/{id}"),
        ("response-status-added", "POST /orders"),
        ("response-status-removed", "GET /orders/{id}"),
    }


def test_breaking_revision_reports_each_breaking_change() -> None:
    changes = diff_specs(parse_spec(V1), parse_spec(BREAKING))
    found = rules(changes, breaking=True)
    assert {
        ("path-removed", "GET /legacy"),
        ("operation-removed", "DELETE /orders/{orderId}"),
        ("required-parameter-added", "GET /orders"),
        ("request-property-required", "POST /orders"),
        ("enum-value-removed", "POST /orders"),
        ("request-constraint-tightened", "POST /orders"),
        ("response-status-removed", "POST /orders"),
        ("response-schema-narrowed", "GET /orders/{orderId}"),
        ("response-type-changed", "GET /orders/{orderId}"),
        ("security-added", "GET /orders/{orderId}"),
    } <= found
    narrowed = [
        item.where
        for item in changes
        if item.rule == "response-schema-narrowed" and item.operation == "GET /orders/{orderId}"
    ]
    assert sorted(narrowed) == [
        "response 200 application/json.status",
        "response 200 application/json.total",
    ]
    assert ("response-status-added", "POST /orders") in rules(changes, breaking=False)
    assert changes == sorted(
        changes, key=lambda item: (not item.breaking, item.operation, item.where, item.rule)
    )


def test_identical_specs_have_no_changes() -> None:
    spec = parse_spec(V1)
    assert diff_specs(spec, spec) == []


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ({"type": "integer"}, {"type": "number"}, [("request-type-widened", False)]),
        ({"type": "number"}, {"type": "integer"}, [("request-type-narrowed", True)]),
        ({}, {"type": "string"}, [("request-type-narrowed", True)]),
        (
            {"type": "string"},
            {"enum": ["a"], "type": "string"},
            [("request-constraint-tightened", True)],
        ),
        (
            {"type": "string", "enum": ["a"]},
            {"type": "string"},
            [("request-constraint-relaxed", False)],
        ),
        (
            {"type": "string"},
            {"type": "string", "pattern": "^a"},
            [("request-constraint-tightened", True)],
        ),
        (
            {"type": "string", "pattern": "^a"},
            {"type": "string"},
            [("request-constraint-relaxed", False)],
        ),
        (
            {"type": "string", "minLength": 2},
            {"type": "string", "minLength": 1},
            [("request-constraint-relaxed", False)],
        ),
        (
            {"type": "integer", "multipleOf": 4},
            {"type": "integer", "multipleOf": 2},
            [("request-constraint-relaxed", False)],
        ),
        (
            {"type": "integer", "multipleOf": 2},
            {"type": "integer", "multipleOf": 4},
            [("request-constraint-tightened", True)],
        ),
        (
            {"type": "object"},
            {"type": "object", "additionalProperties": False},
            [("request-constraint-tightened", True)],
        ),
        (
            {"type": "array", "items": {"type": "string"}},
            {"type": "array", "items": {"type": "string", "maxLength": 3}},
            [("request-constraint-tightened", True)],
        ),
        (
            {"type": "object", "properties": {"a": {}}, "additionalProperties": False},
            {"type": "object", "additionalProperties": False},
            [("request-property-removed", True)],
        ),
        (
            {"type": "object", "properties": {"a": {}}},
            {"type": "object"},
            [("request-property-removed", False)],
        ),
        (
            {"type": "object", "properties": {"a": {}}},
            {"type": "object", "properties": {"a": {}}, "required": ["a"]},
            [("request-property-required", True)],
        ),
        (
            {"type": "object", "properties": {"a": {}}, "required": ["a"]},
            {"type": "object", "properties": {"a": {}}},
            [("request-property-optional", False)],
        ),
        (
            {"type": "string", "description": "x"},
            {"type": "string", "description": "y", "example": "z"},
            [],
        ),
        (True, {"type": "string"}, [("schema-changed-unanalysed", True)]),
        (
            {"oneOf": [{"type": "string"}]},
            {"oneOf": [{"type": "string", "maxLength": 2}]},
            [("request-constraint-tightened", True)],
        ),
        (
            {"oneOf": [{"type": "string"}]},
            {"oneOf": [{"type": "string"}, {"type": "null"}]},
            [("schema-changed-unanalysed", True)],
        ),
        (
            {"not": {"type": "string"}},
            {"not": {"type": "integer"}},
            [("schema-changed-unanalysed", True)],
        ),
    ],
)
def test_request_schema_rules(old: Any, new: Any, expected: list[tuple[str, bool]]) -> None:
    assert schema_changes(old, new) == expected


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ({"type": "string"}, {"type": ["string", "null"]}, [("response-type-changed", True)]),
        ({"type": ["string", "null"]}, {"type": "string"}, [("response-type-narrowed", False)]),
        ({"enum": ["a"]}, {"enum": ["a", "b"]}, [("response-enum-value-added", True)]),
        ({"enum": ["a", "b"]}, {"enum": ["a"]}, [("response-enum-value-removed", False)]),
        (
            {"type": "string", "maxLength": 3},
            {"type": "string", "maxLength": 9},
            [("response-constraint-relaxed", True)],
        ),
        (
            {"type": "string"},
            {"type": "string", "maxLength": 9},
            [("response-constraint-tightened", False)],
        ),
        (
            {"type": "object", "properties": {"a": {}}},
            {"type": "object", "properties": {"a": {}}, "required": ["a"]},
            [("response-property-required", False)],
        ),
    ],
)
def test_response_schema_rules(old: Any, new: Any, expected: list[tuple[str, bool]]) -> None:
    assert schema_changes(old, new, "response") == expected


def op(**overrides: Any) -> Operation:
    values: dict[str, Any] = {
        "id": "x",
        "method": "GET",
        "path": "/x",
        "responses": {"200": Response()},
    }
    values.update(overrides)
    return Operation(**values)


def spec_of(*operations: Operation, schemes: dict[str, SecurityScheme] | None = None) -> Spec:
    return Spec(
        openapi="3.1.0",
        title="t",
        operations={item.id: item for item in operations},
        security_schemes=schemes or {},
    )


def test_operation_level_rules() -> None:
    key = SecurityScheme(type="apiKey", name="k", location="header")
    old = spec_of(
        op(
            parameters=[
                {"name": "X-Trace", "location": "header"},
                {"name": "q", "location": "query"},
            ],
            request_schema={"type": "object"},
            responses={
                "200": Response(
                    headers={"X-Rate": Header(required=True)}, content={"text/plain": {}}
                )
            },
            security=[{"A": []}],
        ),
        schemes={"A": key, "B": key},
    )
    new = spec_of(
        op(
            parameters=[{"name": "x-trace", "location": "header", "required": True}],
            request_schema={"type": "object"},
            request_required=True,
            responses={"200": Response()},
            security=[{"B": []}],
        ),
        schemes={"A": key, "B": key},
    )
    found = {(item.rule, item.breaking) for item in diff_specs(old, new)}
    assert found == {
        ("required-parameter-added", True),
        ("parameter-removed", False),
        ("request-body-required", True),
        ("response-header-removed", True),
        ("response-media-type-removed", True),
        ("security-changed", True),
    }
    back = {(item.rule, item.breaking) for item in diff_specs(new, old)}
    assert {
        ("parameter-became-optional", False),
        ("optional-parameter-added", False),
        ("request-body-optional", False),
        ("response-header-added", False),
        ("response-media-type-added", False),
        ("security-changed", True),
    } <= back


def test_body_added_removed_and_security_removed() -> None:
    old = spec_of(
        op(security=[{"A": []}]), schemes={"A": SecurityScheme(type="http", scheme="bearer")}
    )
    new = spec_of(op(request_schema={"type": "object"}, request_required=True))
    assert {(c.rule, c.breaking) for c in diff_specs(old, new)} == {
        ("request-body-required", True),
        ("security-removed", False),
    }
    optional_body = spec_of(op(request_schema={"type": "object"}))
    assert [(c.rule, c.breaking) for c in diff_specs(spec_of(op()), optional_body)] == [
        ("request-body-added", False)
    ]
    assert [(c.rule, c.breaking) for c in diff_specs(optional_body, spec_of(op()))] == [
        ("request-body-removed", False)
    ]


def test_render_formats() -> None:
    changes = diff_specs(parse_spec(V1), parse_spec(BREAKING))
    text = render(changes, "text")
    assert text.splitlines()[0].startswith("BREAKING")
    breaking = sum(c.breaking for c in changes)
    assert text.rstrip().endswith(f"{breaking} breaking, {len(changes) - breaking} non-breaking")
    data = json.loads(render(changes, "json"))
    assert data["breaking"] == sum(c.breaking for c in changes)
    assert data["changes"][0]["rule"] == changes[0].rule
    md = render(changes, "md")
    assert md.startswith("| Severity | Rule | Operation | Where | Detail |")
    assert render([], "text") == "No contract changes.\n"
    assert render([], "md") == "No contract changes.\n"


def test_markdown_escapes_pipes() -> None:
    change = Change(rule="r", breaking=False, operation="GET /a", where="w|x", detail="d")
    assert "w\\|x" in render([change], "md")


@pytest.mark.parametrize("new, code", [(BREAKING, 1), (COMPATIBLE, 0), (V1, 0)])
def test_cli_diff_exit_codes(new: str, code: int, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["diff", V1, new]) == code
    out = capsys.readouterr().out
    assert ("BREAKING" in out) is (code == 1)


def test_cli_diff_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "out" / "drift.json"
    assert main(["diff", V1, BREAKING, "--format", "json", "--out", str(target)]) == 1
    assert json.loads(target.read_text())["breaking"] > 0
    assert "breaking" in capsys.readouterr().out


def test_cli_diff_invalid_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("openapi: 2.0\n")
    assert main(["diff", V1, str(bad)]) == 2
    assert "OpenAPI 3.0.x or 3.1.x" in capsys.readouterr().err


@pytest.mark.parametrize(
    "old, new, direction, expected",
    [
        (
            {"format": "date"},
            {"format": "date-time"},
            "response",
            [("response-constraint-changed", True)],
        ),
        ({"const": "a"}, {"const": "b"}, "response", [("response-constraint-changed", True)]),
        ({"pattern": "^a"}, {"pattern": "^b"}, "request", [("request-constraint-changed", True)]),
        ({"multipleOf": 2}, {"multipleOf": 3}, "response", [("response-constraint-changed", True)]),
        (
            {"type": "object"},
            {"type": "object", "required": ["a"]},
            "request",
            [("request-property-required", True)],
        ),
        (
            {"type": "object", "required": ["a"]},
            {"type": "object"},
            "request",
            [("request-property-optional", False)],
        ),
        (
            {"type": "object", "required": ["a"]},
            {"type": "object"},
            "response",
            [("response-schema-narrowed", True)],
        ),
        (
            {"type": "object"},
            {"type": "object", "required": ["a"]},
            "response",
            [("response-property-required", False)],
        ),
        (
            {"allOf": [{"type": "object"}, {"required": []}]},
            {"allOf": [{"type": "object"}, {"required": ["name"]}]},
            "request",
            [("request-property-required", True)],
        ),
    ],
)
def test_changed_constraints_and_non_local_required(
    old: Any, new: Any, direction: Direction, expected: list[tuple[str, bool]]
) -> None:
    assert schema_changes(old, new, direction) == expected


def test_security_scheme_definition_changes_are_breaking() -> None:
    secured = op(security=[{"K": []}])
    old = spec_of(
        secured, schemes={"K": SecurityScheme(type="apiKey", name="X-API-Key", location="header")}
    )
    new = spec_of(
        secured,
        schemes={"K": SecurityScheme(type="apiKey", name="Authorization", location="header")},
    )
    assert [(c.rule, c.breaking) for c in diff_specs(old, new)] == [
        ("security-scheme-changed", True)
    ]


def test_request_media_type_change_is_breaking() -> None:
    old = spec_of(op(request_schema={"type": "object"}))
    new = spec_of(
        op(request_schema={"type": "object"}, request_media_type="application/merge-patch+json")
    )
    assert [(c.rule, c.breaking) for c in diff_specs(old, new)] == [
        ("request-media-type-changed", True)
    ]


def test_required_response_header_becoming_optional_is_breaking() -> None:
    """Clients may rely on a header the old contract guaranteed."""

    def with_header(required: bool) -> Spec:
        header = Header.model_validate({"required": required, "schema": {"type": "string"}})
        return spec_of(op(responses={"200": Response(headers={"X-Next": header})}))

    assert [
        (c.rule, c.breaking, c.where) for c in diff_specs(with_header(True), with_header(False))
    ] == [("response-header-optional", True, "response 200 x-next")]
    assert diff_specs(with_header(False), with_header(True)) == []


def test_added_oauth_scope_is_breaking_and_removed_scope_is_not() -> None:
    """A token issued for the old scopes is rejected once the operation demands more."""
    schemes = {"oauth": SecurityScheme(type="oauth2")}

    def scoped(*scopes: str) -> Spec:
        return spec_of(op(security=[{"oauth": list(scopes)}]), schemes=schemes)

    added = diff_specs(scoped("read"), scoped("read", "admin"))
    assert [(c.rule, c.breaking, c.detail) for c in added] == [
        ("security-scope-added", True, "required scopes added: oauth:admin")
    ]
    assert diff_specs(scoped("read", "admin"), scoped("read")) == []
    assert diff_specs(scoped("read"), scoped("read")) == []


def test_scope_alternatives_are_compared_as_sets_not_by_position() -> None:
    schemes = {"oauth": SecurityScheme(type="oauth2")}

    def alternatives(*groups: list[str]) -> Spec:
        security = [{"oauth": scopes} for scopes in groups]
        return spec_of(op(security=security), schemes=schemes)

    either = alternatives(["read"], ["write"])
    assert diff_specs(either, alternatives(["write"], ["read"])) == []
    # An extra, stricter alternative takes nothing away from existing clients.
    assert diff_specs(alternatives(["read"]), alternatives(["read"], ["read", "write"])) == []
    assert diff_specs(alternatives(["read"]), alternatives(["read", "write"], ["read"])) == []
    # Clients that only hold "write" lose access when that alternative goes away.
    dropped = diff_specs(either, alternatives(["read"]))
    assert [(c.rule, c.breaking, c.detail) for c in dropped] == [
        ("security-scope-added", True, "required scopes added: oauth:read")
    ]


def test_summary_is_an_annotation_not_drift() -> None:
    assert schema_changes({"type": "string"}, {"type": "string", "summary": "A name"}) == []

"""Pattern synthesis and seeded property-based generation."""

from __future__ import annotations

import random
import re
from typing import Any

import pytest

from api_vv.cli import main
from api_vv.generate import generate, mutations, operation_cases, sample, valid
from api_vv.io import read_data
from api_vv.models import Plan, Requirements, Spec
from api_vv.spec import parse_document
from api_vv.synth import random_instance, regex_example


@pytest.mark.parametrize(
    "pattern",
    [
        r"^[A-Z]{2}-\d{3,}$",
        r"^(cat|dog|bird)s?$",
        r"^[^@\s]+@[a-z]+\.(com|org)$",
        r"^\w{4,8}$",
        r"^(ab)\1$",
        r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$",
        r"\D\S\W.",
        r"^x*?y+?z{2,}?$",
        r"^(?>ab|a)c$",
        r"^[\d-]+$",
        "^café$",
    ],
)
def test_regex_example_matches(pattern: str) -> None:
    deterministic = regex_example(pattern)
    assert deterministic is not None and re.search(pattern, deterministic)
    rng = random.Random(7)
    for _ in range(20):
        value = regex_example(pattern, rng)
        assert value is not None and re.search(pattern, value), value


@pytest.mark.parametrize("pattern", [r"^(?=a)b$", r"(?<!x)y", "[", r"^a$(?!b)"])
def test_regex_example_gives_up_on_unsupported_or_impossible(pattern: str) -> None:
    assert regex_example(pattern) is None


def test_sample_honours_pattern_and_length() -> None:
    schema = {"type": "string", "pattern": r"^[A-Z]{2}-\d+$", "minLength": 6, "maxLength": 7}
    value = sample(schema)
    assert valid(value, schema), value


def test_unsatisfiable_pattern_falls_back_for_review() -> None:
    schema = {"type": "string", "pattern": r"^(?=a)b$"}
    assert not valid(sample(schema), schema)


def test_pattern_mutation_breaks_only_the_pattern() -> None:
    schema = {"type": "string", "pattern": r"^[a-z]+$", "minLength": 2, "maxLength": 4}
    value = sample(schema)
    found = [
        (item, check) for item, check in mutations(value, schema, "code") if "pattern" in check
    ]
    assert len(found) == 1
    bad, check = found[0]
    assert check == "pattern:code"
    assert not valid(bad, schema)
    assert valid(bad, {key: val for key, val in schema.items() if key != "pattern"})


def test_pattern_mutation_when_every_candidate_matches_length() -> None:
    schema = {"type": "string", "pattern": r"."}
    found = [item for item, check in mutations("a", schema, "p") if check == "pattern:p"]
    assert found == [""]
    anything = {"type": "string", "pattern": ".*"}
    assert not [check for _, check in mutations("a", anything, "p") if "pattern" in check]


SCHEMAS: list[dict[str, Any]] = [
    {"type": "integer", "minimum": -3, "maximum": 3},
    {"type": "integer", "exclusiveMinimum": 0, "multipleOf": 5},
    {"type": "number", "exclusiveMaximum": 1.5},
    {"type": "number", "minimum": 2, "maximum": 2},
    {"type": "string", "minLength": 2, "maxLength": 5},
    {"type": "string", "format": "email"},
    {"type": "string", "pattern": r"^[A-Z]\d$"},
    {"type": ["string", "null"], "maxLength": 1},
    {"enum": ["a", "b", 3]},
    {"const": {"k": 1}},
    {"type": "boolean"},
    {"type": "null"},
    {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 3},
    {"type": "array", "items": {"enum": [1, 2, 3]}, "uniqueItems": True, "minItems": 2},
    {
        "type": "object",
        "required": ["a"],
        "additionalProperties": False,
        "properties": {
            "a": {"type": "string", "minLength": 1},
            "b": {"type": "integer", "maximum": 0},
            "c": {"readOnly": True, "type": "string"},
            "d": {"type": "object", "properties": {"e": {"type": "boolean"}}},
        },
    },
    {"oneOf": [{"type": "integer", "minimum": 100}, {"type": "string", "maxLength": 0}]},
    {"anyOf": [{"type": "boolean"}]},
    {
        "allOf": [
            {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
            {"type": "object", "properties": {"b": {"type": "string"}}},
        ]
    },
    {},
]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_random_instances_are_valid_and_seeded(schema: dict[str, Any]) -> None:
    first = [random_instance(schema, random.Random(f"s:{i}")) for i in range(15)]
    second = [random_instance(schema, random.Random(f"s:{i}")) for i in range(15)]
    assert first == second
    for found, value in first:
        assert found, schema
        assert valid(value, schema), (schema, value)


def test_random_instance_reports_impossible_schemas() -> None:
    assert random_instance(False, random.Random(1)) == (False, None)
    impossible = {"type": "integer", "minimum": 5, "maximum": 1}
    assert random_instance(impossible, random.Random(1))[0] is False
    deep: dict[str, Any] = {"type": "object", "required": ["n"], "properties": {}}
    node = deep
    for _ in range(12):
        child: dict[str, Any] = {"type": "object", "required": ["n"], "properties": {}}
        node["properties"]["n"] = child
        node = child
    assert random_instance(deep, random.Random(1))[0] is False


def pets() -> Spec:
    return parse_document(
        {
            "openapi": "3.1.0",
            "info": {"title": "Pets"},
            "paths": {
                "/pets/{petId}": {
                    "put": {
                        "operationId": "putPet",
                        "parameters": [
                            {"name": "petId", "in": "path", "schema": {"type": "integer"}},
                            {
                                "name": "page",
                                "in": "query",
                                "schema": {"type": "integer", "minimum": 1, "maximum": 50},
                            },
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["name", "code"],
                                        "properties": {
                                            "name": {"type": "string", "maxLength": 6},
                                            "code": {"type": "string", "pattern": "^P\\d{2}$"},
                                            "tags": {
                                                "type": "array",
                                                "items": {"enum": ["a", "b"]},
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "ok"}, "400": {"description": "x"}},
                    }
                }
            },
        }
    )


def requirements() -> Requirements:
    return Requirements.model_validate(
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "text": "Any schema-valid pet is accepted",
                    "priority": "must",
                    "verification_method": "test",
                    "covers": [
                        {
                            "operation_id": "putPet",
                            "responses": ["200"],
                            "checks": ["property:valid"],
                        }
                    ],
                }
            ]
        }
    )


def test_property_cases_are_valid_invalid_and_traced() -> None:
    spec = pets()
    plan = generate(spec, requirements(), seed=11, property_cases=8)
    assert plan.seed == 11 and plan.property_cases == 8
    op = spec.operations["putPet"]
    schema = op.request_schema
    assert schema is not None
    good = [case for case in plan.cases if "property:valid" in case.checks]
    bad = [case for case in plan.cases if "property:invalid" in case.checks]
    # Identical requests merge with boundary cases, so counts are upper bounds.
    assert 4 <= len(good) <= 8 and 4 <= len(bad) <= 8
    for case in good:
        assert case.enabled and case.expected_status == "200" and not case.negative
        assert valid(case.body, schema)
        assert case.parameters["path"]["petId"] == 0
        assert "REQ-001" in case.requirement_ids
        assert "property" in case.generators
    for case in bad:
        assert case.enabled and case.expected_status == "400" and case.negative
        page = case.parameters.get("query", {}).get("page", 1)
        assert not valid(case.body, schema) or not valid(page, op.parameters[1].schema_)
        assert "property" in case.generators
    assert any(case.name.startswith("putPet: property invalid #") for case in bad)
    assert any(case.parameters.get("query") for case in good)


def test_property_generation_is_deterministic_per_seed() -> None:
    spec = pets()
    one = generate(spec, requirements(), seed=3, property_cases=5).model_dump(mode="json")
    two = generate(spec, requirements(), seed=3, property_cases=5).model_dump(mode="json")
    other = generate(spec, requirements(), seed=4, property_cases=5).model_dump(mode="json")
    assert one == two
    assert one != other


def test_property_cases_off_by_default(spec: Spec, requirements: Requirements) -> None:
    plan = generate(spec, requirements)
    assert plan.seed is None and plan.property_cases == 0
    assert not any("property" in case.generators for case in plan.cases)


def test_property_cases_without_error_response_need_review() -> None:
    spec = pets()
    del spec.operations["putPet"].responses["400"]
    cases = operation_cases(spec.operations["putPet"], spec, rng=random.Random(1), property_count=2)
    bad = [case for case in cases if "property:invalid" in case.checks]
    assert bad and all(not case.enabled for case in bad)


def test_property_count_is_bounded() -> None:
    with pytest.raises(ValueError, match="property_cases must be between 0 and 100"):
        generate(pets(), requirements(), property_cases=101)


def test_cli_generate_with_seed(tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
    from tests.conftest import DEMO

    out = tmp_path / "plan.yaml"
    args = [
        "generate",
        "--spec",
        str(DEMO / "openapi.yaml"),
        "--requirements",
        str(DEMO / "requirements.yaml"),
        "--out",
        str(out),
        "--property-cases",
        "3",
        "--seed",
        "42",
    ]
    assert main(args) == 0
    plan = Plan.model_validate(read_data(out))
    assert plan.seed == 42 and plan.property_cases == 3
    first = out.read_text()
    assert main(args) == 0
    assert out.read_text() == first
    assert "Generated" in capsys.readouterr().out


def test_random_instance_accepts_integral_float_bounds() -> None:
    schema = {"type": "string", "minLength": 2.0, "maxLength": 4.0}
    array = {"type": "array", "items": {"type": "boolean"}, "minItems": 1.0, "maxItems": 2.0}
    for target in (schema, array):
        found, value = random_instance(target, random.Random(5))
        assert found and valid(value, target)


@pytest.mark.parametrize(
    "schema",
    [{"type": "string", "minLength": 10**9}, {"type": "array", "minItems": 10**6}],
)
def test_random_instance_refuses_huge_sizes(schema: dict[str, Any]) -> None:
    assert random_instance(schema, random.Random(5)) == (False, None)

"""OpenAPI 3.1 constructs and authentication applied from environment variable names."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from api_vv.cli import main
from api_vv.execute import execute, request_parts
from api_vv.generate import generate, operation_cases, valid
from api_vv.models import Case, Config, Plan, Requirements, SecurityScheme, Spec
from api_vv.spec import normalize_schema, parse_document

INVALID = "api-vv-invalid-credential"


def doc31(**extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Pets"},
        "paths": {
            "/pets": {
                "post": {
                    "operationId": "createPet",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": ["integer", "null"], "minimum": 1},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {
                                        "name": {"type": "string", "maxLength": 3},
                                        "tag": {"type": ["string", "null"]},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "ok"}, "422": {"description": "bad"}},
                }
            }
        },
    }
    doc.update(extra)
    return doc


def secured(scheme: dict[str, Any]) -> Spec:
    doc = doc31()
    doc["components"] = {"securitySchemes": {"Auth": scheme}}
    doc["security"] = [{"Auth": []}]
    doc["paths"]["/pets"]["post"]["responses"]["401"] = {"description": "no"}
    return parse_document(doc)


def one_case(spec: Spec, auth: str = "configured") -> tuple[Case, Spec]:
    case = Case(
        id="c",
        name="c",
        operation_id="createPet",
        expected_status="201",
        auth=auth,  # type: ignore[arg-type]
        generators=["t"],
        checks=["t"],
    )
    return case, spec


def test_type_array_null_unions_generate_enabled_cases() -> None:
    spec = parse_document(doc31())
    cases = operation_cases(spec.operations["createPet"], spec)
    happy = cases[0]
    assert happy.enabled and happy.parameters["query"]["limit"] == 1
    assert happy.body == {"name": "x", "tag": "x"}
    checks = {check for case in cases for check in case.checks}
    assert {"wrong-type:query.limit", "wrong-type:tag", "boundary:name:maxLength:above"} <= checks
    wrong_tag = next(case for case in cases if "wrong-type:tag" in case.checks)
    assert wrong_tag.body["tag"] is not None and wrong_tag.negative


def test_legacy_nullable_without_single_type_keeps_null() -> None:
    schema = normalize_schema(
        {"allOf": [{"type": "object", "required": ["a"]}], "nullable": True}, legacy=True
    )
    assert valid(None, schema)
    assert valid({"a": 1}, schema)
    assert not valid({}, schema)


def test_webhooks_are_listed_but_not_tested() -> None:
    hook = {"post": {"responses": {"200": {"description": "ok"}}}}
    spec = parse_document(doc31(webhooks={"petAdopted": hook, "petLost": hook}))
    assert spec.webhooks == ["petAdopted", "petLost"]
    assert list(spec.operations) == ["createPet"]
    only_hooks = doc31(webhooks={"petAdopted": hook})
    del only_hooks["paths"]
    with pytest.raises(ValueError, match="webhooks are not tested"):
        parse_document(only_hooks)


def test_cli_parse_reports_ignored_webhooks(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    import yaml

    hook = {"post": {"responses": {"200": {"description": "ok"}}}}
    source = tmp_path / "spec.yaml"
    source.write_text(yaml.safe_dump(doc31(webhooks={"petAdopted": hook})))
    assert main(["parse", "--spec", str(source), "--out", str(tmp_path / "out.yaml")]) == 0
    assert capsys.readouterr().out == "Parsed 1 operations (1 webhook ignored)\n"


def test_examples_maps_feed_the_happy_path() -> None:
    doc = doc31()
    post = doc["paths"]["/pets"]["post"]
    post["parameters"][0]["examples"] = {"few": {"value": 7}, "many": {"value": 50}}
    post["requestBody"]["content"]["application/json"]["examples"] = {
        "cat": {"summary": "a cat", "value": {"name": "cat"}}
    }
    spec = parse_document(doc)
    happy = operation_cases(spec.operations["createPet"], spec)[0]
    assert happy.parameters["query"]["limit"] == 7
    assert happy.body == {"name": "cat"}


@pytest.mark.parametrize(
    "scheme, expected",
    [
        ({"type": "http", "scheme": "Bearer"}, "Bearer s3cret"),
        ({"type": "http", "scheme": "BASIC"}, "Basic " + base64.b64encode(b"s3cret").decode()),
    ],
)
def test_http_scheme_names_are_case_insensitive(
    scheme: dict[str, Any], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = secured(scheme)
    monkeypatch.setenv("PET_TOKEN", "s3cret")
    case, _ = one_case(spec)
    config = Config(credentials_env={"Auth": "PET_TOKEN"})
    headers = request_parts(case, spec.operations["createPet"], spec, config)[1]
    assert headers["authorization"] == expected


@pytest.mark.parametrize("value", ["sk-live-123", "has space", "1STARTS_WITH_DIGIT", ""])
def test_credentials_env_values_must_be_variable_names(value: str) -> None:
    with pytest.raises(ValidationError):
        Config(credentials_env={"Auth": value})


def test_default_env_name_is_used_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = secured({"type": "apiKey", "in": "query", "name": "api_key"})
    monkeypatch.setenv("API_VV_AUTH_AUTH", "from-default")
    case, _ = one_case(spec)
    query = request_parts(case, spec.operations["createPet"], spec, Config())[2]
    assert query["api_key"] == "from-default"
    sanitized = secured({"type": "apiKey", "in": "header", "name": "X-Key"})
    sanitized.security_schemes["my-key.v2"] = sanitized.security_schemes.pop("Auth")
    sanitized.operations["createPet"].security = [{"my-key.v2": []}]
    monkeypatch.setenv("API_VV_AUTH_MY_KEY_V2", "sanitized")
    headers = request_parts(case, sanitized.operations["createPet"], sanitized, Config())[1]
    assert headers["x-key"] == "sanitized"


def test_unknown_scheme_in_credentials_env_is_rejected(
    spec: Spec, requirements: Requirements
) -> None:
    plan = generate(spec, requirements)
    config = Config(credentials_env={"DemoKey": "API_VV_DEMO_KEY", "Typo": "X"})
    with pytest.raises(ValueError, match="unknown security scheme in credentials_env: Typo"):
        asyncio.run(execute(plan, "http://api.test", config, httpx.MockTransport(lambda r: r)))


def test_generated_invalid_credentials_case(plan: Plan) -> None:
    invalid = next(case for case in plan.cases if "auth-invalid" in case.checks)
    assert invalid.auth == "invalid" and invalid.negative
    assert invalid.expected_status == "401" and invalid.enabled
    assert invalid.operation_id == "secure"


@pytest.mark.parametrize(
    "scheme, slot, expected",
    [
        ({"type": "apiKey", "in": "header", "name": "X-Key"}, (1, "x-key"), INVALID),
        ({"type": "apiKey", "in": "query", "name": "k"}, (2, "k"), INVALID),
        ({"type": "apiKey", "in": "cookie", "name": "sid"}, (3, "sid"), INVALID),
        ({"type": "http", "scheme": "bearer"}, (1, "authorization"), "Bearer " + INVALID),
        (
            {"type": "http", "scheme": "basic"},
            (1, "authorization"),
            "Basic " + base64.b64encode(f"api-vv:{INVALID}".encode()).decode(),
        ),
    ],
)
def test_invalid_auth_sends_a_fake_credential_without_configuration(
    scheme: dict[str, Any], slot: tuple[int, str], expected: str
) -> None:
    spec = secured(scheme)
    case, _ = one_case(spec, auth="invalid")
    parts = request_parts(case, spec.operations["createPet"], spec, Config())
    assert parts[slot[0]][slot[1]] == expected  # type: ignore[index]


def test_invalid_auth_case_runs_against_demo(
    plan: Plan, config: Config, transport: httpx.ASGITransport
) -> None:
    subset = plan.model_copy(deep=True)
    subset.cases = [case for case in subset.cases if "auth-invalid" in case.checks]
    run = asyncio.run(execute(subset, "http://demo.test", config, transport))
    assert [(item.verdict, item.actual_status) for item in run.results] == [("passed", 401)]


def test_unsupported_scheme_for_invalid_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = secured({"type": "http", "scheme": "bearer"})
    spec.security_schemes["Auth"] = SecurityScheme(type="http", scheme="digest")
    case, _ = one_case(spec, auth="invalid")
    with pytest.raises(ValueError, match="unsupported authentication"):
        request_parts(case, spec.operations["createPet"], spec, Config())

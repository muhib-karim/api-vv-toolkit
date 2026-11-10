"""An ordinary contract against a server that honours it: no generated case may fail.

The demo API only has an integer path parameter, so it cannot show the false failures that
text parameters, date examples, media-type parameters or nullable headers used to cause.
"""

from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from api_vv.execute import execute
from api_vv.generate import generate, valid
from api_vv.io import read_data
from api_vv.models import Config, Requirements, Schema, Spec
from api_vv.report import gate_failures, junit, matrix
from api_vv.spec import parse_spec

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "realistic" / "bookshop.yaml"
TOKEN = "fixture-token"
BOOK = {
    "isbn": "9780000000001",
    "title": "T",
    "price": {"amount": 9.99, "currency": "EUR"},
    "id": "00000000-0000-4000-8000-000000000001",
    "createdAt": "2021-06-30T10:15:00Z",
}
COVERS = [
    ("Books can be listed.", "listBooks", "200", "happy-path"),
    ("A book can be created.", "createBook", "201", "happy-path"),
    ("A book needs a title.", "createBook", "422", "required:title"),
    ("Deleting a book needs a credential.", "deleteBook", "401", "auth-required"),
]
REQUIREMENTS = Requirements.model_validate(
    {
        "requirements": [
            {
                "id": f"REQ-00{number}",
                "text": text,
                "priority": "must",
                "verification_method": "test",
                "covers": [{"operation_id": operation, "responses": [status], "checks": [check]}],
            }
            for number, (text, operation, status, check) in enumerate(COVERS, start=1)
        ]
    }
)


def problem(status: int) -> httpx.Response:
    headers = {"content-type": "application/problem+json"}
    return httpx.Response(status, json={"title": "problem", "status": status}, headers=headers)


def typed(raw: str, schema: Schema) -> Any:
    """What a server does first: read a parameter's text as its declared type."""
    kind = schema.get("type") if isinstance(schema, dict) else None
    if kind == "integer" and re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if kind == "boolean":
        return {"true": True, "false": False}.get(raw, raw)
    return raw


def bookshop(spec: Spec) -> Callable[[httpx.Request], httpx.Response]:
    """A server that implements the contract exactly, validating with the parsed spec."""
    listing, create = spec.operations["listBooks"], spec.operations["createBook"]

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        public = path == "/health" or (path != "/books" and method in {"GET", "HEAD"})
        if not public and request.headers.get("authorization") != f"Bearer {TOKEN}":
            return problem(401)
        if path == "/health":
            return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})
        if path == "/books" and method == "GET":
            for param in listing.parameters:
                source = request.headers if param.location == "header" else request.url.params
                raw = source.get(param.name) if param.location != "cookie" else None
                if raw is not None and not valid(typed(raw, param.schema_), param.schema_):
                    return problem(400)
            headers = {
                "content-type": "application/json; charset=utf-8",
                "X-Total-Count": "1",
                "X-RateLimit-Remaining": "5",
            }
            return httpx.Response(200, content=json.dumps({"items": [BOOK]}), headers=headers)
        if path == "/books":
            assert create.request_schema is not None
            try:
                acceptable = valid(json.loads(request.content), create.request_schema)
            except ValueError:
                acceptable = False
            if not acceptable:
                return problem(422)
            location = f"https://api.example.test/v2/books/{BOOK['isbn']}"
            return httpx.Response(201, json=BOOK, headers={"Location": location})
        if not re.fullmatch(r"/books/[0-9]{13}", path):
            return problem(404)
        if method == "DELETE":
            return httpx.Response(204)
        if method == "HEAD":
            return httpx.Response(200, headers={"content-type": "application/json"})
        return httpx.Response(200, json=BOOK)

    return handler


def test_contract_correct_server_has_no_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_VV_AUTH_BEARERAUTH", TOKEN)
    spec = parse_spec(FIXTURE)
    plan = generate(spec, REQUIREMENTS, seed=1, property_cases=3)
    transport = httpx.MockTransport(bookshop(spec))
    run = asyncio.run(execute(plan, "http://api.test", Config(), transport))

    names = {case.id: case.name for case in plan.cases}
    failed = {names[item.case_id]: item.errors for item in run.results if item.verdict == "failed"}
    assert failed == {}
    assert sum(item.verdict == "passed" for item in run.results) >= 50

    data = matrix(plan, run)
    assert {row.requirement.id: row.status for row in data.rows} == {
        "REQ-001": "verified",
        "REQ-002": "verified",
        "REQ-003": "verified",
        "REQ-004": "verified",
    }
    assert gate_failures(data, Config()) == []
    assert ET.fromstring(junit(plan, data, Config())).get("failures") == "0"


def test_fixture_keeps_the_constructs_it_exists_for() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert "example: 2020-01-01" in text and "application/json; charset=utf-8" in text
    parameters = read_data(FIXTURE)["paths"]["/books"]["get"]["parameters"]
    assert {item["name"]: item.get("example") for item in parameters}["publishedAfter"] == (
        "2020-01-01"
    )

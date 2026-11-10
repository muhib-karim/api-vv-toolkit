from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from api_vv.cli import load_config
from api_vv.execute import execute
from api_vv.generate import generate
from api_vv.io import read_data
from api_vv.llm import augment
from api_vv.models import Config, Plan, Requirements, Result, Spec
from api_vv.spec import parse_spec

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo_api"


def one_operation(
    responses: dict[str, Any], *, version: str = "3.1.0", method: str = "get", **operation: Any
) -> dict[str, Any]:
    """A minimal OpenAPI document with a single operation ``a`` at ``/a``."""
    op = {"operationId": "a", "responses": responses, **operation}
    return {"openapi": version, "info": {"title": "t"}, "paths": {"/a": {method: op}}}


def requirement_for(operation_id: str, status: str = "200") -> Requirements:
    """One must-priority requirement covering the operation's happy path."""
    cover = {"operation_id": operation_id, "responses": [status], "checks": ["happy-path"]}
    item = {"id": "REQ-001", "text": "t", "priority": "must", "verification_method": "test"}
    return Requirements.model_validate({"requirements": [{**item, "covers": [cover]}]})


def run_against(plan: Plan, handler: Callable[[httpx.Request], httpx.Response]) -> list[Result]:
    """Execute a plan in-process against a handler; no sockets are opened."""
    transport = httpx.MockTransport(handler)
    return asyncio.run(execute(plan, "http://api.test", transport=transport)).results


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network is forbidden in tests; use an injected transport")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


@pytest.fixture
def spec() -> Spec:
    return parse_spec(DEMO / "openapi.yaml")


@pytest.fixture
def requirements() -> Requirements:
    return Requirements.model_validate(read_data(DEMO / "requirements.yaml"))


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("API_VV_DEMO_KEY", "fixture-secret")
    return load_config(str(DEMO / "config.yaml"))


@pytest.fixture
def plan(spec: Spec, requirements: Requirements, config: Config) -> Plan:
    return asyncio.run(augment(generate(spec, requirements), config.llm))


@pytest.fixture
def transport() -> httpx.ASGITransport:
    from examples.demo_api.app import app

    return httpx.ASGITransport(app=app)

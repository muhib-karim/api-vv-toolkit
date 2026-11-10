"""Safe serialization and fingerprints (never include runtime credentials)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel

from api_vv.models import Case, Plan


class _Loader(yaml.SafeLoader):
    """SafeLoader without YAML 1.1 timestamps.

    OpenAPI documents are JSON-compatible YAML, where an unquoted ``2024-01-15`` is a string.
    PyYAML would turn it into a ``datetime.date`` that no JSON request or fingerprint can carry.
    """


_Loader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def read_data(path: str | Path) -> Any:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        # YAML is not a strict superset of JSON (tab indentation, for one): parse JSON as JSON.
        try:
            return json.loads(text.removeprefix("\ufeff"))
        except json.JSONDecodeError:
            pass  # YAML saved under a .json name still loads below
    return yaml.load(text, Loader=_Loader)  # a SafeLoader subclass: still safe loading


def scalar(value: Any) -> str:
    """The text a path, query, header or cookie parameter value is sent as."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def write_data(path: str | Path, model: BaseModel) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(model.model_dump(mode="json", by_alias=True), sort_keys=False),
        encoding="utf-8",
    )


def check_base_url(value: str, label: str) -> None:
    """Credentials are only ever sent to a plain HTTP(S) origin the user named."""
    message = f"{label} must be an HTTP(S) URL without credentials, query or fragment"
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise ValueError(message) from None
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.userinfo
        or url.query
        or url.fragment
        # httpx accepts any integer; the socket layer later fails outside its error types.
        or (url.port is not None and not 0 < url.port < 65536)
    ):
        raise ValueError(message)


def unsafe_path(path: str) -> bool:
    return (
        not path.startswith("/")
        or path.startswith("//")
        or "?" in path
        or "#" in path
        or any(part in {".", ".."} for part in path.split("/"))
    )


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def plan_digest(plan: Plan) -> str:
    return digest(plan.model_dump(mode="json", by_alias=True))


def fingerprint(case: Case) -> str:
    return digest(
        {
            "operation": case.operation_id,
            "parameters": case.parameters,
            "body": case.body,
            "has_body": case.has_body,
            "auth": case.auth,
        }
    )

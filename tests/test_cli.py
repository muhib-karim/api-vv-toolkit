from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
import pytest

from api_vv import cli
from api_vv.execute import execute
from api_vv.io import plan_digest, read_data, write_data
from api_vv.models import Config, Plan, Run

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_api"
SPEC = str(DEMO / "openapi.yaml")
REQS = str(DEMO / "requirements.yaml")
CONFIG = str(DEMO / "config.yaml")


def call(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_end_to_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.ASGITransport,
) -> None:
    monkeypatch.setenv("API_VV_DEMO_KEY", "cli-secret")

    async def in_process(plan: Plan, base_url: str, config: Config) -> Run:
        return await execute(plan, base_url, config, transport)

    monkeypatch.setattr(cli, "execute", in_process)
    plan_path, results = str(tmp_path / "plan.yaml"), str(tmp_path / "results.yaml")

    assert call(capsys, "parse", "--spec", SPEC, "--out", str(tmp_path / "spec.yaml")) == (
        0,
        "Parsed 5 operations\n",
        "",
    )
    assert call(capsys, "validate-requirements", "--spec", SPEC, "--requirements", REQS)[1] == (
        "Validated 12 requirements\n"
    )
    code, out, _ = call(
        capsys, "generate", "--spec", SPEC, "--requirements", REQS, "--config", CONFIG,
        "--llm", "--out", plan_path,
    )  # fmt: skip
    assert code == 0 and "LLM proposals: 1 accepted, 1 rejected" in out
    code, out, _ = call(
        capsys, "run", "--plan", plan_path, "--base-url", "http://demo.test",
        "--config", CONFIG, "--out", results,
    )  # fmt: skip
    assert code == 1
    assert out.endswith("2 failed, 0 skipped\nGate: FAIL (REQ-003, REQ-008)\n")
    assert "cli-secret" not in Path(results).read_text() + Path(plan_path).read_text()

    code, out, _ = call(
        capsys, "report", "--plan", plan_path, "--results", results, "--out-dir", str(tmp_path)
    )
    assert code == 1 and "Gate: FAIL (REQ-003, REQ-008)" in out
    suite = ET.parse(tmp_path / "junit.xml").getroot()
    failed = {
        node.get("name") for node in suite.iter("testcase") if node.find("failure") is not None
    }
    assert {"REQ-003", "REQ-008"} <= failed and len(failed) == 4
    with (tmp_path / "traceability.csv").open(newline="") as handle:
        rows = {row["requirement_id"]: row for row in csv.DictReader(handle)}
    assert rows["REQ-003"]["status"] == "failed" and rows["REQ-008"]["verdict"] == "failed"
    assert (tmp_path / "report.html").read_text().startswith("<!doctype html>")

    code, out, _ = call(capsys, "trace", "--plan", plan_path, "--results", results)
    assert code == 0 and "| must | failed |" in out
    trace_csv = tmp_path / "out" / "trace.csv"
    assert (
        call(capsys, "trace", "--plan", plan_path, "--format", "csv", "--out", str(trace_csv))[0]
        == 0
    )
    assert "not run" in trace_csv.read_text()
    code, out, _ = call(capsys, "trace", "--plan", plan_path, "--format", "html")
    assert code == 0 and "not covered" in out


def test_generate_without_llm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "plan.yaml"
    code, text, _ = call(
        capsys, "generate", "--spec", SPEC, "--requirements", REQS, "--out", str(out)
    )
    assert code == 0 and "LLM" not in text
    assert Plan.model_validate(read_data(out)).llm_audit == []


@pytest.mark.parametrize(
    "content, message",
    [
        ("openapi: 2.0\n", "error: expected an OpenAPI 3.0.x or 3.1.x document"),
        (": [", "error: invalid or unreadable input (ParserError)"),
    ],
)
def test_invalid_input_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str, message: str
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(content, encoding="utf-8")
    code, _, err = call(capsys, "parse", "--spec", str(bad), "--out", str(tmp_path / "o"))
    assert (code, err.strip()) == (2, message)


def test_validation_errors_do_not_echo_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "config.yaml"
    bad.write_text("credentials_env: sk-live-secret\n", encoding="utf-8")
    code, _, err = call(capsys, "trace", "--plan", str(bad), "--config", str(bad))
    assert code == 2 and "sk-live-secret" not in err
    assert err.startswith("error: ") and "credentials_env: extra_forbidden" in err


def test_missing_file_and_bad_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = call(capsys, "parse", "--spec", str(tmp_path / "none.yaml"), "--out", "x")
    assert code == 2 and "FileNotFoundError" in err
    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "t"},
        "paths": {"/a": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    spec["paths"]["/a"]["get"]["parameters"] = [{"name": "q", "in": "query", "schema": {"type": 5}}]
    target = tmp_path / "spec.json"
    target.write_text(json.dumps(spec), encoding="utf-8")
    code, _, err = call(capsys, "parse", "--spec", str(target), "--out", str(tmp_path / "o"))
    assert (code, err) == (2, "error: invalid JSON schema\n")


def test_unknown_requirement_operation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reqs = tmp_path / "reqs.yaml"
    reqs.write_text(
        "requirements:\n  - {id: REQ-001, text: t, priority: must, verification_method: test,"
        " covers: [{operation_id: nope, responses: ['200']}]}\n",
        encoding="utf-8",
    )
    code, _, err = call(
        capsys, "validate-requirements", "--spec", SPEC, "--requirements", str(reqs)
    )
    assert (code, err) == (2, "error: REQ-001: unknown operation nope\n")


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        *(
            [command, "--help"]
            for command in ("parse", "validate-requirements", "generate", "run", "report", "trace")
        ),
    ],
)
def test_help_exits_cleanly(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 0
    assert "usage: api-vv" in capsys.readouterr().out


def test_version_matches_package(capsys: pytest.CaptureFixture[str]) -> None:
    from api_vv import __version__

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_generate_accepts_unquoted_date_examples(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        "openapi: 3.0.3\n"
        "info: {title: t, version: '1'}\n"
        "paths:\n"
        "  /events:\n"
        "    get:\n"
        "      operationId: listEvents\n"
        "      parameters:\n"
        "        - {name: since, in: query, schema: {type: string, format: date},"
        " example: 2024-01-15}\n"
        "      responses:\n"
        "        '200': {description: ok}\n",
        encoding="utf-8",
    )
    reqs = tmp_path / "reqs.yaml"
    reqs.write_text(
        "requirements:\n  - {id: REQ-001, text: t, priority: must, verification_method: test,"
        " covers: [{operation_id: listEvents, responses: ['200']}]}\n",
        encoding="utf-8",
    )
    plan = tmp_path / "plan.yaml"
    code, out, err = call(
        capsys, "generate", "--spec", str(spec), "--requirements", str(reqs), "--out", str(plan)
    )
    assert (code, err) == (0, "") and out.startswith("Generated ")
    assert "since: '2024-01-15'" in plan.read_text(encoding="utf-8")


@pytest.mark.parametrize("url", ["http://localhost:80a0", "http://[::1", "http://localhost:99999"])
def test_malformed_base_url_is_invalid_input_not_a_failed_gate(
    url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = str(tmp_path / "plan.yaml")
    assert call(capsys, "generate", "--spec", SPEC, "--requirements", REQS, "--out", plan)[0] == 0
    code, out, err = call(
        capsys, "run", "--plan", plan, "--base-url", url, "--out", str(tmp_path / "results.yaml")
    )
    assert (code, out) == (2, "")
    assert err == "error: base URL must be an HTTP(S) URL without credentials, query or fragment\n"


def test_empty_spec_sections_do_not_look_like_breaking_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 1 means breaking drift; a document the parser cannot read must exit 2."""
    spec = tmp_path / "spec.yaml"
    document = (
        "openapi: 3.0.3\ninfo: {title: t, version: '1'}\ncomponents:\npaths:\n  /a:\n"
        "    get:\n      responses:\n        '200':"
    )
    spec.write_text(document + "\n", encoding="utf-8")  # a response with nothing under it
    code, _, err = call(capsys, "diff", str(spec), str(spec))
    assert (code, err) == (2, "error: invalid or unreadable input (AttributeError)\n")
    spec.write_text(document + " {description: ok}\n", encoding="utf-8")  # only components: empty
    assert call(capsys, "diff", str(spec), str(spec)) == (0, "No contract changes.\n", "")


def test_unexpected_errors_never_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def crash(args: Any) -> int:
        raise RuntimeError("internal")

    monkeypatch.setattr(cli, "dispatch", crash)
    code, _, err = call(capsys, "diff", "old.yaml", "new.yaml")
    assert code == 2
    # The traceback stays visible for a bug report; the exit code still is not the gate's.
    assert "Traceback" in err and err.endswith("error: unexpected failure (RuntimeError)\n")


def test_empty_config_file_means_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("# nothing set\n", encoding="utf-8")
    assert cli.load_config(str(config)) == Config()
    # Only an empty file: any other non-mapping is still a mistake worth reporting.
    config.write_text("[]\n", encoding="utf-8")
    code, _, err = call(capsys, "trace", "--plan", str(config), "--config", str(config))
    assert code == 2 and err.startswith("error: ")


def test_date_like_strings_survive_a_plan_file_round_trip(tmp_path: Path, plan: Plan) -> None:
    """The plan digest ties results to a plan, so reloading must not retype any string."""
    plan.cases[0].name = "2024-01-15"
    plan.cases[1].name = "2024-01-15 10:00:00"
    plan.cases[2].body = {"at": "2024-01-15T10:00:00Z"}
    path = tmp_path / "plan.yaml"
    write_data(path, plan)
    reloaded = Plan.model_validate(read_data(path))
    assert plan_digest(reloaded) == plan_digest(plan)
    assert reloaded.cases[1].name == "2024-01-15 10:00:00"

"""The Pages landing is built from a real demo run's evidence."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from api_vv.execute import execute
from api_vv.io import write_data
from api_vv.models import Config, Plan
from api_vv.report import write_reports
from tests.conftest import ROOT


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_dir(tmp_path: Path, plan: Plan, config: Config, transport: httpx.ASGITransport) -> Path:
    run = asyncio.run(execute(plan, "http://demo.test", config, transport))
    out = tmp_path / "run"
    write_data(out / "plan.yaml", plan)
    write_data(out / "results.yaml", run)
    write_reports(plan, run, out, config)
    (out / "cli-output.txt").write_text("Gate: FAIL (REQ-003, REQ-008)\n", encoding="utf-8")
    return out


def test_landing_reports_the_live_run(
    run_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef")
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GITHUB_REPOSITORY", "someone/fork")
    site = tmp_path / "site"
    assert load_builder().main([str(run_dir), str(site)]) == 0
    page = (site / "index.html").read_text(encoding="utf-8")
    assert "Built by GitHub Actions run 4242 from commit 0123456" in page
    assert "Gate: FAIL (REQ-003, REQ-008)" in page
    assert 'href="report.html#REQ-003"' in page and 'href="report.html#REQ-008"' in page
    assert "status: expected 422, got 201" in page
    assert "path-removed" in page and "https://github.com/someone/fork" in page
    assert '<html lang="en">' in page and "<script" not in page
    for name in ("report.html", "junit.xml", "traceability.csv", "plan.yaml", "results.yaml"):
        assert (site / name).is_file() and f'href="{name}"' in page
    assert (site / ".nojekyll").exists()


def test_landing_outside_ci_and_usage(
    run_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
    builder = load_builder()
    assert builder.main([]) == 2
    assert "usage" in capsys.readouterr().err
    builder.build(run_dir, tmp_path / "site")
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Built locally on" in page
    assert "https://github.com/muhib-karim/api-vv-toolkit" in page

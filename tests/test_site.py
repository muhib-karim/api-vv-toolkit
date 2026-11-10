"""The Pages landing is built from a real demo run's evidence."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import struct
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from api_vv.execute import execute
from api_vv.io import read_data, write_data
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
    assert '<link rel="canonical" href="https://someone.github.io/fork/">' in page
    assert 'content="https://someone.github.io/fork/og-image.png"' in page
    assert 'name="twitter:card" content="summary_large_image"' in page
    assert (site / "og-image.png").is_file()
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


def test_landing_is_static_self_hosted_and_every_local_link_resolves(
    run_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
    site = tmp_path / "site"
    load_builder().build(run_dir, site)
    page = (site / "index.html").read_text(encoding="utf-8")
    head, body = page.split("<body>")
    # Nothing is fetched from elsewhere: no scripts, fonts, stylesheets or remote images.
    assert "@import" not in page and "url(" not in page and "src=" not in page
    assert 'rel="stylesheet"' not in page and "&#34;" not in head
    links = re.findall(r'<link [^>]*href="([^"]*)"', head)
    assert sorted(link.split(",")[0] for link in links) == [
        "apple-touch-icon.png",
        "apple-touch-icon.png",
        "data:image/svg+xml",
        "https://muhib-karim.github.io/api-vv-toolkit/",
    ]
    # Committed icons, and a share card with the size the tags declare.
    assert (site / "apple-touch-icon.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert 'property="og:image:width" content="1200"' in head
    assert 'property="og:image:height" content="630"' in head
    assert struct.unpack(">II", (site / "og-image.png").read_bytes()[16:24]) == (1200, 630)
    description = re.search(r'name="description" content="([^"]*)"', head)
    assert description is not None and "\n" not in description[1]
    # Landmarks, one h1, a skip link, named navigation and focusable scroll regions.
    assert body.count("<h1") == 1 and "<main>" in body and "<footer" in body
    assert '<a class="skip" href="#run">' in body and 'id="run" tabindex="-1"' in body
    assert '<nav class="nav" aria-label="Sections">' in body
    assert body.count('role="region"') == 2 == body.count('tabindex="0"')
    # In-page anchors hit an id; local files exist; report fragments are rows of the report.
    ids = set(re.findall(r' id="([^"]+)"', body))
    report = (site / "report.html").read_text(encoding="utf-8")
    report_ids = set(re.findall(r' id="([^"]+)"', report))
    hrefs = re.findall(r'href="([^"]*)"', body)
    for href in hrefs:
        if href.startswith("#"):
            assert href[1:] in ids, href
        elif not href.startswith("https://github.com/muhib-karim/api-vv-toolkit"):
            name, _, fragment = href.partition("#")
            assert (site / name).is_file(), href
            assert not fragment or (name == "report.html" and fragment in report_ids), href
    # The strip is the run: one cell per requirement, status in words, failures named.
    plan = Plan.model_validate(read_data(run_dir / "plan.yaml"))
    wanted = {f"report.html#{item.id}" for item in plan.requirements.requirements}
    assert wanted <= set(hrefs) and body.count('<span class="vh">') == len(wanted)
    assert '<span class="ln fail">Gate: FAIL (REQ-003, REQ-008)</span>' in body
    assert "actions/runs" not in page and "/commit/" not in page


def test_site_report_is_the_runs_report_plus_a_way_back(
    run_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef")
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GITHUB_REPOSITORY", "someone/fork")
    site = tmp_path / "site"
    builder = load_builder()
    builder.build(run_dir, site)
    recorded = (run_dir / "report.html").read_text(encoding="utf-8")
    published = (site / "report.html").read_text(encoding="utf-8")
    assert "index.html" not in recorded and published.count('href="index.html"') == 2
    assert published.split("<main>")[1] == recorded.split("<main>")[1]
    # In CI the provenance sentence can be checked: the run and the commit are linked.
    page = (site / "index.html").read_text(encoding="utf-8")
    assert (
        '<a href="https://github.com/someone/fork/actions/runs/4242">Workflow run 4242</a>' in page
    )
    assert (
        '<a href="https://github.com/someone/fork/commit/0123456789abcdef">Commit 0123456</a>'
        in page
    )
    assert builder.transcript_lines("Validated 1\nGate: PASS\n\n") == [
        ("Validated 1", ""),
        ("Gate: PASS", "pass"),
    ]


def test_site_build_refuses_a_report_this_toolkit_did_not_render(
    run_dir: Path, tmp_path: Path
) -> None:
    (run_dir / "report.html").write_text("<!doctype html><title>stale</title>", encoding="utf-8")
    with pytest.raises(ValueError, match=r"scripts/demo\.py"):
        load_builder().build(run_dir, tmp_path / "site")
    assert not (tmp_path / "site").exists()

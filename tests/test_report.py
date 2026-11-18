from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from collections.abc import Set

import pytest

from api_vv.generate import generate, trace_case
from api_vv.io import plan_digest
from api_vv.models import Config, Coverage, Plan, Result, Run
from api_vv.report import (
    HTML_TEMPLATE,
    REPORT_CSS,
    THEME_CSS,
    Matrix,
    csv_report,
    gate_failures,
    html_report,
    junit,
    markdown,
    matrix,
)
from api_vv.spec import parse_document
from tests.conftest import one_operation, requirement_for


def run_with(plan: Plan, failed: Set[str] = frozenset(), missing: Set[str] = frozenset()) -> Run:
    """Pass every enabled case except the ones named, which fail or have no result."""
    results = []
    for case in plan.cases:
        if case.id in missing:
            continue
        if not case.enabled:
            results.append(Result(case_id=case.id, verdict="skipped", errors=["review"]))
        elif case.id in failed:
            results.append(Result(case_id=case.id, verdict="failed", errors=["status: bad"]))
        else:
            results.append(Result(case_id=case.id, verdict="passed", latency_ms=1.5))
    return Run(plan_digest=plan_digest(plan), results=results)


def ids_for(plan: Plan, req_id: str) -> set[str]:
    return {case.id for case in plan.cases if req_id in case.requirement_ids}


def statuses(plan: Plan, run: Run | None) -> dict[str, str]:
    return {row.requirement.id: row.status for row in matrix(plan, run).rows}


def test_status_logic(plan: Plan) -> None:
    assert set(statuses(plan, None).values()) == {"not covered"}
    assert set(statuses(plan, run_with(plan)).values()) == {"verified"}
    failing = statuses(plan, run_with(plan, failed=ids_for(plan, "REQ-008")))
    assert failing["REQ-008"] == "failed" and failing["REQ-001"] == "verified"
    missing = statuses(plan, run_with(plan, missing=ids_for(plan, "REQ-009")))
    assert missing["REQ-009"] == "not covered"


def retrace(plan: Plan) -> None:
    for case in plan.cases:
        trace_case(case, plan.requirements)


def test_partial_coverage(plan: Plan) -> None:
    edited = plan.model_copy(deep=True)
    covers = edited.requirements.requirements[1].covers
    covers.append(
        Coverage(operation_id="createWidget", responses=["422"], checks=["required:name"])
    )
    retrace(edited)
    assert statuses(edited, run_with(edited))["REQ-002"] == "verified"
    # A selector that no passing test satisfies leaves the evidence incomplete.
    covers.append(Coverage(operation_id="createWidget", responses=["422"], checks=["unmatched"]))
    assert statuses(edited, run_with(edited))["REQ-002"] == "partially covered"


def test_matrix_rejects_foreign_results(plan: Plan) -> None:
    run = run_with(plan)
    with pytest.raises(ValueError, match="different plan"):
        matrix(plan, run.model_copy(update={"plan_digest": "0" * 64}))
    run.results.append(Result(case_id="TC-unknown", verdict="passed"))
    with pytest.raises(ValueError, match="unknown case ids"):
        matrix(plan, run)


def test_gate_is_configurable(plan: Plan) -> None:
    # REQ-001 (must) and REQ-012 (should) share the health happy-path case.
    data = matrix(plan, run_with(plan, failed=ids_for(plan, "REQ-012")))
    assert gate_failures(data, Config()) == ["REQ-001"]
    both = Config(gate_priorities=["must", "should"])
    assert gate_failures(data, both) == ["REQ-001", "REQ-012"]
    assert gate_failures(data, Config(gate_statuses=["not covered"])) == []


def test_markdown_and_html(plan: Plan) -> None:
    plan = plan.model_copy(deep=True)
    plan.requirements.requirements[0].text = "Pipes | and <b>tags</b>"
    run = run_with(plan, failed=ids_for(plan, "REQ-008"))
    data = matrix(plan, run)
    text = markdown(data)
    assert "| REQ-008: Deleting a widget returns 204 with no body. | must | failed |" in text
    assert "&#124; and &lt;b&gt;" in text
    assert "## Execution findings" in text and "status: bad" in text
    assert "Execution findings" not in markdown(data, matrix_only=True)
    page = html_report(data)
    assert "<b>tags" not in page and "&lt;b&gt;tags" in page
    assert "<script" not in page and "http" not in page.split("<body>")[1]
    assert 'data-status="failed"' in page and ">failed</span>" in page
    assert "Execution findings" not in html_report(data, matrix_only=True)
    clean = matrix(plan, run_with(plan))
    assert "No execution findings." in markdown(clean)
    assert "No execution findings." in html_report(clean)


def test_csv_round_trip_and_formula_guard(plan: Plan) -> None:
    plan = plan.model_copy(deep=True)
    plan.requirements.requirements[0].text = "=HYPERLINK(1)"
    plan.requirements.requirements[11].covers[0].checks = ["unmatched-check"]
    retrace(plan)
    rows = list(csv.DictReader(io.StringIO(csv_report(matrix(plan, run_with(plan))))))
    first = rows[0]
    assert first["kind"] == "requirement" and first["text"] == "'=HYPERLINK(1)"
    assert first["status"] == "verified" and first["verdict"] == "passed"
    kinds = {row["kind"] for row in rows}
    assert kinds == {"requirement", "untraced"}
    empty = next(row for row in rows if row["requirement_id"] == "REQ-012")
    assert empty["case_id"] == "" and empty["verdict"] == "not run"
    untraced = {row["case_id"] for row in rows if row["kind"] == "untraced"}
    assert untraced == {case.id for case in plan.cases if not case.requirement_ids}


def test_csv_lists_unmapped_operations(plan: Plan) -> None:
    plan = plan.model_copy(deep=True)
    plan.requirements.requirements = [
        req for req in plan.requirements.requirements if req.id != "REQ-008"
    ]
    for case in plan.cases:
        case.requirement_ids = [r for r in case.requirement_ids if r != "REQ-008"]
    data = matrix(plan, None)
    assert data.operations_without_requirements == ["deleteWidget"]
    rows = list(csv.reader(io.StringIO(csv_report(data))))
    assert ["unmapped-operation", "", "", "", "", "", "deleteWidget", "", ""] in rows
    assert "Operations without requirements: deleteWidget" in markdown(data)


def test_junit_parses_back(plan: Plan) -> None:
    plan = plan.model_copy(deep=True)
    plan.cases[0].enabled = False
    plan.cases[0].review_reason = "needs review"
    failed = ids_for(plan, "REQ-003")
    run = run_with(plan, failed=failed, missing={plan.cases[1].id})
    root = ET.fromstring(junit(plan, matrix(plan, run), Config()))
    cases = root.findall("testcase")
    assert int(root.get("tests", "0")) == len(cases) == len(plan.cases) + 12
    by_name = {node.get("name"): node for node in cases}
    (case_id,) = failed
    failure = by_name[case_id].find("failure")
    assert failure is not None and failure.get("message") == "status: bad"
    requirement = by_name["REQ-003"].find("failure")
    assert requirement is not None and requirement.get("message") == "failed"
    skipped = by_name[plan.cases[0].id].find("skipped")
    assert skipped is not None and skipped.get("message") == "needs review"
    prop = by_name[case_id].find("properties/property")
    assert prop is not None and prop.get("value") == "REQ-003"
    assert root.get("failures") == str(len(root.findall("testcase/failure")))
    assert root.get("skipped") == str(len(root.findall("testcase/skipped")))


def test_html_matrix_is_accessible_and_responsive(plan: Plan) -> None:
    run = run_with(plan, failed=ids_for(plan, "REQ-008"))
    data = matrix(plan, run)
    page = html_report(data, gate=["REQ-008"])
    body = page.split("<body>")[1]
    # Landmarks, skip link, captioned table with scoped headers.
    assert '<html lang="en">' in page and 'name="viewport"' in page
    assert '<a class="skip" href="#matrix">' in body
    assert "<main" in body and "<header" in body and "<footer" in body
    assert "<caption>" in body and body.count('scope="col"') == 4
    # Status is never conveyed by colour alone: icon is decorative, the word is visible.
    assert 'aria-hidden="true"' in body and "<svg" in body
    # Stacked layout on narrow screens, dark mode, reduced motion and a no-JS filter.
    assert "@media (max-width: 720px)" in page
    assert "prefers-color-scheme: dark" in page
    assert '<input type="checkbox" id="only-open"' in body and '<label for="only-open"' in body
    assert "<script" not in page
    # Requirement -> tests -> result, with the evidence for failures.
    assert "Gate: FAIL (REQ-008)" in body
    row = body.split('id="REQ-008"')[1].split("</tr>")[0]
    assert "deleteWidget" in row and "DELETE /widgets/{widget_id}" in row
    assert "status: bad" in row and "<details" in row
    assert f"{len(data.untraced_tests)} untraced tests" in body
    assert plan.spec.title in body


def test_html_without_results_or_gate(plan: Plan) -> None:
    page = html_report(matrix(plan, None), matrix_only=True)
    assert "Gate:" not in page
    assert ">not run</span>" in page


def test_junit_stays_well_formed_with_control_characters(plan: Plan) -> None:
    """Error paths repeat response keys, and a server may send any character in a key."""
    failed = ids_for(plan, "REQ-003")
    run = run_with(plan, failed=failed)
    (case_id,) = failed
    result = next(item for item in run.results if item.case_id == case_id)
    result.errors = ["body schema: /bad\x01key\x1b[0m [type]"]
    root = ET.fromstring(junit(plan, matrix(plan, run), Config()))
    node = next(item for item in root.iter("testcase") if item.get("name") == case_id)
    failure = node.find("failure")
    assert failure is not None
    assert failure.get("message") == "body schema: /bad\ufffdkey\ufffd[0m [type]"
    assert failure.text == failure.get("message")


def test_markdown_escapes_untraced_case_ids(plan: Plan) -> None:
    """Case ids are free text in a hand-edited plan and end up in the CI job summary."""
    plan = plan.model_copy(deep=True)
    untraced = next(case for case in plan.cases if not case.requirement_ids)
    untraced.id = "TC|x <img src=x>"
    text = markdown(matrix(plan, None))
    assert "TC&#124;x &lt;img src=x&gt;" in text and "<img" not in text


def test_html_counts_only_executed_tests_as_run(plan: Plan) -> None:
    plan = plan.model_copy(deep=True)
    plan.cases[0].enabled = False
    plan.cases[0].review_reason = "needs review"
    run = run_with(plan)
    assert [item.verdict for item in run.results].count("skipped") == 1
    page = html_report(matrix(plan, run))
    assert f"<dt>tests run</dt><dd>{len(run.results) - 1}</dd>" in page


def test_html_report_is_one_file_and_every_link_lands(plan: Plan) -> None:
    data = matrix(plan, run_with(plan, failed=ids_for(plan, "REQ-008")))
    page = html_report(data, gate=["REQ-008"])
    head, body = page.split("<body>")
    # Inline styles and an inline icon: nothing is fetched, and the CSS is not HTML-escaped.
    assert '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,' in head
    assert "url(" not in page and "@import" not in page and "src=" not in page
    assert "&#34;" not in head and "&gt;" not in head
    assert HTML_TEMPLATE.isascii() and (THEME_CSS + REPORT_CSS).isascii()
    assert "\\" not in THEME_CSS + REPORT_CSS
    # Without ``home_url`` every link stays inside the page and resolves to an id.
    hrefs = re.findall(r'href="([^"]*)"', body)
    ids = set(re.findall(r' id="([^"]+)"', body))
    assert hrefs and all(href.startswith("#") and href[1:] in ids for href in hrefs)
    # One jump chip per requirement, status in words, placed before the skip target.
    assert '<nav class="jump" aria-label="Requirements">' in body
    assert {f"#{row.requirement.id}" for row in data.rows} <= set(hrefs)
    assert body.count('<span class="vh">') == len(data.rows)
    assert body.index('class="jump"') < body.index('id="matrix"')
    assert '<nav class="nav" aria-label="Report sections">' in body and body.count("<h1") == 1


def test_html_report_home_link_is_opt_in(plan: Plan) -> None:
    data = matrix(plan, run_with(plan))
    plain = html_report(data)
    assert "index.html" not in plain and "Overview" not in plain
    linked = html_report(data, home_url="index.html")
    # The brand and one labelled link lead back; the rest of the page is unchanged.
    assert linked.count('href="index.html"') == 2 and "Overview" in linked
    assert linked.split("<main>")[1] == plain.split("<main>")[1]


def test_html_filter_empty_state_exists_only_when_all_verified(plan: Plan) -> None:
    clean = html_report(matrix(plan, run_with(plan)))
    assert '<tr class="all-clear">' in clean and "Every requirement is verified" in clean
    failing = html_report(matrix(plan, run_with(plan, failed=ids_for(plan, "REQ-008"))))
    assert (
        '<tr class="all-clear">' not in failing and "Every requirement is verified" not in failing
    )
    assert '<tr class="all-clear">' not in html_report(matrix(plan, None))


def test_html_report_renders_sparse_matrices(plan: Plan) -> None:
    """A render error would also lose the Markdown, CSV and JUnit files written beside it."""
    empty = Matrix(rows=[], untraced_tests=[], operations_without_requirements=[], results={})
    page = html_report(empty, gate=[])
    assert "Gate: PASS" in page and "API: verification and validation report" in page
    assert "0 requirements traced to 0 tests" in page and 'class="jump"' not in page
    # Hand-built, without the optional display context: counts still come out right.
    first = matrix(plan, run_with(plan)).rows[0]
    bare = Matrix(
        rows=[first],
        untraced_tests=["TC-a", "TC-b"],
        operations_without_requirements=["listWidgets"],
        results={},
    )
    page = html_report(bare, matrix_only=True)
    assert f"1 requirements traced to {len(first.cases)} tests" in page
    assert "2 untraced tests" in page and "listWidgets" in page
    # A verdict the palette has no colour for still renders, as a neutral badge.
    odd = first.model_copy(update={"verdicts": {case.id: "flaky" for case in first.cases}})
    assert ">flaky</span>" in html_report(bare.model_copy(update={"rows": [odd]}))


def one_case_plan() -> Plan:
    """GET /a with only a 200: generation yields exactly one enabled happy-path case."""
    spec = parse_document(one_operation({"200": {"description": "ok"}}))
    return generate(spec, requirement_for("a"))


@pytest.mark.parametrize("review_verdict", ["skipped", "not run"])
def test_disabled_review_case_does_not_block_verified(review_verdict: str) -> None:
    plan = one_case_plan()
    (happy,) = plan.cases
    review = happy.model_copy(
        deep=True, update={"id": "TC-manual-review", "enabled": False, "review_reason": "manual"}
    )
    plan.cases.append(review)
    results = [Result(case_id=happy.id, verdict="passed")]
    if review_verdict == "skipped":
        results.append(Result(case_id=review.id, verdict="skipped", errors=["manual"]))
    data = matrix(plan, Run(plan_digest=plan_digest(plan), results=results))
    (row,) = data.rows
    assert row.verdicts[review.id] == review_verdict
    assert row.status == "verified"
    assert gate_failures(data, Config()) == []


@pytest.mark.parametrize("extra_verdict", ["skipped", "not run"])
def test_enabled_case_that_did_not_pass_still_blocks_verified(extra_verdict: str) -> None:
    plan = one_case_plan()
    (happy,) = plan.cases
    extra = happy.model_copy(deep=True, update={"id": "TC-enabled-extra"})
    plan.cases.append(extra)
    results = [Result(case_id=happy.id, verdict="passed")]
    if extra_verdict == "skipped":
        results.append(Result(case_id=extra.id, verdict="skipped", errors=["hand-edited"]))
    data = matrix(plan, Run(plan_digest=plan_digest(plan), results=results))
    (row,) = data.rows
    assert row.verdicts[extra.id] == extra_verdict
    assert row.status == "partially covered"
    assert gate_failures(data, Config()) == ["REQ-001"]

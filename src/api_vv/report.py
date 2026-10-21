"""Traceability is computed from evidence, never from the presence of generated tests."""

from __future__ import annotations

import csv
import html
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from jinja2 import Environment
from pydantic import Field

from api_vv import __version__
from api_vv.execute import validate_plan
from api_vv.generate import matches
from api_vv.io import plan_digest
from api_vv.models import Case, Config, Model, Plan, Requirement, Result, Run

Status = Literal["verified", "failed", "not covered", "partially covered"]


class Row(Model):
    requirement: Requirement
    status: Status
    cases: list[Case]
    verdicts: dict[str, str]


class Matrix(Model):
    rows: list[Row]
    untraced_tests: list[str]
    operations_without_requirements: list[str]
    results: dict[str, Result]
    # Display context for reports; optional so a hand-built Matrix still renders.
    title: str = ""
    cases: dict[str, Case] = Field(default_factory=dict)
    endpoints: dict[str, str] = Field(default_factory=dict)


def matrix(plan: Plan, run: Run | None = None) -> Matrix:
    validate_plan(plan)
    if run is not None and run.plan_digest != plan_digest(plan):
        raise ValueError("results belong to a different plan; execute the edited plan again")
    results = {result.case_id: result for result in run.results} if run else {}
    if results.keys() - {case.id for case in plan.cases}:
        raise ValueError("results contain unknown case ids")
    rows: list[Row] = []
    for requirement in plan.requirements.requirements:
        cases = [case for case in plan.cases if requirement.id in case.requirement_ids]
        verdicts = {
            case.id: results[case.id].verdict if case.id in results else "not run" for case in cases
        }
        passed = [case for case in cases if verdicts[case.id] == "passed"]
        covered = all(
            any(
                matches(case, cover.operation_id, [response], [check] if check else [])
                for case in passed
            )
            for cover in requirement.covers
            for response in cover.responses
            for check in (cover.checks or [""])
        )
        status: Status
        if "failed" in verdicts.values():
            status = "failed"
        elif not passed:
            status = "not covered"
        elif covered and all(value == "passed" for value in verdicts.values()):
            status = "verified"
        else:
            status = "partially covered"
        rows.append(Row(requirement=requirement, status=status, cases=cases, verdicts=verdicts))
    mapped_ops = {
        cover.operation_id
        for requirement in plan.requirements.requirements
        for cover in requirement.covers
    }
    return Matrix(
        rows=rows,
        untraced_tests=[case.id for case in plan.cases if not case.requirement_ids],
        operations_without_requirements=sorted(plan.spec.operations.keys() - mapped_ops),
        results=results,
        title=plan.spec.title,
        cases={case.id: case for case in plan.cases},
        endpoints={op.id: f"{op.method} {op.path}" for op in plan.spec.operations.values()},
    )


def gate_failures(data: Matrix, config: Config) -> list[str]:
    return [
        row.requirement.id
        for row in data.rows
        if row.requirement.priority in config.gate_priorities and row.status in config.gate_statuses
    ]


def escaped(value: str) -> str:
    return html.escape(value).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def markdown(data: Matrix, *, matrix_only: bool = False) -> str:
    lines = [
        "# API V&V report",
        "",
        "| Requirement | Priority | Status | Test cases → latest verdict |",
        "| --- | --- | --- | --- |",
    ]
    for row in data.rows:
        tests = "; ".join(f"{case.id} → {row.verdicts[case.id]}" for case in row.cases) or "—"
        lines.append(
            f"| {row.requirement.id}: {escaped(row.requirement.text)} | "
            f"{row.requirement.priority} | {row.status} | {escaped(tests)} |"
        )
    lines += [
        "",
        "Untraced tests: " + (", ".join(data.untraced_tests) or "none"),
        "",
        "Operations without requirements: "
        + (", ".join(map(escaped, data.operations_without_requirements)) or "none"),
    ]
    if not matrix_only:
        lines += ["", "## Execution findings", ""]
        findings = [result for result in data.results.values() if result.errors]
        lines += [
            f"- {escaped(result.case_id)} ({result.verdict}): {escaped('; '.join(result.errors))}"
            for result in findings
        ] or ["No execution findings."]
    return "\n".join(lines) + "\n"


ICONS = {
    # Decorative: every status is also spelled out in text next to its icon.
    "verified": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "passed": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "failed": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "partially covered": '<circle cx="12" cy="12" r="7.5"/><path d="M12 4.5v15"/>',
    "not covered": '<circle cx="12" cy="12" r="7.5"/><path d="M8 12h8"/>',
    "skipped": '<path d="M8 6.5l6 5.5-6 5.5M16.5 6.5v11"/>',
    "not run": '<circle cx="12" cy="12" r="7.5"/>',
}

HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{{ data.title or 'API' }}: V&amp;V traceability report</title><style>
:root{--bg:#f6f7f9;--surface:#fff;--fg:#121a24;--muted:#4a5565;--line:#d5dae1;
--accent:#1d4ed8;--pass:#166534;--pass-bg:#e3f4e8;--fail:#a61b1b;--fail-bg:#fbe7e7;
--warn:#8a4b00;--warn-bg:#fdf1dc;--idle:#475266;--idle-bg:#eceff3;
--mono:ui-monospace,"SFMono-Regular","JetBrains Mono",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
@media (prefers-color-scheme: dark){:root{--bg:#0e141b;--surface:#151d27;--fg:#e8edf3;
--muted:#a3afbf;--line:#2b3746;--accent:#8ab4ff;--pass:#7ee2a0;--pass-bg:#12301f;
--fail:#ff9d9d;--fail-bg:#3a1618;--warn:#f5c56b;--warn-bg:#352711;--idle:#b4bfcd;
--idle-bg:#222c39}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 var(--sans);
font-variant-numeric:tabular-nums}
::selection{background:var(--accent);color:var(--surface)}
a{color:var(--accent);text-underline-offset:.18em}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:2px}
.skip{position:absolute;left:1rem;top:-3rem;background:var(--surface);padding:.6rem 1rem;
border:1px solid var(--line);z-index:1}
.skip:focus{top:1rem}
.wrap{max-width:76rem;margin:0 auto;padding:1.5rem 1rem 3rem}
header h1{font-size:clamp(1.45rem,1.1rem + 1.6vw,2.1rem);line-height:1.2;margin:0 0 .35rem;
letter-spacing:-.015em;text-wrap:balance}
.scope{color:var(--muted);max-width:68ch;margin:0 0 1.25rem}
.gate{display:inline-flex;align-items:center;gap:.5rem;font-weight:650;
padding:.45rem .8rem;border-radius:.4rem;margin:0 0 1rem}
.gate svg{width:1.2rem;height:1.2rem;fill:none;stroke:currentColor;stroke-width:2.6;
stroke-linecap:round;stroke-linejoin:round;flex:none}
.gate.pass{background:var(--pass-bg);color:var(--pass)}
.gate.fail{background:var(--fail-bg);color:var(--fail)}
.tally{display:flex;flex-wrap:wrap;gap:.35rem 1.6rem;margin:0 0 1.75rem;padding:0}
.tally div{display:flex;align-items:baseline;gap:.4rem}
.tally dt{color:var(--muted);order:2}
.tally dd{margin:0;font-weight:700;font-size:1.15rem}
h2{font-size:1.2rem;margin:2.25rem 0 .6rem}
.tools{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem 1.25rem;margin:0 0 .75rem}
.tools label{display:inline-flex;align-items:center;gap:.55rem;min-height:44px;cursor:pointer}
.tools input{width:1.15rem;height:1.15rem;accent-color:var(--accent)}
.legend{color:var(--muted);font-size:.9rem}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--surface);
border:1px solid var(--line);border-radius:.5rem}
caption{text-align:left;color:var(--muted);padding:0 0 .5rem;caption-side:top}
th,td{padding:.75rem .85rem;text-align:left;vertical-align:top;
border-bottom:1px solid var(--line)}
thead th{font-size:.85rem;font-weight:650;color:var(--muted);background:var(--bg)}
thead th:first-child{border-top-left-radius:.5rem}
thead th:last-child{border-top-right-radius:.5rem}
tbody tr:last-child>*{border-bottom:0}
.req-id{font:600 .9rem var(--mono);display:block;margin-bottom:.15rem}
.req-text{max-width:46ch}
.badge{display:inline-flex;align-items:center;gap:.3rem;white-space:nowrap;font-weight:600;
font-size:.85rem;padding:.12rem .5rem .12rem .35rem;border-radius:999px}
.badge svg{width:1rem;height:1rem;fill:none;stroke:currentColor;stroke-width:2.4;
stroke-linecap:round;stroke-linejoin:round;flex:none}
.s-verified,.s-passed{color:var(--pass);background:var(--pass-bg)}
.s-failed{color:var(--fail);background:var(--fail-bg)}
.s-partially-covered{color:var(--warn);background:var(--warn-bg)}
.s-not-covered,.s-skipped,.s-not-run{color:var(--idle);background:var(--idle-bg)}
.tests{list-style:none;margin:0;padding:0;display:grid;gap:.55rem}
.test{display:grid;grid-template-columns:1fr auto;gap:.1rem .75rem;align-items:start}
.test-name{overflow-wrap:anywhere}
.test-meta{grid-column:1/-1;color:var(--muted);font-size:.85rem;overflow-wrap:anywhere}
code{font:.85rem var(--mono);overflow-wrap:anywhere}
details{grid-column:1/-1;font-size:.88rem}
summary{cursor:pointer;color:var(--fail);font-weight:600;min-height:28px}
details ul{margin:.3rem 0 0;padding-left:1.1rem}
.none{color:var(--muted)}
.more summary{color:var(--accent)}
.more ul{columns:18rem;column-gap:2rem;padding-left:1.1rem}
.more li{break-inside:avoid;margin:0 0 .35rem}
footer{margin-top:2.5rem;color:var(--muted);font-size:.85rem}
body:has(#only-open:checked) tr[data-status="verified"]{display:none}
@media (max-width: 720px){
table,thead,tbody,tr,th,td{display:block}
table{border:0;background:none}
thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
tbody tr{background:var(--surface);border:1px solid var(--line);border-radius:.5rem;
margin:0 0 .85rem;padding:.35rem 0}
td{border:0;padding:.45rem .9rem}
caption{display:block}
td[data-label="Priority"],td[data-label="Status"]{display:inline-block;vertical-align:top;
padding-right:1.5rem}
td[data-label]::before{content:attr(data-label);display:block;font-size:.78rem;
font-weight:650;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.req-text{max-width:none}
}
@media (prefers-reduced-motion: reduce){*{scroll-behavior:auto!important}}
@media print{.tools,.skip{display:none}body{background:#fff}}
</style></head><body>
{%- macro icon(status) -%}
<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{{ icons[status]|safe }}</svg>
{%- endmacro -%}
{%- macro badge(status) -%}
<span class="badge s-{{ status|replace(' ', '-') }}">{{ icon(status) }}{{ status }}</span>
{%- endmacro -%}
{%- macro test_item(case, verdict) -%}
{%- set result = data.results.get(case.id) -%}
<li class="test"><span class="test-name"><code>{{ case.id }}</code> {{ case.name }}</span>
{{ badge(verdict) }}
<span class="test-meta">{{ data.endpoints.get(case.operation_id, case.operation_id) }}
· expects {{ case.expected_status }}
{%- if result and result.actual_status %} · got {{ result.actual_status }}{% endif %}
{%- if result and result.latency_ms is not none %} · {{ '%.0f'|format(result.latency_ms) }} ms
{%- endif %}</span>
{%- if result and result.errors and result.verdict == 'failed' %}
<details><summary>Why it failed</summary><ul>
{%- for error in result.errors %}<li>{{ error }}</li>{% endfor %}</ul></details>
{%- endif %}</li>
{%- endmacro -%}
<a class="skip" href="#matrix">Skip to the traceability matrix</a>
<div class="wrap"><header>
<h1>{{ data.title or 'API' }}: verification and validation report</h1>
<p class="scope">Results describe this recorded run only. The bundled demo uses deliberately
seeded defects; its output is not a production service certification.</p>
{% if gate is not none %}<p class="gate {{ 'fail' if gate else 'pass' }}" role="status">
{{- icon('failed' if gate else 'verified') }}
{%- if gate %}Gate: FAIL ({{ gate|join(', ') }}){% else %}Gate: PASS{% endif %}</p>{% endif %}
<dl class="tally" aria-label="Summary">
{%- for status in statuses %}<div><dt>{{ status }}</dt><dd>{{ counts[status] }}</dd></div>
{%- endfor %}<div><dt>tests run</dt><dd>{{ data.results|length }}</dd></div>
</dl></header>
<main id="matrix" tabindex="-1">
<h2>Requirements, tests and results</h2>
<div class="tools"><label for="only-open"><input type="checkbox" id="only-open">
Show only requirements that are not verified</label>
<span class="legend">Each requirement links to the tests that check it and their latest
verdict.</span></div>
<table><caption>{{ data.rows|length }} requirements traced to
{{ data.cases|length - data.untraced_tests|length }} tests</caption>
<thead><tr><th scope="col">Requirement</th><th scope="col">Priority</th>
<th scope="col">Status</th><th scope="col">Tests and latest verdict</th></tr></thead>
<tbody>
{%- for row in data.rows %}
<tr id="{{ row.requirement.id }}" data-status="{{ row.status }}">
<td><span class="req-id">{{ row.requirement.id }}</span>
<span class="req-text">{{ row.requirement.text }}</span></td>
<td data-label="Priority">{{ row.requirement.priority }}</td>
<td data-label="Status">{{ badge(row.status) }}</td>
<td data-label="Tests">{% if row.cases %}<ul class="tests">
{%- for case in row.cases %}{{ test_item(case, row.verdicts[case.id]) }}{% endfor %}
</ul>{% else %}<span class="none">No test traces to this requirement.</span>{% endif %}</td>
</tr>
{%- endfor %}
</tbody></table>
<h2>Coverage gaps</h2>
<details class="more"><summary>{{ data.untraced_tests|length }} untraced tests</summary>
<p class="legend">Tests that ran but that no requirement claims: a requirement may be missing,
or the test may be unnecessary.</p>
{% if data.untraced_tests %}<ul>{% for case_id in data.untraced_tests %}
{%- set case = data.cases.get(case_id) %}
{%- set result = data.results.get(case_id) %}<li><code>{{ case_id }}</code>
{% if case %}{{ case.name }}{% endif %} {{ badge(result.verdict if result else 'not run') }}</li>
{%- endfor %}</ul>{% else %}<p>None.</p>{% endif %}</details>
<p>Operations without requirements:
{{ data.operations_without_requirements|join(', ') or 'none' }}</p>
{% if not matrix_only %}<h2>Execution findings</h2><ul>
{%- for result in data.results.values() if result.errors %}<li><code>{{ result.case_id }}</code>
({{ result.verdict }}): {{ result.errors|join('; ') }}</li>
{%- else %}<li>No execution findings.</li>{% endfor %}
</ul>{% endif %}</main>
<footer>Generated by api-vv-toolkit {{ version }}. Requirement status comes from executed
evidence, never from the mere presence of a generated test.</footer></div>
</body></html>
"""

STATUSES = ("verified", "failed", "partially covered", "not covered")


def html_report(data: Matrix, *, matrix_only: bool = False, gate: list[str] | None = None) -> str:
    """Static, script-free page; ``gate`` (failing requirement ids) adds the gate verdict."""
    counts = {status: sum(row.status == status for row in data.rows) for status in STATUSES}
    return (
        Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
        .from_string(HTML_TEMPLATE)
        .render(
            data=data,
            matrix_only=matrix_only,
            gate=gate,
            icons=ICONS,
            statuses=STATUSES,
            counts=counts,
            version=__version__,
        )
    )


def csv_report(data: Matrix) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)

    def safe(value: str) -> str:
        # Quoting alone does not stop spreadsheet formula execution.
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value

    writer.writerow(
        [
            "kind",
            "requirement_id",
            "text",
            "priority",
            "status",
            "case_id",
            "operation_id",
            "expected_status",
            "verdict",
        ]
    )
    for row in data.rows:
        prefix = [
            "requirement",
            row.requirement.id,
            safe(row.requirement.text),
            row.requirement.priority,
            row.status,
        ]
        if not row.cases:
            writer.writerow(prefix + ["", "", "", "not run"])
        for case in row.cases:
            writer.writerow(
                prefix
                + [
                    safe(case.id),
                    safe(case.operation_id),
                    case.expected_status,
                    row.verdicts[case.id],
                ]
            )
    for case_id in data.untraced_tests:
        result = data.results.get(case_id)
        writer.writerow(
            [
                "untraced",
                "",
                "",
                "",
                "",
                safe(case_id),
                "",
                "",
                result.verdict if result else "not run",
            ]
        )
    for operation_id in data.operations_without_requirements:
        writer.writerow(["unmapped-operation", "", "", "", "", "", safe(operation_id), "", ""])
    return output.getvalue()


def junit(plan: Plan, data: Matrix, config: Config) -> str:
    suite = ET.Element("testsuite", name="api-vv", tests=str(len(plan.cases) + len(data.rows)))
    failures = 0
    skipped = 0
    for case in plan.cases:
        result = data.results.get(case.id)
        node = ET.SubElement(
            suite,
            "testcase",
            name=case.id,
            classname=case.operation_id,
            time=f"{(result.latency_ms or 0) / 1000:.6f}" if result else "0",
        )
        properties = ET.SubElement(node, "properties")
        ET.SubElement(
            properties, "property", name="requirements", value=",".join(case.requirement_ids)
        )
        if result is None or result.verdict == "skipped":
            ET.SubElement(node, "skipped", message=case.review_reason or "not run")
            skipped += 1
        elif result.verdict == "failed":
            ET.SubElement(node, "failure", message="; ".join(result.errors)).text = "\n".join(
                result.errors
            )
            failures += 1
    gated = set(gate_failures(data, config))
    for row in data.rows:
        node = ET.SubElement(suite, "testcase", name=row.requirement.id, classname="requirements")
        if row.requirement.id in gated:
            ET.SubElement(node, "failure", message=row.status)
            failures += 1
        elif row.status != "verified":
            ET.SubElement(node, "skipped", message=row.status)
            skipped += 1
    suite.set("failures", str(failures))
    suite.set("skipped", str(skipped))
    suite.set("errors", "0")
    ET.indent(suite)
    return ET.tostring(suite, encoding="unicode", xml_declaration=True) + "\n"


def write_reports(plan: Plan, run: Run, directory: str | Path, config: Config) -> Matrix:
    data = matrix(plan, run)
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    formats = {
        "report.md": markdown(data),
        "report.html": html_report(data, gate=gate_failures(data, config)),
        "traceability.csv": csv_report(data),
        "junit.xml": junit(plan, data, config),
    }
    for name, content in formats.items():
        (target / name).write_text(content, encoding="utf-8")
    return data

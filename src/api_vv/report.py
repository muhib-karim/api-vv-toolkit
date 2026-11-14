"""Traceability is computed from evidence, never from the presence of generated tests."""

from __future__ import annotations

import csv
import html
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal
from urllib.parse import quote

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
        elif covered and all(verdicts[case.id] == "passed" for case in cases if case.enabled):
            # Disabled review cases never run; coverage alone decides once nothing enabled is open.
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
        "Untraced tests: " + (", ".join(map(escaped, data.untraced_tests)) or "none"),
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
    # Chrome shared with the Pages landing (scripts/build_site.py).
    "breaking": '<path d="M12 4.5l8.5 15h-17zM12 10.5v4M12 17.3v.2"/>',
    "non-breaking": '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="1.2"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "back": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "external": '<path d="M8 7h9v9M17 7L7 17"/>',
}

# The mark: a trace line that resolves into a check. ``tile`` and ``trace`` are themed in CSS.
MARK = (
    '<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">'
    '<rect class="tile" x="1" y="1" width="30" height="30" rx="7"/>'
    '<path class="trace" d="M6 17h5.5l3.5 4.5L25 10" fill="none" stroke-width="3" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
# Inline so the report stays one self-contained file; follows the browser's colour scheme.
FAVICON = "data:image/svg+xml," + quote(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><style>'
    ".t{fill:#1c1917}.c{stroke:#f7f5f0}"
    "@media (prefers-color-scheme:dark){.t{fill:#f1ebe0}.c{stroke:#14110f}}</style>"
    '<rect class="t" x="1" y="1" width="30" height="30" rx="7"/>'
    '<path class="c" d="M6 17h5.5l3.5 4.5L25 10" fill="none" stroke-width="3" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

# One design system for this report and the Pages landing. Colour is reserved for verdicts:
# chrome is paper and ink, and each status colour always travels with an icon and a word.
# Every text pair below measures at least 4.5:1 in its own theme. The CSS is passed to
# ``render`` and emitted with ``|safe`` (a ``{#`` inside the template source would open a
# Jinja comment); it stays ASCII and backslash-free so plain string literals are safe.
_LIGHT = (
    "--paper:#f7f5f0;--surface:#fffdf9;--sunken:#efece5;--ink:#1c1917;--ink-2:#57514b;"
    "--rule:#dcd7cd;--edge:#8a8279;--frame:#1c1917;--link:#2f3fbf;--mark:#e9e9fb;"
    "--grid:rgba(28,25,23,.06);--pass:#136c3a;--pass-bg:#e2f1e5;--fail:#a4161a;"
    "--fail-bg:#fbe6e4;--warn:#7a4a00;--warn-bg:#fbeed5;--idle:#4b4640;--idle-bg:#ece8e0;"
    "--code-bg:#1b1815;--code-rule:#3a342e"
)
_DARK = (
    "--paper:#14110f;--surface:#1d1916;--sunken:#0f0d0b;--ink:#f1ebe0;--ink-2:#b5aca0;"
    "--rule:#38322c;--edge:#8a8177;--frame:#8a8177;--link:#b3bcff;--mark:#262645;"
    "--grid:rgba(241,235,224,.05);--pass:#7fdca0;--pass-bg:#12301f;--fail:#ff9f97;"
    "--fail-bg:#3d1716;--warn:#f3c56b;--warn-bg:#382a10;--idle:#b9b0a5;--idle-bg:#2a2520;"
    "--code-bg:#0c0a09;--code-rule:#2e2924"
)

THEME_CSS = (
    ":root{color-scheme:light dark;" + _LIGHT + ";"
    """--code-fg:#ece6da;--code-dim:#b3a99b;--code-pass:#8fe0aa;--code-fail:#ffa39b;
--serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua","URW Palladio L",P052,
Georgia,serif;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"SFMono-Regular","Cascadia Mono","JetBrains Mono",Menlo,Consolas,
"DejaVu Sans Mono",monospace}
"""
    "@media (prefers-color-scheme: dark){:root{" + _DARK + "}}"
    """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:1rem/1.6 var(--sans);
font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
::selection{background:var(--ink);color:var(--paper)}
h1,h2,h3,p,dl,dd,ul,ol,figure{margin:0}
h1,h2{font-family:var(--serif);font-weight:400;letter-spacing:-.015em;text-wrap:balance}
a{color:var(--link);text-decoration-thickness:.07em;text-underline-offset:.2em}
a:hover{text-decoration-thickness:.14em}
:focus-visible{outline:3px solid var(--link);outline-offset:3px;border-radius:.25rem}
code,pre{font-family:var(--mono)}
code{font-size:.875em;overflow-wrap:anywhere}
.i{width:1em;height:1em;flex:none;fill:none;stroke:currentColor;stroke-width:2.4;
stroke-linecap:round;stroke-linejoin:round}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);
white-space:nowrap}
.skip{position:absolute;left:1rem;top:-5rem;z-index:30;padding:.65rem 1rem;
border-radius:.4rem;background:var(--ink);color:var(--paper);font-weight:650}
.skip:focus{top:.75rem}
.wrap{max-width:76rem;margin-inline:auto;padding-inline:clamp(1rem,4vw,2.5rem)}
.label{color:var(--ink-2);font:600 .75rem/1.3 var(--mono);letter-spacing:.08em;
text-transform:uppercase}
.paper{position:relative;isolation:isolate}
.paper::before{content:"";position:absolute;inset:0;z-index:-1;
background-image:linear-gradient(var(--grid) 1px,transparent 1px),
linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:2rem 2rem;
-webkit-mask-image:linear-gradient(#000 30%,transparent);
mask-image:linear-gradient(#000 30%,transparent)}
.bar{position:relative;z-index:10;background:var(--paper);border-bottom:1px solid var(--rule)}
.bar-in{display:flex;flex-wrap:wrap;align-items:center;column-gap:1.25rem;min-height:3.5rem}
.brand{display:inline-flex;align-items:center;gap:.6rem;min-height:2.75rem;color:var(--ink);
font:650 1rem/1 var(--mono);letter-spacing:-.02em;text-decoration:none}
.brand svg{flex:none;width:1.75rem;height:1.75rem}
.tile{fill:var(--ink)}
.trace{stroke:var(--paper)}
.ver{padding:.2rem .5rem;border:1px solid var(--rule);border-radius:999px;color:var(--ink-2);
font:500 .75rem/1.2 var(--mono);letter-spacing:0}
.nav{order:3;flex-basis:100%;margin-inline:-.6rem}
.nav ul{display:flex;flex-wrap:wrap;padding:0;list-style:none}
.nav a{display:inline-flex;align-items:center;min-height:2.75rem;padding:0 .6rem;
border-radius:.3rem;color:var(--ink-2);font-size:.9375rem;font-weight:500;text-decoration:none}
.nav a:hover{background:var(--sunken);color:var(--ink)}
.bar-act{display:flex;align-items:center;gap:.25rem 1rem;margin-left:auto}
.bar-act>a:not(.btn){display:inline-flex;align-items:center;gap:.3rem;min-height:2.75rem;
color:var(--ink);font-size:.9375rem;font-weight:500}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.5rem;
min-height:2.75rem;padding:.5rem 1.1rem;border:1.5px solid var(--ink);border-radius:.45rem;
background:var(--paper);color:var(--ink);font-weight:650;line-height:1.2;text-decoration:none}
.btn.primary{background:var(--ink);color:var(--paper)}
.btn.sm{min-height:2.5rem;padding:.35rem .85rem;font-size:.9375rem}
.btn:hover{box-shadow:3px 3px 0 var(--edge);transform:translate(-2px,-2px)}
.btn:active{box-shadow:none;transform:none}
.badge{display:inline-flex;align-items:center;gap:.3rem;padding:.15rem .55rem .15rem .4rem;
border:1px solid transparent;border-radius:999px;background:var(--idle-bg);color:var(--idle);
font:600 .8125rem/1.3 var(--sans);white-space:nowrap}
.s-verified,.s-passed{background:var(--pass-bg);color:var(--pass)}
.s-failed,.s-breaking{background:var(--fail-bg);color:var(--fail)}
.s-partially-covered{background:var(--warn-bg);color:var(--warn)}
.gate{display:flex;align-items:center;gap:.75rem;padding:.7rem .9rem;border:1.5px solid;
border-radius:.5rem;font:700 1rem/1.35 var(--mono);overflow-wrap:anywhere;
text-wrap:balance}
.gate.fail{background:var(--fail-bg);color:var(--fail)}
.gate.pass{background:var(--pass-bg);color:var(--pass)}
.seal{display:grid;flex:none;place-items:center;width:2rem;height:2rem;border-radius:50%;
background:currentColor}
.seal .i{width:1.15rem;height:1.15rem;stroke-width:3}
.gate.fail .seal .i{stroke:var(--fail-bg)}
.gate.pass .seal .i{stroke:var(--pass-bg)}
.tally{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));overflow:hidden;
border:1px solid var(--rule);border-radius:.5rem;background:var(--surface)}
.tally div{display:flex;flex-direction:column-reverse;justify-content:flex-end;gap:.4rem;
padding:.85rem 1rem;box-shadow:-1px -1px 0 var(--rule)}
.tally dt{display:flex;align-items:flex-start;gap:.35rem;color:var(--ink-2);
font-size:.8125rem;line-height:1.3}
.tally dt .i{margin-top:.1em;color:var(--edge)}
.tally dd{font:600 1.75rem/1 var(--mono);letter-spacing:-.04em}
.tally .zero dd{color:var(--ink-2)}
.tally div:last-child:nth-child(odd){grid-column:1/-1}
.tally .k-verified:not(.zero) .i,.tally .k-passed:not(.zero) .i{color:var(--pass)}
.tally .k-failed:not(.zero) .i{color:var(--fail)}
.tally .k-partially-covered:not(.zero) .i{color:var(--warn)}
.strip{--cols:12;--gap:.3rem;display:grid;gap:var(--gap);padding:0;list-style:none;
grid-template-columns:repeat(auto-fill,
minmax(max(4.3rem,(100% - (var(--cols) - 1)*var(--gap))/var(--cols)),1fr))}
.cell{display:grid;justify-items:center;align-content:center;gap:.2rem;min-height:2.9rem;
padding:.4rem .25rem;border:1px solid transparent;border-radius:.3rem;
background:var(--idle-bg);color:var(--idle);font:600 .75rem/1.2 var(--mono);
text-align:center;text-decoration:none;overflow-wrap:anywhere}
.cell .i{width:.95rem;height:.95rem;stroke-width:2.8}
.cell.s-verified{background:var(--pass-bg);color:var(--pass)}
.cell.s-failed{background:var(--fail);color:var(--paper)}
.cell.s-partially-covered{background:var(--warn-bg);color:var(--warn)}
.cell:hover{border-color:currentColor}
.cell.s-failed:hover{border-color:var(--ink)}
.foot{padding-block:1.75rem 3rem;border-top:1px solid var(--rule);color:var(--ink-2);
font-size:.875rem}
.foot-in{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;
gap:.75rem 2rem}
.foot p{max-width:46rem}
@media (max-width: 30rem){
.bar-in{column-gap:.75rem}
.brand{font-size:.9375rem}
.nav{margin-inline:-.4rem}
.nav a{padding:0 .4rem;font-size:.875rem}
.ver,.wide,.bar-act>a:not(.btn){display:none}
}
@media (max-width: 22.5rem){
.nav a{padding:0 .35rem;font-size:.8125rem}
}
@media (min-width: 40rem){
.tally{grid-template-columns:repeat(auto-fit,minmax(7rem,1fr))}
.tally div:last-child:nth-child(odd){grid-column:auto}
}
@media (min-width: 56rem){
.bar{position:sticky;top:0;background:color-mix(in srgb,var(--paper) 86%,transparent);
-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px)}
.nav{order:0;flex-basis:auto;margin-left:auto;margin-right:0}
.bar-act{margin-left:0}
html{scroll-padding-top:4.5rem}
}
@media (prefers-reduced-motion: no-preference){
html{scroll-behavior:smooth}
.btn,.cell,.nav a{transition:transform .15s ease,box-shadow .15s ease,
background-color .15s ease,border-color .15s ease,color .15s ease}
.btn .i{transition:transform .15s ease}
.btn:hover .i{transform:translateX(.15rem)}
.btn:hover .i:first-child{transform:translateX(-.15rem)}
}
@media (forced-colors: active){
.badge,.cell,.gate,.tally,.btn{border-color:CanvasText}
.seal{background:CanvasText}
}
@media print{
:root{"""
    + _LIGHT
    + """}
body{background:#fff}
.bar,.skip{display:none}
.paper::before{display:none}
a{color:inherit}
}
"""
)

# Report-only rules. Motion here is interaction-driven only (hover, the filter switch, the
# row a link lands on): a report is opened and captured repeatedly, and a load animation
# leaves `make screenshot` with a half-faded page.
REPORT_CSS = """
.mast{padding-block:clamp(2rem,5vw,3.25rem) 2rem;border-bottom:1px solid var(--rule)}
.mast-in{display:grid;gap:1.25rem}
.mast h1{margin-top:.6rem;font-size:clamp(1.75rem,1.2rem + 2.4vw,2.75rem);line-height:1.1;
overflow-wrap:anywhere}
.scope{max-width:44rem;margin-top:.75rem;color:var(--ink-2)}
.mast .gate{justify-self:start}
.jump{display:grid;gap:.5rem}
.part{padding-top:clamp(2rem,5vw,3rem)}
.part:focus{outline:0}
.part>h2{margin-bottom:1rem;font-size:clamp(1.375rem,1.2rem + .8vw,1.75rem);line-height:1.2}
.part>p{overflow-wrap:anywhere}
.tools{display:flex;flex-wrap:wrap;align-items:center;gap:.25rem 1.5rem;margin-bottom:.75rem}
.legend{color:var(--ink-2);font-size:.875rem}
.switch{display:inline-flex;position:relative;align-items:center;gap:.65rem;
min-height:2.75rem;font-weight:500;cursor:pointer}
.switch input{position:absolute;left:0;top:50%;width:2.5rem;height:1.5rem;margin:-.75rem 0 0;
opacity:0;cursor:pointer}
.track{position:relative;flex:none;width:2.5rem;height:1.5rem;
border:1.5px solid var(--edge);border-radius:999px;background:var(--surface)}
.track::after{content:"";position:absolute;top:50%;left:.2rem;width:.9rem;height:.9rem;
border-radius:50%;background:var(--edge);transform:translateY(-50%)}
.switch input:checked+.track{border-color:var(--ink);background:var(--ink)}
.switch input:checked+.track::after{background:var(--paper);transform:translate(1rem,-50%)}
.switch input:focus-visible+.track{outline:3px solid var(--link);outline-offset:3px}
table{width:100%;border:1px solid var(--rule);border-radius:.5rem;border-collapse:separate;
border-spacing:0;background:var(--surface)}
caption{padding:0 0 .6rem;color:var(--ink-2);font-size:.875rem;text-align:left;
caption-side:top}
th,td{padding:.8rem .9rem;border-bottom:1px solid var(--rule);text-align:left;
vertical-align:top}
thead th{background:var(--sunken);color:var(--ink-2);font:600 .75rem/1.3 var(--mono);
letter-spacing:.06em;text-transform:uppercase}
thead th:first-child{border-top-left-radius:.45rem}
thead th:last-child{border-top-right-radius:.45rem}
tbody tr:last-child>*{border-bottom:0}
tbody tr{scroll-margin-top:6rem}
tbody td:first-child{box-shadow:inset 3px 0 0 var(--spine,transparent)}
tbody tr:last-child td:first-child{border-bottom-left-radius:.45rem}
tr[data-status="verified"]{--spine:var(--pass)}
tr[data-status="failed"]{--spine:var(--fail)}
tr[data-status="partially covered"]{--spine:var(--warn)}
tr[data-status="not covered"]{--spine:var(--edge)}
tr:target>td{background:var(--mark)}
.req-id{display:block;margin-bottom:.2rem;font:650 .875rem/1.3 var(--mono);
overflow-wrap:anywhere}
.req-text{display:block;max-width:44ch;overflow-wrap:anywhere}
.prio{color:var(--ink-2);font:500 .8125rem/1.6 var(--mono)}
.tests{display:grid;gap:.7rem;padding:0;list-style:none}
.test{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start;
gap:.15rem .75rem}
.test-name{overflow-wrap:anywhere}
.test-meta{grid-column:1/-1;color:var(--ink-2);font-size:.8125rem;overflow-wrap:anywhere}
details{grid-column:1/-1;font-size:.875rem}
summary{width:fit-content;min-height:1.75rem;color:var(--fail);font-weight:650;cursor:pointer}
details ul{margin-top:.35rem;padding:.55rem .75rem .55rem 1.75rem;border-radius:.35rem;
background:var(--sunken);font:.8125rem/1.55 var(--mono);overflow-wrap:anywhere}
.none{color:var(--ink-2)}
.all-clear{display:none}
.more{padding:0 1rem;border:1px solid var(--rule);border-radius:.5rem;
background:var(--surface)}
.more summary{display:list-item;width:auto;min-height:0;padding:.8rem 0;color:var(--ink)}
.more .legend{margin-bottom:.75rem}
.more ul{columns:19rem;column-gap:2rem;margin:0;padding:0 0 .6rem;background:none;
font:inherit;list-style:none}
.more li{margin-bottom:.5rem;break-inside:avoid;overflow-wrap:anywhere}
.more+p{margin-top:1rem}
.findings{display:grid;gap:.5rem;padding:0;list-style:none}
.findings li{padding:.7rem .9rem;border:1px solid var(--rule);
border-left:3px solid var(--edge);border-radius:.4rem;background:var(--surface);
overflow-wrap:anywhere}
.findings .v-failed{border-left-color:var(--fail)}
.foot{margin-top:clamp(2.5rem,6vw,4rem)}
body:has(#only-open:checked) tr[data-status="verified"]{display:none}
body:has(#only-open:checked) .strip li[data-status="verified"]{display:none}
body:has(#only-open:checked) .all-clear{display:table-row}
@media (min-width: 56rem){
thead th{position:sticky;top:calc(3.5rem + 1px);z-index:1}
}
@media (max-width: 720px){
table,thead,tbody,tr,th,td{display:block}
table{border:0;background:none}
thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
tbody tr{margin:0 0 .85rem;padding:.4rem 0;border:1px solid var(--rule);
border-left:3px solid var(--spine,var(--rule));border-radius:.5rem;background:var(--surface)}
td{padding:.45rem .9rem;border:0}
tbody td:first-child{box-shadow:none}
tr:target{outline:2px solid var(--link);outline-offset:2px}
caption{display:block}
td[data-label="Priority"],td[data-label="Status"]{display:inline-block;
padding-right:1.5rem;vertical-align:top}
td[data-label]::before{content:attr(data-label);display:block;margin-bottom:.15rem;
color:var(--ink-2);font:600 .6875rem/1.4 var(--mono);letter-spacing:.08em;
text-transform:uppercase}
.req-text{max-width:none}
body:has(#only-open:checked) .all-clear{display:block}
}
@media (prefers-reduced-motion: no-preference){
@keyframes mark{from{box-shadow:inset 3rem 0 0 var(--link)}}
tr:target>td:first-child{animation:mark .9s ease-out}
.track,.track::after{transition:transform .15s ease,background-color .15s ease,
border-color .15s ease}
}
@media (forced-colors: active){
.track::after{background:CanvasText}
.switch input:checked+.track{background:Highlight}
}
@media print{
.jump,.tools{display:none}
thead th{position:static}
tr,.test,.findings li{break-inside:avoid}
}
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f7f5f0">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#14110f">
<title>{{ data.title or 'API' }}: V&amp;V traceability report</title>
<link rel="icon" type="image/svg+xml" href="{{ favicon }}">
<style>{{ css|safe }}</style></head><body>
{%- macro icon(name) -%}
<svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
{{- icons[name]|safe }}</svg>
{%- endmacro -%}
{%- macro badge(status) -%}
<span class="badge s-{{ status|replace(' ', '-') }}">{{ icon(status) }}{{ status }}</span>
{%- endmacro -%}
{%- macro test_item(case, verdict) -%}
{%- set result = data.results.get(case.id) -%}
<li class="test"><span class="test-name"><code>{{ case.id }}</code> {{ case.name }}</span>
{{ badge(verdict) }}
<span class="test-meta">{{ data.endpoints.get(case.operation_id, case.operation_id) }}
&middot; expects {{ case.expected_status }}
{%- if result and result.actual_status %} &middot; got {{ result.actual_status }}{% endif %}
{%- if result and result.latency_ms is not none %}
 &middot; {{ '%.0f'|format(result.latency_ms) }} ms
{%- endif %}</span>
{%- if result and result.errors and result.verdict == 'failed' %}
<details><summary>Why it failed</summary><ul>
{%- for error in result.errors %}<li>{{ error }}</li>{% endfor %}</ul></details>
{%- endif %}</li>
{%- endmacro -%}
<a class="skip" href="#matrix">Skip to the traceability matrix</a>
<header class="bar" id="top"><div class="wrap bar-in">
{% if home_url %}<a class="brand" href="{{ home_url }}">{{ mark|safe }}api-vv-toolkit</a>
{% else %}<span class="brand">{{ mark|safe }}api-vv-toolkit</span>
{% endif %}
<nav class="nav" aria-label="Report sections"><ul>
<li><a href="#matrix">Matrix</a></li>
<li><a href="#gaps">Coverage gaps</a></li>
{% if not matrix_only %}<li><a href="#findings">Findings</a></li>{% endif %}
</ul></nav>
{% if home_url %}<div class="bar-act"><a class="btn sm" href="{{ home_url }}">
{{- icon('back') }}<span>Overview<span class="wide"> of the sample run</span></span></a></div>
{% endif %}
</div></header>
<main>
<div class="mast paper"><div class="wrap mast-in">
<div><p class="label">Traceability report</p>
<h1>{{ data.title or 'API' }}: verification and validation report</h1>
<p class="scope">Results describe this recorded run only. The bundled demo uses deliberately
seeded defects; its output is not a production service certification.</p></div>
{% if gate is not none %}<p class="gate {{ 'fail' if gate else 'pass' }}" role="status">
<span class="seal">{{ icon('failed' if gate else 'verified') }}</span>
{%- if gate %}Gate: FAIL ({{ gate|join(', ') }}){% else %}Gate: PASS{% endif %}</p>{% endif %}
<dl class="tally" aria-label="Summary">
{%- for status in statuses %}
<div class="k-{{ status|replace(' ', '-') }}{{ ' zero' if not counts[status] }}">
<dt>{{ icon(status) }}{{ status }}</dt><dd>{{ counts[status] }}</dd></div>
{%- endfor %}<div><dt>tests run</dt><dd>{{ executed }}</dd></div>
</dl>
{% if data.rows %}<nav class="jump" aria-label="Requirements">
<p class="label">Jump to a requirement</p>
<ol class="strip">
{%- for row in data.rows %}
<li data-status="{{ row.status }}"><a class="cell s-{{ row.status|replace(' ', '-') }}"
 href="#{{ row.requirement.id|urlencode }}">
{{- icon(row.status) }}<span>{{ row.requirement.id }}</span>
<span class="vh">{{ row.status }}</span></a></li>
{%- endfor %}
</ol></nav>{% endif %}
</div></div>
<section class="wrap part" id="matrix" tabindex="-1" aria-labelledby="matrix-h">
<h2 id="matrix-h">Requirements, tests and results</h2>
<div class="tools"><label for="only-open" class="switch"><input type="checkbox" id="only-open">
<span class="track"></span>Show only requirements that are not verified</label>
<span class="legend">Each requirement links to the tests that check it and their latest
verdict.</span></div>
<table><caption>{{ data.rows|length }} requirements traced to {{ traced }} tests</caption>
<thead><tr><th scope="col">Requirement</th><th scope="col">Priority</th>
<th scope="col">Status</th><th scope="col">Tests and latest verdict</th></tr></thead>
<tbody>
{%- for row in data.rows %}
<tr id="{{ row.requirement.id }}" data-status="{{ row.status }}">
<td><span class="req-id">{{ row.requirement.id }}</span>
<span class="req-text">{{ row.requirement.text }}</span></td>
<td data-label="Priority"><span class="prio">{{ row.requirement.priority }}</span></td>
<td data-label="Status">{{ badge(row.status) }}</td>
<td data-label="Tests">{% if row.cases %}<ul class="tests">
{%- for case in row.cases %}{{ test_item(case, row.verdicts[case.id]) }}{% endfor %}
</ul>{% else %}<span class="none">No test traces to this requirement.</span>{% endif %}</td>
</tr>
{%- endfor %}
{% if all_verified %}<tr class="all-clear"><td colspan="4">Every requirement is verified, so
this filter leaves nothing to show.</td></tr>{% endif %}
</tbody></table>
</section>
<section class="wrap part" id="gaps" aria-labelledby="gaps-h">
<h2 id="gaps-h">Coverage gaps</h2>
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
</section>
{% if not matrix_only %}<section class="wrap part" id="findings" aria-labelledby="findings-h">
<h2 id="findings-h">Execution findings</h2><ul class="findings">
{%- for result in data.results.values() if result.errors %}
<li class="v-{{ result.verdict }}"><code>{{ result.case_id }}</code>
({{ result.verdict }}): {{ result.errors|join('; ') }}</li>
{%- else %}<li>No execution findings.</li>{% endfor %}
</ul></section>{% endif %}
</main>
<footer class="foot"><div class="wrap foot-in">
<p>Generated by api-vv-toolkit {{ version }}. Requirement status comes from executed
evidence, never from the mere presence of a generated test.</p>
<a href="#top">Back to top</a></div></footer>
</body></html>
"""

STATUSES = ("verified", "failed", "partially covered", "not covered")


def html_report(
    data: Matrix,
    *,
    matrix_only: bool = False,
    gate: list[str] | None = None,
    home_url: str | None = None,
) -> str:
    """Static, script-free, self-contained page.

    ``gate`` (failing requirement ids) adds the gate verdict. ``home_url`` adds a link back to a
    page that embeds this report, as the Pages build does; without it the page links nowhere.
    """
    counts = {status: sum(row.status == status for row in data.rows) for status in STATUSES}
    return (
        Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
        .from_string(HTML_TEMPLATE)
        .render(
            data=data,
            matrix_only=matrix_only,
            gate=gate,
            home_url=home_url,
            icons=ICONS,
            mark=MARK,
            favicon=FAVICON,
            css=THEME_CSS + REPORT_CSS,
            statuses=STATUSES,
            counts=counts,
            # Disabled review cases are recorded as skipped results; they were not run.
            executed=sum(result.verdict != "skipped" for result in data.results.values()),
            # Counted from the rows, so a hand-built Matrix without ``cases`` still adds up.
            traced=len({case.id for row in data.rows for case in row.cases}),
            all_verified=bool(data.rows) and all(row.status == "verified" for row in data.rows),
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


# Everything outside the XML 1.0 ``Char`` production. ElementTree writes such characters
# verbatim, and one of them (an error path repeating a response key) makes the file unparseable.
XML_ILLEGAL = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


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
    document = ET.tostring(suite, encoding="unicode", xml_declaration=True)
    return XML_ILLEGAL.sub("\ufffd", document) + "\n"


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

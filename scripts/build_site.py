"""Assemble the GitHub Pages site from a finished demo run (CI only; never committed).

usage: python scripts/build_site.py RUN_DIR SITE_DIR

RUN_DIR is the output of ``scripts/demo.py`` (plan, results, reports, CLI transcript). The
landing page states which commit and workflow run produced it, from the standard GitHub
Actions environment variables; outside CI it says the build was local.

The published ``report.html`` is the run's own report plus one link back to the landing page.
The build stops if this toolkit no longer renders the run's ``report.html`` byte for byte, so
the page cannot drift from the evidence beside it.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment

from api_vv import __version__
from api_vv.cli import load_config
from api_vv.diff import Change, diff_specs
from api_vv.io import read_data
from api_vv.models import Plan, Run
from api_vv.report import FAVICON, ICONS, MARK, THEME_CSS, gate_failures, html_report, matrix
from api_vv.spec import parse_spec

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = (
    ("report.html", "Traceability matrix (HTML)"),
    ("junit.xml", "JUnit XML"),
    ("traceability.csv", "Traceability CSV"),
    ("plan.yaml", "Generated test plan"),
    ("results.yaml", "Execution results"),
    ("cli-output.txt", "CLI transcript"),
)
# Committed assets, published under these names.
ASSETS = (("og-image.png", "og-image.png"), ("favicon.png", "apple-touch-icon.png"))
DESCRIPTION = (
    "OpenAPI and written requirements in, API tests and a requirement-to-verdict "
    "traceability matrix out, gated in CI."
)
OG_ALT = "api-vv-toolkit: Requirements in. Verdicts out. Every test traced."

# Landing-only rules; tokens and shared components come from ``api_vv.report.THEME_CSS``.
SITE_CSS = """
main{counter-reset:sec}
.hero{padding-block:clamp(2.5rem,7vw,5rem) clamp(3rem,7vw,5rem)}
.hero-in{display:grid;align-items:center;gap:clamp(2.25rem,5vw,3rem)}
.hero-in>*{min-width:0}
.hero h1{margin-block:1rem 1.25rem;font-size:clamp(2.5rem,1.2rem + 5.4vw,4.25rem);
line-height:1.02;letter-spacing:-.03em}
.hero h1 span{display:block}
.hero h1 em{background:linear-gradient(currentColor,currentColor) 0 96%/100% .045em no-repeat}
.lede{max-width:34rem;color:var(--ink-2);font-size:clamp(1.0625rem,1rem + .3vw,1.1875rem)}
.cta{display:flex;flex-wrap:wrap;gap:.75rem;max-width:38rem;margin-top:1.75rem}
.cta .btn{flex:1 1 auto}
.sheet{display:grid;gap:1.1rem;padding:1.25rem;border:1.5px solid var(--frame);
border-radius:.6rem;background:var(--surface);box-shadow:.4rem .4rem 0 var(--rule)}
.sheet-head{display:grid;gap:.45rem;padding-bottom:1rem;border-bottom:1px dashed var(--edge)}
.sheet h2{font-size:1.375rem;line-height:1.2}
.provenance{color:var(--ink-2);font-size:.8125rem;line-height:1.5;overflow-wrap:anywhere}
.prov-links{display:flex;flex-wrap:wrap;gap:.25rem 1.25rem;font-size:.8125rem}
.sheet .strip{--cols:6;--gap:.25rem;margin-top:.5rem}
.sheet .tally{grid-template-columns:repeat(2,minmax(0,1fr))}
.sec{border-top:1px solid var(--rule)}
.sec-in{display:grid;gap:1.5rem 3rem;padding-block:clamp(2.5rem,6vw,4rem)}
.sec-in>*{min-width:0}
.sec-head h2{font-size:clamp(1.5rem,1.25rem + 1vw,2rem);line-height:1.15}
.sec-head h2::before{display:block;margin-bottom:.6rem;color:var(--ink-2);
font:600 .75rem/1.3 var(--mono);letter-spacing:.08em;counter-increment:sec;
content:counter(sec,decimal-leading-zero);content:counter(sec,decimal-leading-zero) / ""}
.sec-head p{margin-top:.75rem;color:var(--ink-2)}
.sec-body{display:grid;gap:1rem}
.sec-body>*{min-width:0}
.defects{display:grid;gap:1rem;padding:0;list-style:none}
.defect{display:grid;align-content:start;gap:.65rem;padding:1.1rem 1.25rem;
border:1px solid var(--rule);border-left:4px solid var(--edge);border-radius:.5rem;
background:var(--surface)}
.defect[data-status="failed"]{border-left-color:var(--fail)}
.defect-top{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;
gap:.5rem}
.req{display:inline-flex;align-items:center;gap:.35rem;min-height:1.75rem;
font:650 1rem/1.3 var(--mono)}
.defect-text{font-family:var(--serif);font-size:1.25rem;line-height:1.3;
overflow-wrap:anywhere}
.why{display:grid;gap:.3rem;padding:.6rem .75rem;border-radius:.35rem;background:var(--sunken)}
.why code{font-size:.8125rem;line-height:1.5}
.term{overflow:hidden;border:1px solid var(--code-rule);border-radius:.6rem;
background:var(--code-bg);color:var(--code-fg)}
.term figcaption{display:flex;align-items:center;justify-content:space-between;gap:1rem;
min-height:2.5rem;padding:.3rem 1rem;border-bottom:1px solid var(--code-rule);
color:var(--code-dim);font:500 .75rem/1.3 var(--mono);letter-spacing:.04em}
.term a{color:var(--code-fg)}
.term :focus-visible{outline-color:var(--code-fg)}
.term pre{margin:0;padding:.9rem 1rem;overflow-x:auto;font-size:.8125rem;line-height:1.7}
.term pre:focus-visible{outline-offset:-3px}
.term code{font-size:1em;overflow-wrap:normal}
.term .k{color:var(--code-dim)}
.log{counter-reset:ln;white-space:pre-wrap}
.log code{overflow-wrap:anywhere}
.ln{display:block;position:relative;min-height:1.7em;padding-left:2.4rem}
.ln::before{position:absolute;left:0;width:1.4rem;color:var(--code-dim);font-weight:400;
text-align:right;
counter-increment:ln;content:counter(ln);content:counter(ln) / ""}
.ln.fail{color:var(--code-fail);font-weight:700}
.ln.pass{color:var(--code-pass);font-weight:700}
.scroll{overflow-x:auto;border:1px solid var(--rule);border-radius:.5rem;
background:var(--surface)}
.scroll:focus-visible{outline-offset:2px}
.drift{width:100%;border-collapse:collapse;font-size:.875rem}
.drift th,.drift td{padding:.6rem .85rem;border-bottom:1px solid var(--rule);text-align:left;
vertical-align:top}
.drift thead th{background:var(--sunken);color:var(--ink-2);font:600 .75rem/1.3 var(--mono);
letter-spacing:.06em;text-transform:uppercase}
.drift tbody tr:last-child>*{border-bottom:0}
.drift th:first-child{width:1%}
.drift td{overflow-wrap:anywhere}
.files{display:grid;gap:.75rem;padding:0;list-style:none}
.file{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;
gap:.1rem .9rem;height:100%;padding:.85rem 1rem;border:1px solid var(--rule);
border-radius:.5rem;background:var(--surface);color:var(--ink);text-decoration:none}
.ext{display:grid;grid-row:span 2;place-items:center;width:2.9rem;height:2.9rem;
border:1.5px solid var(--frame);border-radius:.35rem;font:700 .6875rem/1 var(--mono);
letter-spacing:.04em;text-transform:uppercase}
.file-label{font-weight:650;line-height:1.3}
.file code{grid-column:2;color:var(--ink-2)}
.file .i{grid-area:1/3/span 2;width:1.1rem;height:1.1rem;color:var(--ink-2)}
.file:hover{border-color:var(--frame);box-shadow:3px 3px 0 var(--rule);
transform:translate(-2px,-2px)}
@media (min-width: 40rem){
.defects{grid-template-columns:repeat(auto-fit,minmax(17rem,1fr))}
.files{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (min-width: 64rem){
.hero-in{grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr)}
.hero h1{font-size:clamp(3rem,5.8vw,4.25rem)}
.sec-in{grid-template-columns:minmax(0,16rem) minmax(0,1fr)}
.sec-head{position:sticky;top:5.5rem;align-self:start}
}
@media (min-width: 72rem){
.drift td:nth-child(2),.drift td:nth-child(3){white-space:nowrap}
}
@media (max-width: 720px){
.drift,.drift tbody,.drift tr,.drift td{display:block}
.drift thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
.drift tr{padding:.75rem .9rem;border-bottom:1px solid var(--rule)}
.drift tbody tr:last-child{border-bottom:0}
.drift td{padding:.12rem 0;border:0}
.drift td:nth-child(-n+2){display:inline-block;padding:0 .6rem .35rem 0;vertical-align:middle}
}
@media (prefers-reduced-motion: no-preference){
@keyframes draw{from{background-size:0 .045em}}
@keyframes rise{from{opacity:0;transform:translateY(.6rem)}}
@keyframes tick{from{opacity:0;transform:scale(.7)}}
@keyframes stamp{from{opacity:0;transform:scale(1.05)}}
.hero-copy>*{animation:rise .6s cubic-bezier(.2,.7,.2,1) backwards}
.hero-copy>:nth-child(2){animation-delay:.07s}
.hero-copy>:nth-child(3){animation-delay:.14s}
.hero-copy>:nth-child(4){animation-delay:.21s}
.hero h1 em{animation:draw .7s .65s ease-out backwards}
.sheet{animation:rise .7s .12s cubic-bezier(.2,.7,.2,1) backwards}
.gate{animation:stamp .4s .35s cubic-bezier(.2,.7,.2,1) backwards}
.cell{animation:tick .3s cubic-bezier(.2,.7,.2,1) backwards;
animation-delay:calc(.45s + min(var(--i,0),30)*.035s)}
.file{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.file .i,.req .i{transition:transform .15s ease}
.file:hover .i,.req:hover .i{transform:translateX(.2rem)}
}
@media print{
.term{border-color:#000;background:#fff;color:#000}
.sec-head{position:static}
}
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f7f5f0">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#14110f">
<meta name="description" content="{{ description }} Live sample run.">
<title>api-vv-toolkit: live sample run</title>
<link rel="canonical" href="{{ site_url }}">
<link rel="icon" type="image/png" sizes="180x180" href="apple-touch-icon.png">
<link rel="icon" type="image/svg+xml" href="{{ favicon }}">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:title" content="api-vv-toolkit: live sample run">
<meta property="og:description" content="{{ description }}">
<meta property="og:url" content="{{ site_url }}">
<meta property="og:image" content="{{ site_url }}og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{{ og_alt }}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="api-vv-toolkit: live sample run">
<meta name="twitter:description" content="{{ description }}">
<meta name="twitter:image" content="{{ site_url }}og-image.png">
<style>{{ css|safe }}</style></head><body>
{%- macro icon(name) -%}
<svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
{{- icons[name]|safe }}</svg>
{%- endmacro -%}
{%- macro badge(status) -%}
<span class="badge s-{{ status|replace(' ', '-') }}">{{ icon(status) }}{{ status }}</span>
{%- endmacro -%}
<a class="skip" href="#run">Skip to the live sample run</a>
<header class="bar" id="top"><div class="wrap bar-in">
<a class="brand" href="index.html" aria-current="page">{{ mark|safe }}api-vv-toolkit
<span class="ver">v{{ version }}</span></a>
<nav class="nav" aria-label="Sections"><ul>
<li><a href="#run">Run</a></li>
<li><a href="#transcript">Transcript</a></li>
<li><a href="#usage">Use it</a></li>
<li><a href="#drift">Drift</a></li>
<li><a href="#evidence">Evidence</a></li>
</ul></nav>
<div class="bar-act"><a class="btn sm primary" href="report.html">Matrix{{ icon('arrow') }}</a>
<a href="{{ repo_url }}">GitHub{{ icon('external') }}</a></div>
</div></header>
<main>
<div class="hero paper"><div class="wrap hero-in">
<div class="hero-copy">
<p class="label">Open source &middot; MIT &middot; v{{ version }}</p>
<h1><span>Requirements in.</span> <span>Verdicts out.</span>
<span>Every test <em>traced.</em></span></h1>
<p class="lede">api-vv-toolkit reads an OpenAPI 3.0 or 3.1 contract and your written
requirements, generates API tests (boundary, negative, auth and seeded property cases), runs
them against a live service and gates CI on which requirements are actually verified.</p>
<p class="cta"><a class="btn primary" href="report.html">Open the traceability matrix
{{- icon('arrow') }}</a>
<a class="btn" href="{{ repo_url }}">Source and quickstart{{ icon('external') }}</a></p>
</div>
<section class="sheet" id="run" tabindex="-1" aria-labelledby="run-h">
<div class="sheet-head"><h2 id="run-h">Live sample run</h2>
<p class="provenance">{{ provenance }}</p>
{% if sources %}<p class="prov-links">{% for label, href in sources %}
<a href="{{ href }}">{{ label }}</a>{% endfor %}</p>{% endif %}
</div>
<p class="gate {{ 'fail' if failed else 'pass' }}">
<span class="seal">{{ icon('failed' if failed else 'verified') }}</span>
{%- if failed %}Gate: FAIL ({{ failed|join(', ') }}){% else %}Gate: PASS{% endif %}</p>
{% if rows %}<div><h3 class="label" id="strip-h">{{ rows|length }} requirements, each linked
to its matrix row</h3>
<ul class="strip" aria-labelledby="strip-h">
{%- for row in rows %}
<li><a class="cell s-{{ row.status|replace(' ', '-') }}"
 href="report.html#{{ row.requirement.id|urlencode }}" style="--i:{{ loop.index0 }}">
{{- icon(row.status) }}<span>{{ row.requirement.id }}</span>
<span class="vh">{{ row.status }}</span></a></li>
{%- endfor %}
</ul></div>{% endif %}
<dl class="tally">
{%- for label, value, kind in tally %}
<div class="k-{{ kind }}{{ ' zero' if not value }}"><dt>{{ icon(kind) }}{{ label }}</dt>
<dd>{{ value }}</dd></div>
{%- endfor %}
</dl>
</section>
</div></div>
{% if caught %}<section class="sec" id="caught" aria-labelledby="caught-h">
<div class="wrap sec-in">
<div class="sec-head"><h2 id="caught-h">What the gate caught</h2>
<p>The bundled demo API carries two deliberately seeded defects. The gate named both:</p></div>
<ul class="defects">
{%- for item in caught %}
<li class="defect" data-status="{{ item.status }}">
<p class="defect-top"><a class="req" href="report.html#{{ item.id|urlencode }}">{{ item.id }}
{{- icon('arrow') }}</a>{{ badge(item.status) }}</p>
<p class="defect-text">{{ item.text }}</p>
<p class="why"><span class="label">Why</span><code>{{ item.why }}</code></p></li>
{%- endfor %}
</ul></div></section>{% endif %}
<section class="sec" id="transcript" aria-labelledby="cli-h"><div class="wrap sec-in">
<div class="sec-head"><h2 id="cli-h">What CI ran</h2></div>
<div class="sec-body"><figure class="term">
<figcaption><span>cli-output.txt</span><a href="cli-output.txt">Raw file</a></figcaption>
<pre class="log"><code>{% for text, kind in transcript %}<span class="ln{{ ' ' ~ kind if kind }}">
{{- text }}</span>{% endfor %}</code></pre></figure></div>
</div></section>
<section class="sec" id="usage" aria-labelledby="use-h"><div class="wrap sec-in">
<div class="sec-head"><h2 id="use-h">Gate your own API</h2></div>
<div class="sec-body"><figure class="term">
<figcaption><span>GitHub Actions step</span></figcaption>
<pre tabindex="0" role="region" aria-label="GitHub Actions step">
<code>- <span class="k">uses:</span> muhib-karim/api-vv-toolkit@v1
  <span class="k">with:</span>
    <span class="k">spec:</span> openapi.yaml
    <span class="k">requirements:</span> requirements.yaml
    <span class="k">base-url:</span> http://localhost:8000</code></pre></figure>
<p>Or locally: install the wheel from a
<a href="{{ repo_url }}/releases">GitHub release</a>, then run <code>api-vv generate</code>,
<code>run</code> and <code>report</code>.</p></div>
</div></section>
<section class="sec" id="drift" aria-labelledby="drift-h"><div class="wrap sec-in">
<div class="sec-head"><h2 id="drift-h">Contract drift, classified</h2>
<p><code>api-vv diff old.yaml new.yaml</code> exits 1 when a change breaks existing clients.
Sample: the bundled breaking fixture ({{ breaking }} breaking,
{{ drift|length - breaking }} non-breaking).</p></div>
<div class="scroll" role="region" aria-label="Classified contract changes" tabindex="0">
<table class="drift"><thead><tr><th scope="col">Severity</th><th scope="col">Rule</th>
<th scope="col">Operation</th><th scope="col">Detail</th></tr></thead><tbody>
{%- for change in drift %}
<tr><td>{{ badge('breaking' if change.breaking else 'non-breaking') }}</td>
<td><code>{{ change.rule }}</code></td>
<td><code>{{ change.operation }}</code></td>
<td>{{ change.where ~ ': ' if change.where }}{{ change.detail }}</td></tr>
{%- endfor %}
</tbody></table></div>
</div></section>
<section class="sec" id="evidence" aria-labelledby="files-h"><div class="wrap sec-in">
<div class="sec-head"><h2 id="files-h">Evidence from this run</h2></div>
<ul class="files">
{%- for name, label in downloads %}
<li><a class="file" href="{{ name }}">
<span class="ext" aria-hidden="true">{{ name.rsplit('.', 1)[-1] }}</span>
<span class="file-label">{{ label }}</span><code>{{ name }}</code>{{ icon('arrow') }}</a></li>
{%- endfor %}
</ul></div></section>
</main>
<footer class="foot"><div class="wrap foot-in">
<p>api-vv-toolkit {{ version }} &middot; MIT &middot; <a href="{{ repo_url }}">GitHub</a>.
The demo service and its defects are bundled test fixtures, not an audit of a real API.</p>
<a href="#top">Back to top</a></div></footer>
</body></html>
"""


def provenance() -> str:
    sha = os.environ.get("GITHUB_SHA", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if sha and run_id:
        return (
            f"Built by GitHub Actions run {run_id} from commit {sha[:7]} on {when}, against the "
            "bundled demo API on a loopback port."
        )
    return f"Built locally on {when}, against the bundled demo API on a loopback port."


def sources(repo_url: str) -> list[tuple[str, str]]:
    """Links that let a reader check the provenance sentence; none outside CI."""
    sha = os.environ.get("GITHUB_SHA", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not (sha and run_id):
        return []
    return [
        (f"Workflow run {run_id}", f"{repo_url}/actions/runs/{run_id}"),
        (f"Commit {sha[:7]}", f"{repo_url}/commit/{sha}"),
    ]


def transcript_lines(text: str) -> list[tuple[str, str]]:
    """Each transcript line with the verdict class its gate line carries, if any."""
    kinds = {"Gate: FAIL": "fail", "Gate: PASS": "pass"}
    return [(line, kinds.get(line[:10], "")) for line in text.strip().splitlines()]


def build(run_dir: Path, site: Path) -> None:
    plan = Plan.model_validate(read_data(run_dir / "plan.yaml"))
    run = Run.model_validate(read_data(run_dir / "results.yaml"))
    config = load_config(str(ROOT / "examples" / "demo_api" / "config.yaml"))
    data = matrix(plan, run)
    failed = gate_failures(data, config)
    recorded = (run_dir / "report.html").read_text(encoding="utf-8")
    if html_report(data, gate=failed) != recorded:
        raise ValueError(
            f"{run_dir / 'report.html'} is not what this toolkit renders for this run; "
            "run scripts/demo.py again before building the site"
        )
    rows = {row.requirement.id: row for row in data.rows}
    caught = [
        {
            "id": req_id,
            "text": rows[req_id].requirement.text,
            "status": rows[req_id].status,
            "why": "; ".join(
                error
                for case in rows[req_id].cases
                if case.id in data.results
                for error in data.results[case.id].errors
            )
            or rows[req_id].status,
        }
        for req_id in failed
    ]
    verdicts = [result.verdict for result in run.results]
    tally = [
        ("requirements verified", sum(row.status == "verified" for row in data.rows), "verified"),
        ("requirements failed", sum(row.status == "failed" for row in data.rows), "failed"),
        ("tests passed", verdicts.count("passed"), "passed"),
        ("tests failed", verdicts.count("failed"), "failed"),
    ]
    fixtures = ROOT / "tests" / "fixtures" / "diff"
    drift: list[Change] = diff_specs(
        parse_spec(fixtures / "v1.yaml"), parse_spec(fixtures / "v2-breaking.yaml")
    )
    repo = os.environ.get("GITHUB_REPOSITORY", "muhib-karim/api-vv-toolkit")
    repo_owner, repo_name = repo.split("/", 1)
    repo_url = f"https://github.com/{repo}"
    site.mkdir(parents=True, exist_ok=True)
    for name, _ in DOWNLOADS:
        shutil.copy2(run_dir / name, site / name)
    for source, target in ASSETS:
        shutil.copy2(ROOT / "docs" / "assets" / source, site / target)
    # The run's report, plus the way back to the landing page.
    (site / "report.html").write_text(
        html_report(data, gate=failed, home_url="index.html"), encoding="utf-8"
    )
    page = (
        Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
        .from_string(PAGE)
        .render(
            css=THEME_CSS + SITE_CSS,
            icons=ICONS,
            mark=MARK,
            favicon=FAVICON,
            description=DESCRIPTION,
            og_alt=OG_ALT,
            provenance=provenance(),
            sources=sources(repo_url),
            failed=failed,
            caught=caught,
            rows=data.rows,
            tally=tally,
            transcript=transcript_lines((run_dir / "cli-output.txt").read_text(encoding="utf-8")),
            drift=drift,
            breaking=sum(change.breaking for change in drift),
            downloads=DOWNLOADS,
            repo_url=repo_url,
            site_url=f"https://{repo_owner.lower()}.github.io/{repo_name}/",
            version=__version__,
        )
    )
    (site / "index.html").write_text(page, encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    build(Path(argv[0]), Path(argv[1]))
    print(f"Wrote {argv[1]}/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

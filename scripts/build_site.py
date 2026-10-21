"""Assemble the GitHub Pages site from a finished demo run (CI only; never committed).

usage: python scripts/build_site.py RUN_DIR SITE_DIR

RUN_DIR is the output of ``scripts/demo.py`` (plan, results, reports, CLI transcript). The
landing page states which commit and workflow run produced it, from the standard GitHub
Actions environment variables; outside CI it says the build was local.
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
from api_vv.report import gate_failures, matrix
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

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="OpenAPI and written requirements in, API tests and a
requirement-to-verdict traceability matrix out, gated in CI. Live sample run.">
<title>api-vv-toolkit: live sample run</title><style>
:root{--bg:#f6f7f9;--surface:#fff;--fg:#121a24;--muted:#4a5565;--line:#d5dae1;
--accent:#1d4ed8;--pass:#166534;--pass-bg:#e3f4e8;--fail:#a61b1b;--fail-bg:#fbe7e7;
--code-bg:#101820;--code-fg:#dbe4ee;
--mono:ui-monospace,"SFMono-Regular","JetBrains Mono",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
@media (prefers-color-scheme: dark){:root{--bg:#0e141b;--surface:#151d27;--fg:#e8edf3;
--muted:#a3afbf;--line:#2b3746;--accent:#8ab4ff;--pass:#7ee2a0;--pass-bg:#12301f;
--fail:#ff9d9d;--fail-bg:#3a1618;--code-bg:#0a0f15}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 var(--sans);
font-variant-numeric:tabular-nums}
::selection{background:var(--accent);color:var(--surface)}
a{color:var(--accent);text-underline-offset:.18em}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px;border-radius:2px}
.skip{position:absolute;left:1rem;top:-3rem;background:var(--surface);padding:.6rem 1rem}
.skip:focus{top:1rem}
.wrap{max-width:68rem;margin:0 auto;padding:2.5rem 1rem 3rem}
h1{font-size:clamp(2rem,1.4rem + 3vw,3.4rem);line-height:1.08;letter-spacing:-.03em;
margin:0 0 1rem;max-width:18ch;text-wrap:balance}
.lede{font-size:1.15rem;color:var(--muted);max-width:60ch;margin:0 0 1.75rem}
.cta{display:flex;flex-wrap:wrap;gap:.75rem;margin:0 0 3rem}
.btn{display:inline-flex;align-items:center;min-height:44px;padding:.6rem 1.1rem;
border-radius:.45rem;font-weight:650;text-decoration:none;border:1px solid var(--line)}
.btn.primary{background:var(--accent);color:var(--surface);border-color:var(--accent)}
.btn:hover{filter:brightness(1.08)}
h2{font-size:1.4rem;letter-spacing:-.01em;margin:3rem 0 .75rem}
.run{background:var(--surface);border:1px solid var(--line);border-radius:.6rem;padding:1.25rem}
.provenance{color:var(--muted);font-size:.92rem;margin:0 0 1rem}
.gate{display:inline-block;font-weight:700;padding:.4rem .75rem;border-radius:.4rem;
margin:0 0 1rem}
.gate.fail{background:var(--fail-bg);color:var(--fail)}
.gate.pass{background:var(--pass-bg);color:var(--pass)}
.tally{display:flex;flex-wrap:wrap;gap:.4rem 1.75rem;margin:0 0 1rem;padding:0}
.tally div{display:flex;align-items:baseline;gap:.4rem}
.tally dt{color:var(--muted);order:2}.tally dd{margin:0;font-weight:700;font-size:1.2rem}
.caught{margin:0;padding-left:1.2rem}.caught li{margin:.35rem 0}
pre{background:var(--code-bg);color:var(--code-fg);padding:1rem 1.1rem;border-radius:.5rem;
overflow-x:auto;font:.85rem/1.55 var(--mono);margin:0}
code{font-family:var(--mono);font-size:.9em}
.grid{display:grid;gap:1.25rem}
.grid>*{min-width:0}
@media (min-width: 860px){.grid{grid-template-columns:1fr 1fr}}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:650}
.sev{font-weight:650}.sev.b{color:var(--fail)}
.scroll{overflow-x:auto}
ul.files{list-style:none;padding:0;margin:0;display:grid;gap:.35rem}
footer{margin-top:3.5rem;color:var(--muted);font-size:.9rem}
@media (max-width: 600px){td,th{padding:.45rem .35rem}}
</style></head><body>
<a class="skip" href="#run">Skip to the live sample run</a>
<div class="wrap"><header>
<h1>Requirements in. Verdicts out. Every test traced.</h1>
<p class="lede">api-vv-toolkit reads an OpenAPI 3.0 or 3.1 contract and your written
requirements, generates API tests (boundary, negative, auth and seeded property cases), runs
them against a live service and gates CI on which requirements are actually verified.</p>
<p class="cta"><a class="btn primary" href="report.html">Open the traceability matrix</a>
<a class="btn" href="{{ repo_url }}">Source and quickstart</a></p>
</header><main>
<section id="run" tabindex="-1" aria-labelledby="run-h">
<h2 id="run-h">Live sample run</h2>
<div class="run">
<p class="provenance">{{ provenance }}</p>
<p class="gate {{ 'fail' if failed else 'pass' }}">
{%- if failed %}Gate: FAIL ({{ failed|join(', ') }}){% else %}Gate: PASS{% endif %}</p>
<dl class="tally">
{%- for label, value in tally %}<div><dt>{{ label }}</dt><dd>{{ value }}</dd></div>{% endfor %}
</dl>
{% if caught %}<p>The bundled demo API carries two deliberately seeded defects. The gate
named both:</p><ul class="caught">
{%- for item in caught %}<li><a href="report.html#{{ item.id }}">{{ item.id }}</a>:
{{ item.text }} <span class="provenance">({{ item.why }})</span></li>{% endfor %}</ul>
{% endif %}</div></section>
<div class="grid">
<section aria-labelledby="cli-h"><h2 id="cli-h">What CI ran</h2>
<pre><code>{{ transcript }}</code></pre></section>
<section aria-labelledby="use-h"><h2 id="use-h">Gate your own API</h2>
<pre><code>- uses: muhib-karim/api-vv-toolkit@v1
  with:
    spec: openapi.yaml
    requirements: requirements.yaml
    base-url: http://localhost:8000</code></pre>
<p>Or locally: install the wheel from a
<a href="{{ repo_url }}/releases">GitHub release</a>, then run <code>api-vv generate</code>,
<code>run</code> and <code>report</code>.</p></section>
</div>
<section aria-labelledby="drift-h"><h2 id="drift-h">Contract drift, classified</h2>
<p><code>api-vv diff old.yaml new.yaml</code> exits 1 when a change breaks existing clients.
Sample: the bundled breaking fixture ({{ breaking }} breaking,
{{ drift|length - breaking }} non-breaking).</p>
<div class="scroll"><table><thead><tr><th scope="col">Severity</th><th scope="col">Rule</th>
<th scope="col">Operation</th><th scope="col">Detail</th></tr></thead><tbody>
{%- for change in drift %}<tr><td class="sev {{ 'b' if change.breaking }}">
{{- 'breaking' if change.breaking else 'non-breaking' }}</td><td><code>{{ change.rule }}</code></td>
<td><code>{{ change.operation }}</code></td>
<td>{{ change.where ~ ': ' if change.where }}{{ change.detail }}</td></tr>{% endfor %}
</tbody></table></div></section>
<section aria-labelledby="files-h"><h2 id="files-h">Evidence from this run</h2>
<ul class="files">{% for name, label in downloads %}<li><a href="{{ name }}">{{ label }}</a>
<code>{{ name }}</code></li>{% endfor %}</ul></section>
</main>
<footer>api-vv-toolkit {{ version }} · MIT · <a href="{{ repo_url }}">GitHub</a>.
The demo service and its defects are bundled test fixtures, not an audit of a real API.
</footer></div></body></html>
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


def build(run_dir: Path, site: Path) -> None:
    plan = Plan.model_validate(read_data(run_dir / "plan.yaml"))
    run = Run.model_validate(read_data(run_dir / "results.yaml"))
    config = load_config(str(ROOT / "examples" / "demo_api" / "config.yaml"))
    data = matrix(plan, run)
    failed = gate_failures(data, config)
    rows = {row.requirement.id: row for row in data.rows}
    caught = [
        {
            "id": req_id,
            "text": rows[req_id].requirement.text,
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
        ("requirements verified", sum(row.status == "verified" for row in data.rows)),
        ("requirements failed", sum(row.status == "failed" for row in data.rows)),
        ("tests passed", verdicts.count("passed")),
        ("tests failed", verdicts.count("failed")),
    ]
    fixtures = ROOT / "tests" / "fixtures" / "diff"
    drift: list[Change] = diff_specs(
        parse_spec(fixtures / "v1.yaml"), parse_spec(fixtures / "v2-breaking.yaml")
    )
    repo = os.environ.get("GITHUB_REPOSITORY", "muhib-karim/api-vv-toolkit")
    site.mkdir(parents=True, exist_ok=True)
    for name, _ in DOWNLOADS:
        shutil.copy2(run_dir / name, site / name)
    page = (
        Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
        .from_string(PAGE)
        .render(
            provenance=provenance(),
            failed=failed,
            caught=caught,
            tally=tally,
            transcript=(run_dir / "cli-output.txt").read_text(encoding="utf-8").strip(),
            drift=drift,
            breaking=sum(change.breaking for change in drift),
            downloads=DOWNLOADS,
            repo_url=f"https://github.com/{repo}",
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

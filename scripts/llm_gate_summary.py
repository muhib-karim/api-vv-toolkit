"""Summarise LLM gate experiment runs: one directory per run with plan.yaml and results.yaml."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.demo_api.app import CREATE_SCHEMA, SPEC  # noqa: E402

DOCUMENTED = Draft202012Validator(SPEC.operations["createWidget"].request_schema)
IMPLEMENTED = Draft202012Validator(CREATE_SCHEMA)


def classify(case: dict[str, object], actual: int | None) -> str:
    """Attribute an executed LLM-case failure to a seeded defect or to a wrong expectation."""
    if case["operation_id"] == "deleteWidget" and actual == 200:
        return "defect-2"
    body = case.get("body")
    if (
        case["operation_id"] == "createWidget"
        and actual == 201
        and not DOCUMENTED.is_valid(body)
        and IMPLEMENTED.is_valid(body)
    ):
        return "defect-1"
    return "wrong-expectation"


def bucket(reason: str) -> str:
    if reason == "validated":
        return "accepted"
    if reason.startswith("invalid proposal"):
        return "schema: " + re.sub(r"^invalid proposal: ", "", reason).split(";")[0].split(": ")[-1]
    for key in (
        "outside the requested requirement coverage",
        "do not include llm-scenario",
        "undocumented",
        "conflicting expectations",
        "malformed",
        "unknown operation",
    ):
        if key in reason:
            return key
    return reason[:60]


def summarise(run: Path) -> dict[str, object]:
    plan = yaml.safe_load((run / "plan.yaml").read_text(encoding="utf-8"))
    reviews = [r for audit in plan.get("llm_audit", []) for r in audit["reviews"]]
    reasons = Counter(bucket(r["reason"]) for r in reviews)
    llm_ids = {c["id"] for c in plan["cases"] if c.get("generators") == ["llm"]}
    cases = {c["id"]: c for c in plan["cases"]}
    verdicts: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    results_path = run / "results.yaml"
    if results_path.exists():
        results = yaml.safe_load(results_path.read_text(encoding="utf-8"))["results"]
        mine = [r for r in results if r["case_id"] in llm_ids]
        verdicts = Counter(r["verdict"] for r in mine)
        failures = Counter(
            classify(cases[r["case_id"]], r.get("actual_status"))
            for r in mine
            if r["verdict"] == "failed"
        )
    return {
        "run": run.name,
        "requirements_queried": len(plan.get("llm_audit", [])),
        "proposals": len(reviews),
        "accepted": reasons.pop("accepted", 0),
        "llm_cases_in_plan": len(llm_ids),
        "executed_passed": verdicts.get("passed", 0),
        "executed_failed": verdicts.get("failed", 0),
        "failures_on_seeded_defects": failures.get("defect-1", 0) + failures.get("defect-2", 0),
        "seeded_defects_found": sorted(k for k in failures if k.startswith("defect")),
        "failures_wrong_expectation": failures.get("wrong-expectation", 0),
        "rejections": dict(reasons.most_common()),
    }


def report(root: Path) -> None:
    """Aggregate <root>/<model>/<variant>/<run>/ into summary.json and report.md."""
    rows = []
    for run in sorted(root.glob("*/*/r*")):
        row = summarise(run)
        row["model"], row["variant"] = run.parent.parent.name, run.parent.name
        log = (run / "gen.log").read_text(encoding="utf-8")
        found = re.search(r"GEN_EXIT 0 (\d+)s", log)
        row["generate_seconds"] = int(found.group(1)) if found else None
        rows.append(row)
    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault((str(row["model"]), str(row["variant"])), []).append(row)
    lines = [
        "| Model | Prompt | Runs | Model calls / run | Proposals | Accepted | Acceptance |"
        " LLM cases executed | Failed on seeded defects | Wrong expectations |"
        " Seeded defects hit |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    table = []
    for (model, variant), runs in sorted(groups.items(), key=lambda kv: kv[0]):

        def total(key: str, group: list[dict[str, object]] = runs) -> int:
            return sum(int(r[key]) for r in group)  # type: ignore[call-overload]

        proposals, accepted = total("proposals"), total("accepted")
        executed = total("executed_passed") + total("executed_failed")
        hits = sorted({d for r in runs for d in r["seeded_defects_found"]})  # type: ignore[attr-defined]
        entry = {
            "model": model,
            "variant": variant,
            "runs": len(runs),
            "calls_per_run": total("requirements_queried") / len(runs),
            "proposals": proposals,
            "accepted": accepted,
            "acceptance_rate": round(accepted / proposals, 3) if proposals else None,
            "llm_cases_executed": executed,
            "failed_on_seeded_defects": total("failures_on_seeded_defects"),
            "failed_wrong_expectation": total("failures_wrong_expectation"),
            "seeded_defects_hit": hits,
        }
        table.append(entry)
        rate = f"{100 * accepted / proposals:.0f}%" if proposals else "n/a"
        lines.append(
            f"| {model} | {variant} | {len(runs)} | {entry['calls_per_run']:g} | {proposals} |"
            f" {accepted} | {rate} | {executed} | {entry['failed_on_seeded_defects']} |"
            f" {entry['failed_wrong_expectation']} | {', '.join(hits) or 'none'} |"
        )
    (root / "summary.json").write_text(
        json.dumps({"groups": table, "runs": rows}, indent=1) + "\n", encoding="utf-8"
    )
    (root / "table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--report"]:
        report(Path(sys.argv[2]))
    else:
        print(json.dumps([summarise(Path(p)) for p in sys.argv[1:]], indent=1))

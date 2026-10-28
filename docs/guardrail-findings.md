# LLM proposal boundaries: findings and limits

Status: source review plus offline regression tests. No new live model evaluation,
production safety certification or personal expertise claim is implied.

## Context selection is part of the boundary

[Anthropic's context engineering guide](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)
supports selecting relevant input rather than sending all available context. The
scenario generator already sends a requirement and selected operations, not the
whole OpenAPI document. This update limits operation context to covers explicitly
opting into `llm-scenario`, consistent with `allowed_targets`.

This is data minimization and clearer scope, not proof of better model output.
Requirement text and selected schemas are still untrusted text. A prompt telling a
model to ignore embedded instructions is not a security guarantee. Do not put real
credentials or private data in a spec sent to a remote provider.

## A concrete mixed-cover gap

A requirement can cover both LLM-selected and ordinary deterministic checks. The
prompt advertised only the `llm-scenario` targets, but the review gate previously
matched operation/status against *all* covers. A proposal could match an ordinary
cover while a different cover on the same requirement supplied LLM traceability.

The gate now checks operation/status against explicit LLM covers for opted-in
requirements. A regression test constructs a 404 LLM cover alongside an ordinary
200 cover for the same operation. A 200 suggestion is rejected even though it
matches the ordinary cover. This is a deterministic gate finding, not a claim that
a particular live model exploited it.

Additional offline tests cover the 50/51-proposal envelope boundary, rejection of
unknown operations/extra control fields, no executor requests for a fully rejected
batch, and omission of unrelated operation context. Existing provenance records the
prompt, raw reply and accept/reject reason.

## Validation and approval are different

[OpenAI's guardrails and human review guide](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
distinguishes automatic checks from human decisions before sensitive effects. The
provider-specific examples are a design reference, not a dependency in this toolkit.

Passing the spec gate means a test is structurally in scope. It does **not** make an
operation safe, authorize a target, or guarantee a harmless request body. Review the
generated plan before running it. Use a disposable service/test environment, explicit
target allowlisting outside this tool and least-privilege test credentials. Never run
destructive scenarios against production merely because a model or schema accepted
them. No new automatic approval, hosted tracing or network service is added here.

## Next measurable question, not an executed finding

Compare current selected-operation context with a fuller contract under fixed model,
settings, requirements and candidate budget. Measure accepted useful cases, rejection
reasons, coverage and reported usage. Retain prompts and test outcomes. Do not report
higher coverage as better safety without examining the actual cases. Live calls and
costs require approval; this update runs only offline fixtures and local tests.

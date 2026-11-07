# LLM-04: evidence-driven improvements after real GigaChat trial

Baseline commit: `4a8419cec59d115920ca512bdf821cf2eb1b6f57`, branch `feat/v013-editorial-quality`.

## Evidence (2026-11-07)

Six real structured GigaChat replies for three products all parsed as valid JSON, but none passed the model-only validation. SEO lengths: РОСМА 635/665; ОВЕН ТРМ202 732/876; ОВЕН ПД200 732/794. End-user `ready_for_review` resulted from fallback, not model SEO.

- The model frequently returned SEO below the 800-character minimum.
- The refined ТРМ202 response included speculative applications and mentioned certificates despite the source lacking them.
- The model combined alternative HART and RS-485 interfaces without an execution qualifier.
- Model responses expanded IP54/IP65 into water/dust properties absent from structured specifications; IP54 was even connected to jets, which is technically inappropriate.
- ROSMA `refinement_selected` was traced even though the selected draft was still short and immediately replaced by fallback; `refinement_partial` now distinguishes that event.

## Changes

- **Prompt:** precise 4-paragraph length plan only for rich product specifications; no meaningless padding or invented facts; separate reminders not to invent IP interpretations, interface compatibility, certificates or guarantees.
- **Refinement:** more concrete target lengths and warning language for 8+ facts, only one existing refinement call, unchanged structured JSON schema.
- **IP guard:** conservatively reject a model's explicit IP water/dust interpretation when source `specs` does not support the explanation. Listing `IP54`/`IP65` without interpretation remains allowed. This is *not* a general standards fact checker.
- **Variant guard:** when source shows HART / RS-485 as alternatives, flag unqualified `HART и RS-485` as possible simultaneous compatibility. Qualified `варианты серии` and explicit negations remain allowed.
- **Trace:** `refinement_partial` replaces `refinement_selected` only when the selected refined draft still has `requires_revision`.

## Acceptance

1. All existing tests remain green, new negative tests pass, Ruff PASS, branch coverage >=95% and HTTP offline acceptance PASS.
2. `main` unchanged; no GigaChat calls, no historic JSON rewrites, no commit/push from patch installer.
3. Next: deploy/commit on feature branch after checks, then *separate* 3-product live A/B trial with new reports. Prompts alone do not prove a quality improvement; 4/5 editorial score still requires human review.

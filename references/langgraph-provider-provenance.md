# P0.1 — LangGraph provider provenance spike

Date: 2026-08-03
Runtime: Python 3.11, `langgraph==1.2.10`, `langchain-core==1.5.3`
Scope: determine whether a direct LangChain model call can prove the serving
model in `response_metadata` or `usage_metadata`.

## Verdict

**The spike decision is complete: no provider is approved for a direct-call
judgment seat from this run.** A provider that was not observed returning a
resolved serving model is treated as **unverifiable** until a live probe proves
otherwise. The safe Q2 fallback is active: keep every seat behind an existing
subprocess harness until a matrix row is promoted by live evidence. This closes
the implementation decision without pretending the unavailable provider probes
succeeded.

The configured provider probe failed before a completion was produced. That is
an unavailable-completion result, not evidence about whether a provider reports
`actual_model`.

## Provider matrix

| Family | Provider/model probe | Response metadata | Usage metadata | Classification | Direct-call viable? |
|---|---|---|---|---|---|
| anthropic | not run; adapter/credential unavailable in the probe environment | unobserved | unobserved | not measured → treat as unverifiable | no evidence |
| openai-codex | not run; no direct LangChain adapter/credential available | unobserved | unobserved | not measured → treat as unverifiable | no evidence |
| kimi | not run; adapter/credential unavailable | unobserved | unobserved | not measured → treat as unverifiable | no evidence |
| minimax | request failed before completion | unavailable because the call failed | unavailable because the call failed | blocked, not a provenance result | no evidence |
| qwen | not run; adapter/credential unavailable | unobserved | unobserved | not measured → treat as unverifiable | no evidence |
| xai | not run; adapter/credential unavailable | unobserved | unobserved | not measured → treat as unverifiable | no evidence |
| zai | not run; adapter/credential unavailable | unobserved | unobserved | not measured → treat as unverifiable | no evidence |

The rows follow `schema/families.json`; “no evidence” is deliberately not a
claim that the provider cannot report the model. The probe must be repeated on
a host with the corresponding optional adapter, credentials, and a successful
trivial completion before a provider can be promoted to direct-call viable.

## Probe procedure

The successful portion of the Minimax run used `langchain-openai` against the
documented OpenAI-compatible endpoint and captured only sanitized metadata. It
did not print the API key or response content. A future complete probe should:

1. send a trivial completion through `init_chat_model` with a deliberately
   aliased model id;
2. record only model-like fields from `response_metadata` and token fields from
   `usage_metadata`;
3. classify the result as resolved-model echo, alias echo, or no report; and
4. set `direct-call viable` only for the resolved-model-echo case.

## Consequence for P1/P2

The package may proceed with framework-neutral core work, but direct-call
`SeatModel` support must default to fail-closed. Until a provider row is proven,
judgment seats use subprocess execution or return `unverifiable`; no
`best-effort` mode is permitted.

# Does Beastmode improve coding outcomes? A controlled evaluation of planning, delegation, and review

**Working paper — protocol frozen; trial generation in progress; no effectiveness results yet.**

## Abstract

Beastmode separates planning and judgment review from implementation by an economy model. This study will compare a bounded manual implementation of that workflow with a single implementation attempt and a self-revision control. The frozen design calls for twelve independently scored Python utility tasks, two repetitions, and held-out executable tests. The primary endpoint is complete task correctness. Secondary endpoints include partial correctness, regressions, latency, and observed token usage. The study has not produced scored outcomes; effectiveness, superiority, and cost savings are currently unproven.

## 1. Question and hypotheses

The question is whether an explicit acceptance plan and independent director review improve final functional correctness over implementation alone, and whether any benefit survives comparison with an additional self-revision call. We hypothesize that decomposition and review can catch omissions in contracts involving ordering, boundaries, and interacting rules. Extra coordination could also introduce errors or overhead. Both directions are part of the study.

The intervention is the recorded manual workflow in this study. It is not a test of every Beastmode adapter, the learning loop across deployments, multi-worker scaling, or production repository development. Claims about those capabilities require separate evaluations.

## 2. Related work

Kim et al. study agent coordination under controlled conditions and find that architectural benefits depend on the task; coordination can also reduce performance. Their April 2026 revision motivates measuring overhead and preserving negative outcomes. [Kim et al., v3](https://arxiv.org/abs/2512.08296v3)

NIST CAISI documents cases where evaluation agents gain unintended access to solutions or other privileged information. We separate public task material from held-out tests and retain call traces for contamination audits. [NIST CAISI](https://www.nist.gov/caisi/cheating-ai-agent-evaluations/2-examples-cheating-caisis-agent-evaluations)

SWE-rebench addresses contamination in software engineering evaluation through fresh task collection. Our newly authored tasks reduce direct reliance on known benchmark solutions, but differ substantially from real repository issues and cannot establish real-world validity. [SWE-rebench](https://arxiv.org/abs/2505.20411)

None of these sources measures Beastmode. They inform the design, not the result.

## 3. Methods

The authoritative pre-trial design is PROTOCOL.md. Twelve task contracts span six families: dependency scheduling, interval operations, event reduction, record reconciliation, parsing, and resource allocation. Each exposes solve(payload) with JSON-compatible input and output. Public examples and precise semantics are shared across arms; held-out cases are not used for planning or repair. Fixture references and mutation checks must pass before freeze.

The single arm receives one implementation call. The self-revision arm reuses that initial solution and receives one fresh revision call. The Beastmode arm receives the director's public-specification plan, a separate economy implementation, director review, and one economy revision. The shared initial output makes single versus self-revision a paired incremental comparison. Matching executor calls does not match total compute: director planning and review are additional resources.

Both repetitions remain in analysis. Task, rather than individual assertion or repetition, is the unit for generalization. We report task-cluster bootstrap intervals for paired differences and explicitly flag limited information from a small or saturated sample. Missingness and infrastructure failures remain in the manifest and denominator accounting.

The schedule contains 24 task/repetition blocks, shuffled with Python random.Random(20260911). Within each block, the baseline and Beastmode workflow order is independently shuffled. Calls execute serially. Both revision calls always occur, including when review finds no defect. The final Beastmode outcome is its revision output; the study never selects whichever intermediate artifact scores best. All 12 director plans were frozen before generation, and each of the 24 Beastmode initial outputs receives its own recorded review. The director remains blind to baseline candidates and held-out scores until all reviews finish.

The economy model configuration is gpt-5.6-luna with maximum reasoning, invoked through codex exec. Each call has a 600-second execution limit. Runtime model and reasoning evidence is bound to the exact child session's turn_context records. This is client runtime evidence; a proprietary backend snapshot is not independently attested. Forbidden model tool use and missing or mismatched provenance invalidate the evidence. Such artifacts remain unsolved in the fixed 24-per-arm denominator, and contamination or identity uncertainty propagates to dependent revision outputs. A syntax error under a valid initial call remains legitimate repair input. Only pre-response infrastructure failure permits one identical logged retry; all measured retry usage is retained.

Candidate scoring uses a fresh bubblewrap namespace for every case, with network isolation, a scrubbed environment, private temporary storage, and no host home, grader, reference, or expected-output file mounted. Inputs arrive through standard input; expected outputs remain in the parent. Per-case limits are 256 MiB address space, two CPU seconds, five wall-clock seconds, and 1 MiB standard output. Output must be a single JSON value; comparison distinguishes Boolean and numeric scalar types and preserves array order. The environment receipt records the interpreter hash and versions, but the study does not use a fully pinned container image.

Primary quality is the mean of task-level solve rates, each averaging its two repetitions. Partial correctness also weights tasks and repetitions equally, rather than pooling assertions. Paired contrasts include Beastmode minus single, Beastmode minus self-revision, and self-revision minus single. The primary exploratory interval uses 10,000 task-cluster bootstrap resamples with seed 20260911 and percentile bounds with linear interpolation. A sensitivity analysis resamples the six task families, retaining both tasks and repetitions in each family. Repair regressions compare stored initial and final solutions only after generation and all director reviews are complete. Missingness, invalid evidence, execution failures, and unavailable usage fields remain explicit.

### Execution deviations recorded before scoring

After 40 completed calls, the frozen driver's post-substitution guard rejected a literal pair of closing braces in task09's public nested-JSON example as an unresolved template placeholder. No model had launched for that stage. The operator preserved all frozen files, performed the same ordered substitutions explicitly, recorded the prompt hash and recovery receipt, and invoked the unchanged harness CLI with its schedule and frozen-input checks. Affected subsequent task09 prompts use the same documented procedure. This is an orchestration deviation, not a change to task wording, model configuration, treatment or scoring rules.

The task09 repetition2 Beastmode initial harness then exited with observed process status143 before persisting a terminal record or buffered output. Its exact child PID was confirmed absent. The model's exit status, final output, actual completion time, usage and runtime identity were unavailable; the cause remains unresolved. The original running record was retained, and the invocation was marked interrupted and unverified. No retry was justified because a pre-response failure could not be established. The required revision receives the protocol's missing-output sentinel, and inherits the initial call's invalid evidence status. These records remain in the full denominator. Final generation reconciliation will report any further deviations and distinguish execution failure from functional failure.

## 4. Results

Not yet measured. No rates, superiority claims, significance claims, or cost reductions can currently be reported. Populate this section only from the complete frozen trial matrix and independently reproduced scores.

## 5. Threats to validity

The task suite is small, synthetic, and authored within the same study. Fully specified utility programming differs from ambiguous feature work, repository navigation, and long-running development. The benchmark and evaluated model family may share inductive biases. A strong baseline may yield ceiling effects. Passing a finite test set is not a proof of semantic correctness.

The intervention bundles director planning and review and adds unbalanced director computation. It therefore cannot isolate individual components or establish efficiency without additional controls and reliable cost accounting. The original single output is shared with the revision arm, and repeated trials within task are correlated. A narrow or degenerate bootstrap interval in a small saturated sample does not prove general equivalence.

The authors are evaluating their own workflow. Freezing the protocol, retaining unfavorable results, separating held-out evaluation, and sharing reproducible artifacts mitigate but do not eliminate this conflict. Independent replication and external task evaluation remain necessary for broad claims.

## 6. Conclusion

Pending completed experiments. The final conclusion must distinguish observed differences on this suite from claims that remain untested.

## Reproducibility statement

Study branch: research/effectiveness-evals-20260911. Base source revision: 346bbb4b1459a6c71f1a57953ffc13cc15377ecf. Intended artifact directory: evals/effectiveness. Run 20260911-main freezes 84 inputs under manifest SHA-256 a70093e22325429d31029f812a428bc467658d479087c758dd97d3de56b50972. All 12 task plans were fixed before generation. Reference validation covered 41 public examples and 285 held-out cases; all 24 deliberate mutants were detected. Both fixture batches passed independent semantic audits. Generation is in progress; the completed outcome table does not yet exist.

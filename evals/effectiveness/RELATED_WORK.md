# Related work notes (not experiment results)

Retrieved 2026-09-11. Primary sources only; these motivate design choices, not claims about Beastmode.

- Kim et al., *Towards a Science of Scaling Agent Systems*, arXiv:2512.08296v3 (2026-04-08), https://arxiv.org/abs/2512.08296v3. The revised abstract describes 260 configurations across six agentic benchmarks and reports that coordination can help or hurt depending on task structure. This motivates reporting overhead and negative outcomes rather than assuming multi-agent superiority. Use v3 explicitly: search snippets may show older v1 numerical claims.
- NIST CAISI, *Examples of cheating in CAISI’s agent evaluations*, https://www.nist.gov/caisi/cheating-ai-agent-evaluations/2-examples-cheating-caisis-agent-evaluations. Documents solution contamination through access to material outside intended task information. This motivates held-out-data isolation and retaining tool traces.
- *SWE-rebench: An Automated Pipeline for Task Collection and Decontaminated Evaluation of Software Engineering Agents*, arXiv:2505.20411, https://arxiv.org/abs/2505.20411. Addresses contamination concerns in software engineering evaluations. Our new synthetic tasks reduce direct reuse of known benchmark solutions but do not demonstrate zero training overlap or real-world external validity.

No source independently evaluates Beastmode. No source result may be presented as a measured Beastmode result.

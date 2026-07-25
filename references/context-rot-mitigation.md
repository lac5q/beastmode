# Context Rot in Multi-Agent Orchestration

## The Problem

Beastmode/ultraswarm orchestrates multiple subagents (Codex, Qwen, Gwen), each generating tool outputs, file reads, and intermediate results. When these outputs accumulate in the main orchestrator's context, the context grows rapidly:

- **10-15 minutes into a beastmode run:** 300-500KB of accumulated context
- **Sources:** Agent summaries, tool outputs, file contents, planning docs, QA results
- **Symptoms:** Headroom compression timeouts (413 errors), Codex /compact failures, "Bad Request" errors

## Root Cause

The orchestrator (Codex/Claude Code) receives the **full output** from each subagent, including:
- Intermediate tool calls and results
- File reads and diffs
- Planning documents
- QA/merge logs
- Self-improvement entries

This is **not** a beastmode skill length issue (the skill is 416 lines, within the 250-450 target). The issue is **context accumulation during execution**.

## Solutions

### Immediate Fixes

#### 1. Preserve the Prompt Cache (Do Not Compress Prompts)

Prompt caching is the single largest token lever available, and it is destroyed by
prompt-rewriting proxies. Anthropic caches on an **exact byte prefix**: cache reads
bill at **0.10x** and cache writes at **1.25x**. A stable prefix therefore approaches
a 90% discount on everything before the new turn.

Any middlebox that rewrites message payloads (LLMLingua-style compression, injected
timestamps, reordered tool schemas) changes those prefix bytes and converts a 0.10x
read into a 1.00x uncached read.

**The break-even math** — for compression saving `s` fraction of input tokens:

```
cost_uncompressed(C) = C*0.10 + (1-C)*1.00     # C = cacheable prefix fraction
cost_compressed      = (1-s)*1.00              # prefix mutated => no cache hits

break-even C = s / 0.90
```

At a measured `s = 5%`, break-even is **C = 5.6%**. If more than 5.6% of your prefix
would have been a cache hit, compression is a net loss. Agent workloads — stable
system prompts, repeated tool schemas, growing history — sit far above that.

| cache hit fraction | uncompressed | compressed (5%) | winner |
|---|---|---|---|
| 0% | 1.000 | 0.950 | compress |
| 25% | 0.775 | 0.950 | **direct** |
| 50% | 0.550 | 0.950 | **direct** |
| 90% | 0.190 | 0.950 | **direct** |

**Rule:** route agent traffic through a pass-through proxy. Do not enable prompt
compression at the API layer.

> Historical note: this project previously recommended a local LLMLingua proxy
> (`headroom`) with a fail-open flag. Measured over 24,508 requests / 1.82B input
> tokens it delivered **5.18%** input-token reduction — real, but an order of
> magnitude smaller than prompt caching, and in direct tension with it. It also
> compressed at least one 19,176-token tool output to **zero**. Removed 2026-07-25.

#### 2. Compact More Aggressively

Don't wait for context to break. Run `/compact` early and often:

- **Every 5-10 minutes** during beastmode runs
- **After each major phase** (planning, execution, QA, merge)
- **Before escalation** (when switching from Qwen to Codex)

**Rule of thumb:** If you've delegated 3+ subagent tasks, compact before continuing.

#### 3. Limit Beastmode Session Duration

Restart on **context pressure**, not on a timer. A restart discards a warm prompt
cache (see fix #1), so it has a real cost — the 20-30 minute figure below is a
heuristic for when context *typically* becomes the binding constraint, not a rule to
follow while context is still healthy.

When context does become the constraint:
- Save state (commit work, write learnings)
- Start a fresh session
- Resume from the saved state

**Why:** Context grows non-linearly. A 30-minute run might have 200KB, but a 60-minute run might have 600KB+ (due to accumulated diffs, planning docs, etc.).

### Architectural Fixes

#### 4. Subagent Output Summarization

**Problem:** Subagents return full tool outputs, which accumulate in the orchestrator's context.

**Fix:** Subagents should return **only the final result**, not intermediate steps.

**Example:**
```python
# Bad: Subagent returns full execution log
delegate_task(
    goal="Implement feature X",
    # Returns: 50 tool calls, 20 file reads, 10 diffs = 100KB
)

# Good: Subagent returns summary
delegate_task(
    goal="Implement feature X. Return only: (1) files changed, (2) tests passed/failed, (3) any issues. Do not include intermediate tool outputs.",
    # Returns: 3-line summary = 1KB
)
```

**Implementation:** Update ultraswarm to instruct subagents to summarize their outputs.

#### 5. Context Boundaries

**Problem:** Beastmode runs accumulate context indefinitely.

**Fix:** Use explicit context boundaries:
- **Phase 1 (Planning):** Compact before starting execution
- **Phase 2 (Execution):** Compact after each subagent delegation
- **Phase 3 (QA/Merge):** Compact before final review
- **Phase 4 (Self-improvement):** Compact after writing learnings

**Implementation:** Add explicit "compact now" checkpoints to the beastmode loop.

#### 6. Limit Subagent Scope

**Problem:** Subagents tackle large tasks, generating lots of intermediate output.

**Fix:** Break tasks into smaller units. One subagent = one small, bounded task.

**Example:**
```python
# Bad: One subagent implements entire feature
delegate_task(goal="Implement user authentication system")
# Returns: 200KB of output

# Good: Multiple subagents, each with small scope
delegate_task(goal="Create User model with email/password fields")
delegate_task(goal="Implement /login endpoint")
delegate_task(goal="Add password hashing utility")
# Each returns: 10-20KB of output
```

**Tradeoff:** More subagent calls, but each call has smaller context impact.

### Compression Strategy

#### 7. Compress Tool Output, Never the Prompt

There are two distinct layers, and they have opposite verdicts:

| Layer | Tool | Verdict | Why |
|-------|------|---------|-----|
| CLI / tool output | squeez | **Use** | Shrinks text *before* it enters context; prefix stays byte-stable, cache intact |
| API layer (prompt rewriting) | headroom / LLMLingua | **Do not use** | Mutates the cached prefix; trades a 90% discount for ~5% savings |

Compressing a tool result before it is appended is strictly good: fewer tokens enter
the conversation, and every byte already in the prefix is untouched. Compressing the
assembled prompt in flight is strictly bad: it rewrites the prefix other turns depend on.

**Setup:**
```bash
# Install squeez
cargo install squeez

# Configure for Codex
# Add to ~/.codex/config.json:
{
  "hooks": {
    "PostToolUse": "~/.local/bin/squeez hook codex"
  }
}
```

**Warning:** Watch for "compression tax" — if compression is too aggressive, the agent compensates by asking follow-up questions or re-running commands, emitting MORE tokens than saved. Squeez has adaptive intensity to detect this; RTK does not.

**Corollary — compact less often than instinct suggests.** `/compact` rewrites
conversation history, which resets the cached prefix and forces a full re-write at
1.25x. Compaction is still correct when context genuinely threatens the window, but
every compaction has a real cost. Prefer bounded subagents (fix #4/#5) that keep the
orchestrator prefix small, so compaction is needed rarely.

#### 8. Avoid Compressing Critical Context

Some outputs should NOT be compressed:
- Error messages and stack traces (need full context for debugging)
- Small files (< 100 lines) — compression overhead > savings
- Structured data the agent needs to parse exactly (JSON APIs, CSV)
- Interactive prompts (password prompts, Y/N)

**Implementation:** Configure squeez/headroom to skip these patterns.

## Recommended Action Plan

### Phase 1: Immediate Relief (Today)

1. **Verify no prompt-rewriting proxy is in the chain** — `echo $ANTHROPIC_BASE_URL` should point at a pass-through endpoint
2. **Keep the prefix stable** — no timestamps or rotating text in system prompts
3. **Limit beastmode sessions to 30 minutes** — start fresh after

### Phase 2: Architectural Improvements (This Week)

4. **Update ultraswarm to summarize subagent outputs** — only return final results, not intermediate steps
5. **Add explicit compact checkpoints** to beastmode loop (after each phase)
6. **Install squeez** for CLI output compression (tool-output layer only)

### Phase 3: Long-Term Optimization (Next Week)

7. **Break large tasks into smaller subagent units** — reduce per-subagent context
8. **Monitor compression tax** — if agent starts asking more follow-ups, back off compression intensity
9. **Consider context isolation** — run subagents in separate processes that don't share context with orchestrator

## Beastmode Skill Updates

Add a new section to the beastmode skill:

```markdown
## Context Management

Beastmode runs accumulate context fast. Follow these rules to avoid context rot:

1. **Compact every 5-10 minutes** — don't wait for context to break
2. **Limit sessions to 30 minutes** — save state, start fresh, resume
3. **Subagent output summarization** — instruct subagents to return only final results, not intermediate steps
4. **Compact after each phase** — planning, execution, QA, merge, self-improvement
5. **Never run prompt compression at the API layer** — it destroys prompt-cache hits (0.10x reads become 1.00x)
6. **Compress tool output, not prompts** — squeez on tool results is safe; LLMLingua-style prompt rewriting is not
7. **Break large tasks into small units** — one subagent = one small, bounded task

**Rule of thumb:** If you've delegated 3+ subagent tasks, compact before continuing.
```

## Tradeoffs

| Solution | Benefit | Cost |
|----------|---------|------|
| Prompt-cache preservation | Up to 90% off repeated prefix | Requires byte-stable prompts; no in-flight rewriting |
| Aggressive compacting | Keeps context small | Resets cached prefix (full re-write at 1.25x) |
| Session limits | Prevents context bloat | Cold cache on restart; need to save/resume state |
| Subagent summarization | Reduces context accumulation | May lose debugging details |
| Tool-output compression (squeez) | Fewer tokens enter context, cache-safe | Setup overhead, potential compression tax |
| Smaller subagent tasks | Less context per task | More subagent calls, each with a cold prefix |

## Monitoring

Track these metrics to detect context rot:

- **Cache hit rate:** the primary metric. From any API response, compute
  `cache_read_input_tokens / (input_tokens + cache_read_input_tokens + cache_creation_input_tokens)`.
  Sustained <30% on a long session means the prefix is being invalidated somewhere.
  Run `scripts/cache-hitrate` to verify caching survives your proxy chain.
- **Upstream fan-out:** if a proxy round-robins across multiple upstream accounts or
  endpoints, each maintains **separate cache state**, so an identical prompt can
  alternate between hit rates. Caching still works, but a single request's hit rate
  is not the whole picture — average across several calls before concluding anything.
- **Compact frequency:** How often are you running `/compact`? Each one resets the cache.
- **Session duration:** Are beastmode runs exceeding 30 minutes?
- **Subagent output size:** Are subagents returning large outputs?

**Alert thresholds:**
- Context size > 200KB → compact now
- Compression failures > 3/hour → enable fail-open or increase timeout
- Session duration > 30 minutes → save state and restart

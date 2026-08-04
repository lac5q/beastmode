# Public Sharing Checklist

When publishing beastmode or similar skills publicly, sanitize these items:

## Must Remove

| Item | Example | Why |
|------|---------|-----|
| Local file paths | `<user-local-tool-path>`, `<private-run-directory>` | Reveals machine setup |
| Internal project names | Client names, internal codenames | Leaks client/project info |
| Directory structure | `<private-knowledge-directory>` | Shows repo organization |
| Personal symlinks | "Codex, Qwen symlink to that store" | Reveals multi-agent setup |
| Credentials/secrets | API keys, tokens, service account paths | Obvious |
| Machine-specific commands | Custom automation scripts | Ties to your environment |

## Safe to Keep

- Generic tool names (`qwen-agent`, `codex exec`, `ultraswarm`)
- Conceptual architecture (role separation, self-improvement loop)
- Execution modes and commands (without local paths)
- Cost discipline principles
- Acceptance contract templates

## Publishing Workflow

1. **Audit**: Scan every tracked file, generated artifact, and release commit for credentials, private paths, internal names, and sensitive metadata
2. **Sanitize**: Remove or generalize local references
3. **Verify**: Run the repository's fail-closed public-artifact guard and the official security scan on the exact release commit
4. **Create repo**: Publish only after both checks complete successfully
5. **Share**: Use the repo URL in social posts, docs, etc.

## Social Promotion Pattern

When sharing on X/LinkedIn:
- Find 5-10 relevant conversations (search thread replies, not just root tweets)
- Tailor each reply to the conversation context
- Lead with the differentiator (self-learning, zero marginal cost, existing subs)
- Include repo link + "Re: <original tweet URL>" format
- Post as new tweets (can't reply to threads where you weren't mentioned)

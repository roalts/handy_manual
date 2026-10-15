# Coordination

All communication between the agents building this project happens in Markdown files in this
folder. Agents never message each other. Messages to and from the orchestrator are written here
too; a chat message may only point at a file here, never carry content of its own.

## Files

| File | Written by | Read by |
|---|---|---|
| `orchestrator.md` | orchestrator only | everyone |
| `answer-engine.md` | answer engine agent (002) only | everyone |
| `web-client.md` | web client agent (004) only | everyone |
| `answer-api.md` | answer API agent (003) only | everyone |
| `work-orders.md` | work orders agent (005) only | everyone |
| `evaluation.md` | evaluation harness agent (006) only | everyone |

A new agent gets its own `<component>.md`. Shared design lives in `specs/contracts/` and each
feature's `specs/NNN-*/` folder, as before; this folder is for status, questions and requests.

## Rules

1. **Write only your own file.** Read the others' whenever you start a task and before you finish.
2. **Append, don't rewrite.** Add entries at the bottom under a dated heading:
   `## 2026-10-12 19:40 — <short title>`. Status sections at the top may be updated in place.
3. **Each entry has a type** on its first line: `STATUS`, `QUESTION (to: …)`, `ANSWER (to: …)`,
   `REQUEST (to: …)` (for example, a contract change), `DECISION`, or `BLOCKER`.
4. **Requests and questions are answered in the recipient's own file**, quoting the heading they
   answer. Nobody edits another agent's file to reply.
5. **Contract changes** (`specs/contracts/`, `src/copilot_contracts/`) are only made by the
   orchestrator, after a `REQUEST` and a `DECISION` in `orchestrator.md`.
6. **Explain codes in parentheses** every time, as in `.cursor/rules/explain-codes.mdc`: for
   example HV-PROC-07 (high-voltage drive fault reset procedure, restricted), u06 (chiller
   technician without refrigerant certification).
7. **No secrets** in these files: never the API key or `.env` contents.
8. **Final report**: when an agent finishes, its last entry is a `STATUS` with what is built, how
   it was verified, spend, and open items. Its final chat message only says which file to read.

## Status block (top of each agent file)

```markdown
# <Component> — <agent>

**State**: working | blocked | done
**Current task**: …
**Last updated**: YYYY-MM-DD HH:MM
```

# Session 4 candidate promotion manifest

Owner: Session 4. Target reviewer: Session 0. No file in this directory is a
shared golden fixture until Session 0 explicitly promotes it.

| Candidate | Purpose | Expected disposition |
|---|---|---|
| `candidates/approve.json` | Contract-valid unchanged APPROVE with evidence codes | Promote as a positive verdict candidate after Session 0 independently validates it. |
| `candidates/reject.json` | Contract-valid non-actionable REJECT | Promote as a negative evidence-based verdict candidate. |
| `candidates/modify.json` | Contract-valid independently valid 1:1 MODIFY with shorter validity | Promote only if Session 0 accepts the `EVIDENCE_` reason-code adapter convention. |
| `candidates/expired.json` | Contract-valid EXPIRED with null prices | Promote as an expiry candidate. |
| `malformed/extra_prose.txt` | Prose before JSON | Must remain rejected. |
| `malformed/code_fence.txt` | Markdown-fenced JSON | Must remain rejected. |
| `malformed/tool_call.json` | Tool-call injection | Must remain rejected. |
| `malformed/prompt_injection.txt` | Artifact/prompt injection | Must remain untrusted and never become a verdict. |
| `technical_failures.json` | Mock provider/OpenClaw failure taxonomy | Technical results only; never promote as AI Verdict fixtures. |

Promotion checks:

1. Copy nothing automatically. Session 0 reviews exact bytes and hashes.
2. Run the frozen contract validator against all four candidate verdicts.
3. Run Session 4 post-gates with the recorded dispatch and trusted clock.
4. Preserve `fixtures/project_a/**` history; promote through a Session 0-owned
   commit and update replay expectations deliberately.
5. Record whether `EVIDENCE_<NORMALIZED_ID>` remains an adapter convention or a
   future contract change is approved.

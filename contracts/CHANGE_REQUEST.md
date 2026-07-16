# Contract change request process

1. Open a request owned by Session 0 with problem statement, proposing session,
   affected contract/version/fields, compatibility classification, security and
   rollback impact, and evidence that an adapter cannot solve it.
2. Attach old/new examples plus updated valid and invalid fixtures. Identify all
   readers, writers, persistence columns, and output adapters.
3. Session 0 decides: reject, solve in a feature adapter, approve additive minor,
   or approve breaking version. Silence is not approval.
4. Implement on a dedicated `project-a/contract-<topic>` branch. Session 0 owns
   schema/registry/shared fixture edits; feature owners update their adapters.
5. Required gates: schema meta-validation, contract tests, full offline replay,
   backward/forward compatibility matrix, security review, and rollback drill.
6. Merge readers before writers, then fixtures, then writers. Freeze the new
   version only after the integration branch passes all release gates.

Emergency rule: malformed or unsafe data is rejected. Do not loosen validation
in production to work around a feature-branch mismatch.

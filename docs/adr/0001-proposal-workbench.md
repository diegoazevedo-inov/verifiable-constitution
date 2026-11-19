# ADR 0001 — Proposal workbench: the model proposes, a human decides

Status: accepted.

Context: an agent may suggest who should take a pending work item in a regulated setting.
Decision: suggestions are records without effect; the effect happens only through a human decision recorded under the approver's identity (C1, C4). A deterministic rule (least open load) is the floor when the model is absent, fails or answers outside the contract (C1, C2). Evidence is mandatory and enforced in the service and in the database (C3). The audit trail is append-only and records reads of proposals (C5). Decided proposals cannot be changed, and no proposal can be deleted (C7). Reads go through tenant-scoped views. Database triggers refuse any insert, update, delete or replace that would make a proposal, a decision or an effect cross tenants: a proposal is inserted pending, its content cannot be rewritten, and a decision happens only by a checked update (C6). The connection turns recursive triggers on, so REPLACE cannot bypass the delete triggers.
Consequences: every guarantee has a check in `checks/` and at least one planted violation in `tools/mutants.py`.

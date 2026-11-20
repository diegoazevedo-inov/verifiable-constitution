# Verifiable constitution — generic template (C1–C10)

Each principle is written as a statement, one or more **Prohibits** clauses, and the **Verification** that must fail when a clause is violated. A clause is *covered* only when a check exists **and** every planted violation of that clause shows the check failing. **Reach** records whether the check would also catch a *new* case (`general`) or only the existing path (`instance`).

Reach is declared here by the author; it is not measured. `tools/coverage.py` copies it into its table. For a guarantee enforced by the database, `general` means that the prohibited state is refused for any INSERT, UPDATE, DELETE, REPLACE or UPSERT (`INSERT ... ON CONFLICT DO UPDATE`) on a connection opened by `connect()` in `example/workbench.py`, whatever the code path and whatever tenant the session is set to. SQLite has no roles, so the following are outside that reach: changing the schema (for example dropping a trigger), writing the session-tenant table directly, turning `recursive_triggers` off, and opening the database without `connect()`. A production system would reserve these to a schema-owner role that the application does not hold. Coverage refers to the **Prohibits** clauses only: a principle reported as FULL has every declared clause covered, which is not the same as its whole statement. Parts of a statement without a clause in the example are listed under **Not measured**.

The check identifiers refer to `checks/` in this repository, which applies the template to the minimal example in `example/`. The planted violations are in `tools/mutants.py`.

## C1 — Deterministic core; the model only proposes
Model output never becomes state by itself; a deterministic rule is the floor when the model is absent or fails.
- **Prohibits C1.a:** state or critical values created directly from model output.
- **Prohibits C1.b:** the task failing to happen because the model failed.
- **Verification:** `test_c1_proposal_has_no_effect_until_approved`, `test_c1_rule_is_the_floor_when_model_fails`. Reach: instance.

## C2 — The model chooses, it does not name
The system builds a closed list; the model may only point inside it.
- **Prohibits C2.a:** accepting a model answer that is not in the closed list (invented id, other tenant's id).
- **Verification:** `test_c2_out_of_list_choice_is_discarded`. Reach: instance.

## C3 — No proposal without traceable evidence; confidence is not evidence
- **Prohibits C3.a:** a proposal persisted without evidence.
- **Prohibits C3.b:** confidence, score or probability used as the only evidence.
- **Verification:** `test_c3_empty_evidence_is_rejected` (service), `test_c3_database_rejects_proposal_without_evidence` and `test_c3_database_rejects_whitespace_only_value` (constraint and trigger), `test_c3_confidence_is_not_evidence`, `test_c3_confidence_only_evidence_with_several_items_is_rejected`, `test_c3_confidence_is_recognised_as_a_word`. Reach: general for C3.a (database constraint and trigger), instance for C3.b.
- **Limit of C3.a:** the database requires a non-empty array in which every item has a code (capital letters, digits and underscores) and a non-empty text or numeric value; a text made only of ASCII white space (space, tab, line feed, vertical tab, form feed, carriage return) counts as empty. Other Unicode white space (for example a no-break space) is refused by the service, which uses Python's `str.strip()`, but not by the database. The database does not judge whether the value is correct.
- **Limit of C3.b:** confidence is recognised by the name of the evidence code: a code counts as confidence when CONFIDENCE, SCORE, PROBABILITY, CERTAINTY or LIKELIHOOD appears in it as a word, that is, delimited by the start or end of the code or by an underscore (MODEL_SCORE counts as confidence; SCOREBOARD_ID does not). Evidence is refused when all its items are confidence, whatever their number. A confidence value under another name (for example CONF, MODEL_PROB or LOGIT) is accepted as evidence.

## C4 — Validation by a qualified professional
- **Prohibits C4.a:** an effect executed, or a proposal decided (approved or rejected), without the decision recorded in the trail under the approver's identity.
- **Prohibits C4.b:** someone approving what they could not do directly.
- **Verification:** `test_c4_effect_belongs_to_the_approver`, `test_c4_rejection_is_recorded_under_the_approver`, `test_c4_unauthorized_approver_is_refused`. Reach: instance.

## C5 — Append-only trail, including reads and agent actions
- **Prohibits C5.a:** updating or deleting trail entries.
- **Prohibits C5.b:** an agent action recorded without agent identity, model and prompt version.
- **Prohibits C5.c:** reading proposals through the application without a trail entry that names the reader.
- **Verification:** `test_c5_trail_is_append_only` (trigger), `test_c5_agent_signs_its_proposals`, `test_c5_reading_proposals_is_recorded`. Reach: general for C5.a (triggers; REPLACE is refused because `connect()` turns recursive triggers on, so the row it would delete fires the DELETE trigger), instance for C5.b and C5.c.
- **Limit of C5.c:** only `Workbench.proposals()` records a read. The reads made while proposing or deciding are not recorded separately; the operation itself is (PROPOSE, APPROVE, REJECT).

## C6 — Tenant isolation enforced below the application
- **Prohibits C6.a:** reading another tenant's proposals, users or work items through the application path.
- **Prohibits C6.b:** a proposal whose work item or target belongs to another tenant, whether inserted that way, obtained by rewriting a proposal, or obtained by moving its work item or target to another tenant. A proposal is never deleted and its content columns (id, tenant, item, proposer, target, evidence) cannot be updated, so UPDATE, REPLACE and UPSERT cannot rewrite it; a proposed work item cannot be renamed or deleted, and a referenced user cannot change id or tenant or be deleted.
- **Prohibits C6.c:** a decision recorded under an approver from another tenant. A proposal can only be inserted pending and without an approver; the decision is an update, made from a session of the proposal's tenant and checked against the tenant of the proposal and of the approver, and the approver cannot later change tenant or be deleted.
- **Prohibits C6.d:** an effect on another tenant's work item, or a work item assigned to another tenant's user, whether by inserting, updating, deleting or replacing a work item, or by changing or deleting the assigned user.
- **Verification:** `test_c6_cross_tenant_read_returns_nothing` (C6.a); `test_c6_proposal_across_tenants_is_refused`, `test_c6_pending_proposal_cannot_be_rewritten`, `test_c6_proposed_item_keeps_its_identity`, `test_c6_target_keeps_its_tenant` (C6.b); `test_c6_approver_from_other_tenant_is_refused`, `test_c6_approver_keeps_its_tenant`, `test_c6_proposal_is_inserted_pending`, `test_c6_decision_from_another_tenant_session_is_refused` (C6.c); `test_c6_effect_across_tenants_is_refused`, `test_c6_assignee_keeps_its_tenant` (C6.d). Reach: instance for C6.a, general for C6.b, C6.c and C6.d.
- **Limit of C6:** the example reads through tenant-scoped views, but SQLite has no grants, so a new read of a base table would not be stopped (hence `instance` for C6.a). Writes are checked by database triggers against the session tenant and against the tenant of the item, target, assignee and approver: inserting, updating, deleting and replacing proposals and work items, and changing the id or tenant of, or deleting, the users they reference (hence `general` for C6.b–C6.d, in the sense defined at the top of this document). Other writes to users (inserting a user, changing a role, deleting an unreferenced user) and inserts into the audit trail are not checked against the session tenant. The session tenant is a table set by the application, which emulates a row-level security setting; production systems should use database row-level security.

## C7 — Validated records are immutable; retention is a duty
- **Prohibits C7.a:** changing a decided proposal.
- **Prohibits C7.b:** deleting a decided proposal.
- **Verification:** `test_c7_decided_proposal_is_immutable` (trigger), `test_c7_decided_proposal_cannot_be_deleted` (trigger). Reach: general (UPDATE, UPSERT and UPDATE OR REPLACE fire the update trigger; DELETE, and REPLACE with recursive triggers on, fire the delete trigger).
- **Not measured:** retention periods (how long records must be kept); the example only prevents deleting proposals (decided or pending; C6.b, C7.b) and trail entries (C5.a).

## C8 — No agent task without a passing evaluation for the (model, prompt version) pair
- **Prohibits C8.a:** calling the model when there is no approved evaluation for the current task, model and prompt version.
- **Verification:** `test_c8_no_eval_no_model_call`, `test_c8_eval_for_other_prompt_version_does_not_count`, `test_c8_eval_for_other_model_or_task_does_not_count`. Reach: instance.

## C9 — Model output and external channels are untrusted input
- **Prohibits C9.a:** free text from the model reaching the human approver as evidence.
- **Verification:** `test_c9_reason_code_is_restricted_to_the_contract`. Reach: instance.
- **Not measured:** external channels. The example has no external channel (no message, e-mail or webhook input), so that part of the statement is not instantiated here and is outside the measurement.

## C10 — Decision before code, traceable
- **Prohibits C10.a:** a production module without a reference to an existing decision record.
- **Verification:** `test_c10_every_module_cites_a_decision_record`: every module under `example/`, subfolders included, must cite at least one `docs/adr/<file>.md` path, and every cited file must exist; only an empty `__init__.py` is exempt. Reach: general (scans every `.py` file under `example/`).
- **Not measured:** that the decision came before the code (order in time); the check sees only the reference.

## Conflict hierarchy
C6 and C7 (data integrity) > C4 and C5 (accountability) > C2, C3, C8, C9 (agent containment) > C1, C10 (process).

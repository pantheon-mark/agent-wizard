# Interview Sequence

Numbered markdown state machine files. Claude reads them in order when running the wizard for a user. Each file covers one logical phase or topic group, specifies exact question wording for fixed questions, and ends with a handoff instruction to the next file.

## Files in this directory (as built)

| File | Question IDs | Phase |
|------|-------------|-------|
| `00_env_check.md` | ENV-1 | Pre-interview environment check |
| `01_phase1_capture.md` | P1-1, P1-2, P1-3 | Phase 1 — Immediate capture |
| `02_financial.md` | FIN-1, FIN-2 | Financial guardrails |
| `03_user_profile.md` | UP-1 through UP-5 | User profile |
| `04_notifications.md` | NOTIF-1 through NOTIF-6 | Notification channels |
| `05_vision.md` | V-1 through V-8 | Vision document interview |
| `06_approach.md` | (approach derivation) | Approach document |
| `07_advisors.md` | ADV-1 | Advisor identification |
| `08_architecture.md` | ARCH-1 through ARCH-5 | System design |
| `09_credentials.md` | CRED-1 through CRED-5 | Credentials and secrets |
| `10_validation.md` | GATE-1 through GATE-4 | Input validation gate |
| `11_error_handling.md` | ERR-1, ERR-2, ERR-3 | Error handling preferences |
| `12_qa_settings.md` | QA-1 through QA-4 | Quality preferences |
| `13_operations.md` | CONC-1, CONC-2, START-1, START-2, DRIFT-1, SCALE-1 through SCALE-4 | Operations settings |
| `14_document_review.md` | DOC-1, DOC-2 | Document artifacts |
| `15_close.md` | CLOSE-1 through CLOSE-4, GH-1, CLOSE-5 through CLOSE-14 | Closing sequence (GH-1 embedded after CLOSE-4) |

## How answers become documents (the group flow)

The 16 files above are the **question carriers**. Underneath, the wizard organizes the work into a small set of **logical groups** (defined as data in the `derivation_groups` registry — not a change to the file layout). The flow for each group is **record → derive → confirm (via preview) → close**:

1. **Record** — each answer is written to a durable transcript (`~/claude-wizard-draft/wizard_transcript.jsonl`) the moment it is given.
2. **Derive** — once a group's inputs are complete, that group's foundation-doc content is derived from the recorded answers.
3. **Preview + confirm** — the operator is shown a **rendered preview** of the group's document(s) and confirms before the group closes.
4. **Close** — a group-close marker carrying a **source hash** is written, so a resumed session knows the group is done and can detect when an earlier answer was edited afterward.

The complete system is **emitted in one pass at `15_close.md`** (CLOSE-EMIT) from the confirmed transcript. Mid-interview document writes are **retired** — earlier versions wrote `approach.md`, `technical_architecture.md`, and other docs partway through; now nothing is written until close, generated from exactly what the operator confirmed. Cold-resume reads **both** the step markers and the group markers, so an interrupted session resumes without re-asking answered questions or re-deriving confirmed (and still-fresh) groups; if an earlier answer feeding a confirmed group was edited, that group's confirmation is invalidated (its source hash no longer matches) and it is re-derived and re-confirmed.

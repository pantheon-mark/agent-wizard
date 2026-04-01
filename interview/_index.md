# Interview Sequence

Numbered markdown state machine files. Claude reads them in order when running the wizard for a user. Each file covers one logical phase or topic group, specifies exact question wording for fixed questions, and ends with a handoff instruction to the next file.

## Files in this directory (18 total)

| File | Question IDs | Phase |
|------|-------------|-------|
| `00_env_check.md` | ENV-1 | Pre-interview environment check |
| `01_phase1_capture.md` | P1-1, P1-2, P1-3 | Phase 1 — Immediate capture |
| `02_financial.md` | FIN-1, FIN-2 | Financial guardrails |
| `03_user_profile.md` | UP-1 through UP-5 | User profile |
| `04_notifications.md` | NOTIF-1 through NOTIF-6 | Notification channels |
| `05_vision.md` | V-1 through V-8 | Vision document interview |
| `06_advisors.md` | ADV-1 | Advisor identification |
| `07_system_design.md` | ARCH-1 through ARCH-5 | System design |
| `08_error_handling.md` | ERR-1, ERR-2, ERR-3 | Error handling preferences |
| `09_quality_prefs.md` | QA-1 through QA-4 | Quality preferences |
| `10_validation_gate.md` | GATE-1 through GATE-4 | Input validation gate |
| `11_credentials.md` | CRED-1 through CRED-5 | Credentials and secrets |
| `12_concurrency.md` | CONC-1, CONC-2 | Concurrency and recovery |
| `13_startup_behavior.md` | START-1, START-2 | Session startup behavior |
| `14_drift_review.md` | DRIFT-1 | Drift and review cadences |
| `15_scale_tier.md` | SCALE-1 through SCALE-4 | Scale tier |
| `16_document_artifacts.md` | DOC-1, DOC-2 | Document artifacts |
| `17_closing_sequence.md` | CLOSE-1 through CLOSE-14 | Closing sequence |

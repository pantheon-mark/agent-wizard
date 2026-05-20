# Templates — Docs Directory

Templates for files in the user's System `/docs/` directory.

## Files in this directory

| Template file | Generates | Notes |
|--------------|-----------|-------|
| `document_impact_map.md` | `/docs/document_impact_map.md` | Pre-populated with the standard change event taxonomy from Item 9; wizard adds project-specific change categories based on agent roster and data sources |
| `architectural_review_staging.md` | `/docs/architectural_review_staging.md` | Empty structure at setup; populated at runtime with phase-gate staging findings |
| `future_items.md` | `/docs/future_items.md` | Three sections (date-triggered, condition-triggered, monitoring cadence); monitoring cadence pre-populated from wizard answers; date/condition rows populated from deferred items captured during interview |
| `voice_and_style.md` | `/docs/voice_and_style.md` | Seeded from user profile (UP-1 through UP-5), notification verbosity (ERR-1), QA reporting style (QA-1), and vision document voice; no new interview questions |
| `how_your_system_works.md` | `/docs/how_your_system_works.md` | Static operator-facing prose explaining how the agent team manages itself across 11 topic areas (problem-finding / log management / recovering from problems / session management / model management / tool updates / document updates / quality checking / security / PII handling / pre-flight checks); no new interview questions |

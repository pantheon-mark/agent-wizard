# Templates — Quality Directory

Templates for files in the user's System `/quality/` directory.

## Files in this directory

| Template file | Generates | Notes |
|--------------|-----------|-------|
| `validation_gate_config.md` | `/quality/validation_gate_config.md` | Pre-populated from GATE-1 and GATE-2 answers — input type inventory and domain sensitivity settings |
| `co-protected-workflows.md` | `/quality/co-protected-workflows.md` | Pre-populated from Tier 1 categories (money, external communication, irreversible action, guardrail violation, legal/compliance); not user-editable without architectural review |
| `source_registry.md` | `/quality/source_registry.md` | Header and structure; source rows derived from the QA-3 confirmed-source answers and emitted at close (SOURCE_REGISTRY_ROWS). Empty table if the operator confirmed no external sources. Health/Last-verified columns fill at runtime |
| `capability_descriptor_registry.md` | `/quality/capability_descriptor_registry.md` | Header and structure; rows are a QA projection of the confirmed external-dependency identity record's typed capability descriptors (CAPABILITY_DESCRIPTOR_REGISTRY_ROWS) — action class, fail-safe-resolved risk class, test target, blast-radius cap, recovery profile, accepted (always `No` at setup). Empty table if no dependency declares a capability descriptor. The machine-readable set runtime enforcement consumes is a separate emitted artifact (`security/capability_descriptors.json`), not this file (B1-2, wiring at B2) |
| `rules_library.md` | `/quality/rules_library.md` | Empty structure at setup — populated at runtime from human feedback |
| `human_review_queue.md` | `/quality/human_review_queue.md` | Empty structure at setup — populated at runtime |
| `advisor_knowledge_base.md` | `/quality/advisor_knowledge_base.md` | Pre-populated with advisor header entries from ADV-1 — one header per confirmed advisor; knowledge entries added at runtime |

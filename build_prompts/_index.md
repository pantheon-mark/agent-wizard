# Build Prompts

This directory is empty at Build time. It is populated during wizard runtime.

At close, the wizard writes one file here: `phase_01_build_prompt.md`. This is the Phase-1 build-and-operate prompt, which brings the first phase's agents into operation under supervised conditions and walks the operator through acceptance.

Phases 2 and later are not pre-written by the wizard. They are driven by the next-phase skill in `wizard/skills/`, which the operator runs after each phase is accepted.

Per CLOSE-13 (the wizard closing orientation moment): the wizard explicitly tells the user this path so they can find the Phase-1 prompt here if they close the window before copying it.

This directory is the disk-first safety net for the wizard-produced Phase-1 build-and-operate prompt.

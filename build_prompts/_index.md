# Build Prompts

This directory is empty at Build time. It is populated during wizard runtime.

When the wizard produces a build prompt for each agent during the closing sequence, the prompt is written here immediately — before it is handed to the user. Files are named descriptively: `agent_01_build_prompt.md`, `agent_02_build_prompt.md`, etc.

Per CLOSE-13 (the wizard closing orientation moment): the wizard explicitly tells the user this path — "If you ever close this window before copying a prompt, open that folder and you'll find it."

This directory is the disk-first safety net for wizard-produced build prompts. A user should never lose a prompt because their session ended unexpectedly.

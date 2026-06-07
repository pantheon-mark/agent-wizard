"""Derivation-prompt loader (stdlib-only).

Loads a per-class derivation prompt (extraction / synthesis / classification / policy / auto)
or the agent-intent prompt from the wizard-distributed derivation-prompts directory, and stamps
it with a content-bound version hash. The derivation step records that hash in the field's audit
envelope (_prompt_version), so a change to a prompt surfaces as protocol drift (the derivation was
produced under a different prompt version) rather than slipping by silently.

Fail-closed: an unknown prompt name, a missing file, or an empty file is a hard error.

Stdlib-only, pip-install-free.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from derivation_replay import content_hash  # type: ignore

# The five derivation classes (mirror the derived-record contract enum) plus the agent-intent prompt.
PROMPT_NAMES = {"extraction", "synthesis", "classification", "policy", "auto", "authoring", "agent-intent"}


class DerivationPromptError(Exception):
    """Raised on an unknown prompt name or a missing/empty prompt file (fail-closed)."""


@dataclass(frozen=True)
class DerivationPrompt:
    name: str
    text: str
    prompt_version: str   # content_hash(text) — recorded into the derivation envelope as _prompt_version


def default_prompts_dir() -> Path:
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "derivation-prompts"


def load_derivation_prompt(name: str, prompts_dir: Optional[Path] = None) -> DerivationPrompt:
    """Load one prompt by name (e.g. 'policy', 'agent-intent'). prompt_version = content_hash(text)."""
    if name not in PROMPT_NAMES:
        raise DerivationPromptError(f"unknown prompt {name!r}; known: {sorted(PROMPT_NAMES)}")
    pdir = prompts_dir or default_prompts_dir()
    path = Path(pdir) / f"{name}.md"
    if not path.exists():
        raise DerivationPromptError(f"derivation prompt not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise DerivationPromptError(f"derivation prompt is empty: {path}")
    return DerivationPrompt(name=name, text=text, prompt_version=content_hash(text))


def load_all_prompts(prompts_dir: Optional[Path] = None) -> Dict[str, DerivationPrompt]:
    """Load every known prompt. Fails closed if any is missing/empty."""
    return {name: load_derivation_prompt(name, prompts_dir) for name in sorted(PROMPT_NAMES)}


def main() -> int:
    import sys
    pdir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        prompts = load_all_prompts(pdir)
    except DerivationPromptError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    for name in sorted(prompts):
        p = prompts[name]
        print(f"OK: {name:14s} {len(p.text):5d} chars  {p.prompt_version}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

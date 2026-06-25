"""Voice-settings derivation for the scaffold substitution map.

Derives the six voice keys (TONE / TECHNICAL_LEVEL / EXPLANATION_DEPTH /
LENGTH_PREFERENCE / LIST_STYLE / TABLE_STYLE) from `foundation_doc_inputs` and
returns them ready to inject via `**voice_settings_inputs(...)` into the
`scaffold_extra` dict.

Accepts two flavours of input:
  - Derived field names (live emit path, e.g. UP_TECHNICAL_LITERACY,
    NOTIFICATION_VERBOSITY, QA_REPORTING_STYLE) — what plan.foundation_doc_inputs
    carries at emit time.
  - Raw question IDs (UP-1, UP-4, ERR-1, QA-1) — the keys used in the brief's
    test skeleton; the function detects whichever flavour is present and reads from
    both so the function is useful in both test and live contexts.

Output values are drawn from the closed vocabulary in voice_and_style.md §4.2.
TONE is always "plain-and-direct" (project voice rule: never "warm").

Stdlib-only, pip-install-free.
"""

from typing import Dict


def voice_settings_inputs(inputs: Dict[str, str]) -> Dict[str, str]:
    """Derive the six voice keys from foundation_doc_inputs (or raw question IDs).

    Args:
        inputs: plan.foundation_doc_inputs or any dict containing voice-source keys.

    Returns:
        Dict with keys TONE, TECHNICAL_LEVEL, EXPLANATION_DEPTH,
        LENGTH_PREFERENCE, LIST_STYLE, TABLE_STYLE — all closed values.
    """
    # --- resolve source strings, preferring derived field names then raw IDs ---

    # TECHNICAL_LEVEL sources:
    #   derived: UP_TECHNICAL_LITERACY (scaffold field, set from UP-1 interview answer)
    #   raw:     UP-1 ("not technical" / "very technical" / "comfortable" / etc.)
    up_tech_raw = str(inputs.get("UP_TECHNICAL_LITERACY", inputs.get("UP-1", ""))).lower()

    # EXPLANATION_DEPTH sources:
    #   derived: NOTIFICATION_VERBOSITY ("Minimal"/"Standard"/"Detailed")
    #   raw:     ERR-1 ("quiet"/"standard"/"detailed") + UP-4 (verbosity preference)
    verbosity = str(inputs.get("NOTIFICATION_VERBOSITY", inputs.get("ERR-1", ""))).lower()
    up4 = str(inputs.get("UP-4", "")).lower()

    # LENGTH_PREFERENCE sources:
    #   derived: QA_REPORTING_STYLE ("summary"/"detailed")
    #   raw:     QA-1 ("concise"/"summary"/"detailed") + UP-4
    qa_style = str(inputs.get("QA_REPORTING_STYLE", inputs.get("QA-1", ""))).lower()

    # --- TECHNICAL_LEVEL ---
    if "not tech" in up_tech_raw or "non-tech" in up_tech_raw or "plain" in up_tech_raw:
        technical = "plain"
    elif (
        "very" in up_tech_raw
        or "comfortable" in up_tech_raw
        or "technical" in up_tech_raw
    ):
        technical = "technical"
    else:
        technical = "some-technical"

    # --- EXPLANATION_DEPTH ---
    if "minimal" in verbosity or "quiet" in verbosity or "brief" in up4:
        depth = "brief"
    elif "detailed" in verbosity or "detail" in up4:
        depth = "detailed"
    else:
        depth = "standard"

    # --- LENGTH_PREFERENCE ---
    # Closed vocabulary is concise / standard (no "detailed" length value), so a
    # detailed/live reporting style maps to standard like the default — the two are
    # folded into one else branch (M-1: the prior explicit "detailed"->"standard"
    # branch was dead, identical to the else).
    if "summary" in qa_style or "concise" in qa_style or "brief" in up4:
        length = "concise"
    else:
        length = "standard"

    return {
        "TONE": "plain-and-direct",           # project voice rule: never "warm"
        "TECHNICAL_LEVEL": technical,
        "EXPLANATION_DEPTH": depth,
        "LENGTH_PREFERENCE": length,
        "LIST_STYLE": "bullets",
        "TABLE_STYLE": "tables-when-comparing",
    }

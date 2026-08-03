"""FIXTURE (synthetic): the disclosed residual of the baked-consent rule.

Every confirmation below reaches the acceptance command as something other than
a string literal sitting next to the flag -- a variable, an f-string, a join.
An AST literal check cannot see through any of them, so NONE of these is
flagged. This fixture exists so that limit is asserted as a fact rather than
only described in a docstring: the rule is anti-drift, not a consent oracle.
"""

import subprocess

_WORDS = "yes, accept it"


def from_a_variable(confirmation):
    subprocess.run(
        [
            "python3",
            "agents/lib/external_write/operator_acceptance.py",
            "--capability-id",
            "inbox-tidy",
            "--operator-confirmation",
            confirmation,
        ],
        check=True,
    )


def from_a_module_constant():
    subprocess.run(
        [
            "python3",
            "agents/lib/external_write/operator_acceptance.py",
            "--capability-id",
            "inbox-tidy",
            "--operator-confirmation",
            _WORDS,
        ],
        check=True,
    )


def from_an_fstring(name):
    subprocess.run(
        [
            "python3",
            "agents/lib/external_write/operator_acceptance.py",
            "--capability-id",
            "inbox-tidy",
            "--operator-confirmation",
            f"yes, accept {name}",
        ],
        check=True,
    )


def from_a_join():
    subprocess.run(
        [
            "python3",
            "agents/lib/external_write/operator_acceptance.py",
            "--capability-id",
            "inbox-tidy",
            "--operator-confirmation",
            " ".join(["yes,", "accept", "it"]),
        ],
        check=True,
    )

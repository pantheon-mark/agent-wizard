"""FIXTURE (synthetic): the LITERAL escapes from the baked-consent rule.

Nothing here is computed. Every character of both confirmations below is written
into the source, and both reach the acceptance command carrying words no person
said -- yet neither is a list or tuple the rule inspects, so neither is flagged.

That is the half of the ceiling that is easiest to misread: the rule's other
disclosed escapes are all COMPUTED, which invites the inference that anything
literal is caught. It is not. A shell string and a mapping are literal and still
escape, and this fixture exists so that is an asserted fact.

Everything below is invented for this fixture.
"""

import subprocess

_OPTIONS = {
    "--capability-id": "inbox-tidy",
    "--operator-confirmation": "yes, accept it",
}


def from_a_shell_string():
    subprocess.run(
        "python3 agents/lib/external_write/operator_acceptance.py "
        "--capability-id inbox-tidy "
        "--operator-confirmation 'yes, accept it'",
        shell=True,
        check=True,
    )


def from_a_mapping():
    argv = ["python3", "agents/lib/external_write/operator_acceptance.py"]
    for flag, value in _OPTIONS.items():
        argv.append(flag)
        argv.append(value)
    subprocess.run(argv, check=True)

# Session State

CLEAR

<!--
This file records the current in-progress task state for this system.

"CLEAR" means no task is in progress. When a task is underway, this file holds
what was in progress, what has completed, and what remains — so a new session
can resume cleanly after an interruption.

Session-close enforcement: this file is updated first at every session close,
before session_bootstrap.md, the work queue, and the session log. State
persistence takes priority over any in-progress task. This sequence runs even
when a session is ending because of a problem.
-->

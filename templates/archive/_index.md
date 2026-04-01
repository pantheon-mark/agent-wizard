# Templates — Archive Directory

Templates for initial archive files in the user's System `/archive/` directory. All archive files start empty at setup — they receive entries moved from active files at runtime.

## Files in this directory

| Template file | Generates | Receives entries from |
|--------------|-----------|----------------------|
| `decisions_archive.md` | `/archive/decisions_archive.md` | `pending_decisions.md` on resolution |
| `work_archive.md` | `/archive/work_archive.md` | `/work/work_queue.md` on item completion |
| `review_queue_archive.md` | `/archive/review_queue_archive.md` | `/quality/human_review_queue.md` on resolution |
| `notification_archive.md` | `/archive/notification_archive.md` | `/logs/notification_log.md` daily (alerts older than 7-day rolling window) |

Runtime-only archive subdirectories (no templates — wizard creates empty directories):
- `/archive/advisor-guides/` — completed interview guides archived after consultation
- `/archive/logs/` — rotated log files archived at size threshold

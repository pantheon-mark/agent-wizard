# Source Registry

*Record of all external dependencies — data sources, APIs, and integrations. Every external dependency this system relies on is registered here with its expected behavior and current health status.*

*Pre-populated during wizard setup (QA-3) with confirmed sources. Updated when sources are added, changed, or resolved from stubs.*

---

| Source name | Type | Purpose | What stops without it | Expected behavior | Status | Last verified | Health flag |
|------------|------|---------|----------------------|------------------|--------|--------------|------------|

*Sources are confirmed and added here during wizard setup (QA-3).*

---

## Source types

| Type | Description |
|------|------------|
| API | External API endpoint |
| Web scraper | Website scraped for data |
| File export | File exported from an external tool (CSV, JSON, etc.) |
| Database | Direct database connection |
| Email | Email inbox monitored for inputs |
| Webhook | Inbound webhook from an external service |
| Manual upload | Files or data provided manually by the user |

## Health flag values

| Flag | Meaning |
|------|---------|
| Healthy | Operating normally |
| Degraded | Returning unexpected responses — investigation in progress |
| Broken | Not returning data — agents relying on this source are affected |
| Quarantined | Temporarily suspended pending investigation |
| Pending | Identified but not yet confirmed or configured |

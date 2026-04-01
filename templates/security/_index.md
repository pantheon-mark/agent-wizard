# Templates — Security Directory

Templates for files in the user's System `/security/` directory.

## Files in this directory

| Template file | Generates | Notes |
|--------------|-----------|-------|
| `credentials_registry.md` | `/security/credentials_registry.md` | Header and structure only at setup; rows added during CRED-2 for each confirmed credential |
| `gitignore_manifest.md` | `/security/gitignore_manifest.md` | Pre-populated with the baseline .gitignore entries written at project init |

`/security/session_cookies/` is a runtime directory — created by wizard at setup, populated by agents at runtime. No template file needed.

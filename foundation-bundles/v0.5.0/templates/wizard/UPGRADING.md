# Upgrading this system's foundation

This system was set up from foundation bundle **v0.4.0**. The wizard
can tell you when a newer bundle is available and what would change.

## Checking for updates

Ask the wizard to run an upgrade check against this project. It reports the
available versions, what would change, and whether any files you have edited
would be affected — without changing anything.

```
wizard upgrade-check
```

To preview the plan for a specific version:

```
wizard upgrade-plan --to <version>
```

## Applying updates

When you are ready to apply an update, run the apply command for a specific
version. This only ever changes the foundation documents (vision, approach,
technical architecture, execution plan, test cases, audit framework). It never
runs on its own: you have to ask for it each time.

```
wizard upgrade --to <version> --apply
```

Before it changes anything, the wizard makes a backup of your files. Any file you
have edited yourself is kept exactly as-is; the new version of that file is saved
next to it in a review folder (`.wizard/upgrade-review/`) so you can open it, see
what changed, and copy over anything you want by hand. Nothing in the review folder
is applied automatically.

If you have edited a file that the wizard would normally just replace, it stops and
asks you to confirm. Re-run the same command with `--ack` added to tell it you are
okay replacing your edited version (your old version is still backed up first):

```
wizard upgrade --to <version> --apply --ack
```

To preview an update without changing anything, use `--plan-only` instead of
`--apply` (or the `wizard upgrade-plan` command shown above).

## What the wizard tracks

`.wizard/manifest.json` records every file this system was set up with and its
content fingerprint, so the wizard can tell which files you have customized and
protect those edits during an upgrade. `.wizard/upgrade-policy.yaml` holds your
upgrade preferences. `.wizard/upgrade-history.log` records upgrades over time.

# Upstream synchronization log

This document tracks how we synchronize this Linux-only fork with the upstream `zcop/agy-cli-manager` project. It records which upstream commits we selectively port and which ones we deliberately reject to protect our OS Keyring isolation.

## v0.2.2 (11 Commits)

Upstream's v0.2.2 release adds concurrency fixes that override the `$HOME` environment variable. On Linux, `agy` uses D-Bus to communicate with the Global OS Keyring. D-Bus ignores `$HOME`. We rejected those specific commits because they would allow background tasks to silently overwrite the active terminal session's token. We maintain our own isolation using `_isolated_keyring_warmup` and process blocking.

**Rejected commits (isolation breakage):**
* `bf7eca9` Isolate interactive login from the active live account
* `4792f56` Isolate quota refresh to its selected account profile
* `6876c2a` Probe named accounts in their own home directories

**Ported commits (features & bug fixes):**
* `c17d519` Reject unsafe account profile paths. We added path validation to `account_dir`.
* `2113d3e` Make manager state writes atomic and status read only. We added `tempfile.mkstemp` to `save_state`.
* `bf7eca9` Isolate interactive login from the active live account. We rejected the `$HOME` override, but we ported the temporary staging directory concept and wrapped it securely in our keyring backup logic.
* `22336f1` Allow immediate quota failover in a new agy session. We ported this logic to allow `dedupe_seconds=0` for new sessions.
* `5909c9a` Skip unusable standby accounts during failover. We ported the fix to return `None` when no ranked candidates exist.
* `d9eb139` Preserve explicit disabled live directory setting. We ported the fix in `load_state` so it does not overwrite a disabled `live_dir`.

**Ignored / Meta commits:**
* `aa0410e` Prepare v0.2.2 release (Upstream version bump)
* `f9f351c` Document account manager fixes in changelog (Upstream changelog update)
* `72ea6f4` Point Pages install guide to safe v0.2.1 release (Upstream documentation update)

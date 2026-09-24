# Upstream synchronization log

This document tracks how we synchronize this Linux-only fork with the upstream `zcop/agy-cli-manager` project. It records which upstream commits we selectively port and which ones we deliberately reject to protect our OS Keyring isolation.

## v0.2.2

Upstream's v0.2.2 release adds concurrency fixes that override the `$HOME` environment variable. On Linux, `agy` uses D-Bus to communicate with the Global OS Keyring. D-Bus ignores `$HOME`. We rejected those specific commits because they would allow background tasks to silently overwrite the active terminal session's token. We maintain our own isolation using `_isolated_keyring_warmup` and process blocking.

**Rejected commits (isolation breakage):**
* `bf7eca9` Isolate interactive login from the active live account
* `4792f56` Isolate quota refresh to its selected account profile
* `6876c2a` Probe named accounts in their own home directories

**Ported commits:**
* `c17d519` Reject unsafe account profile paths. We added path validation to `account_dir`.
* `2113d3e` Make manager state writes atomic and status read only. We added `tempfile.mkstemp` to `save_state`.
* `bf7eca9` Isolate interactive login from the active live account. We rejected the `$HOME` override, but we ported the temporary staging directory concept and wrapped it securely in our keyring backup logic.

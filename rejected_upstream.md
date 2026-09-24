# Rejected Upstream Commits

We track commits merged in the upstream `zcop/agy-cli-manager` project that we deliberately reject in this Linux-only fork.

## v0.2.2

We rejected upstream's concurrency and isolation fixes. Upstream targets Windows and macOS, where `agy` stores OAuth tokens in flat files. Their fix overrides the `$HOME` environment variable to run background tasks without touching the active profile.

On Linux, `agy` uses D-Bus to communicate with the Global OS Keyring. D-Bus ignores `$HOME`. If we merged these commits, background tasks would silently overwrite the active terminal session's token in the keyring.

We maintain our own isolation using `_isolated_keyring_warmup` and process blocking.

**Rejected commits:**
* `bf7eca9` Isolate interactive login from the active live account
* `4792f56` Isolate quota refresh to its selected account profile
* `6876c2a` Probe named accounts in their own home directories

We manually cherry-picked the path validation and atomic state writes from this release.

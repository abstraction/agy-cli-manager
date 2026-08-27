# Developer Notes: State Isolation Fixes

## Problem Statement
The CLI manager worked locally for file-based routing but broke under concurrent background updates or interrupted interactive commands. The core issue was leaky state management surrounding the OS Keyring.

## Implemented Fixes
1. **The Silent Keyring Assassin**: 
   - *Bug*: Background cron jobs running `refresh_account_usage` on a standby account would extract the token, sync it to the OS Keyring, run `agy` to warm it up, but never restore the original token. This would cause the user's active session to randomly break or switch accounts.
   - *Fix*: Introduced the `_isolated_keyring_warmup` context manager in `manager.py`. It backs up the active keyring state, yields to the warmup process, and then restores the keyring.

2. **The Login Black Hole**: 
   - *Bug*: The `login_account` function wiped `~/.gemini` (the `live_dir`) to force `agy` to spawn a clean browser login flow. However, if the user hit `Ctrl-C` (or if it was a standby login), the script exited without restoring the active account, leaving the CLI completely unauthenticated.
   - *Fix*: Wrapped the destructive login process in a strict `try...finally` block. Upon any exit (success, failure, interrupt), it checks if there is an active account and immediately invokes `_copy_active_runtime` and `_sync_runtime_to_live_dir` to restore the environment.

## Design Validations
- Verified that `agy` 1.1.22 requires the Keyring and does not fallback to `antigravity-oauth-token` in `~/.gemini/` anymore.
- Verified that `list_models` and `probe_profile_identity_via_usage` already correctly isolate the global state.
- Created `tests/test_keyring_isolation.py` to assert the behavior of the new context manager.

## Next Steps
- Monitor if any future Antigravity CLI updates introduce alternative authentication locations.

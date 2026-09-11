# Agent Guide to `agy-cli-manager`

## 1. Architectural Overview
This project (`agy-cli-manager`) is a multi-account failover manager for the Antigravity CLI (`agy`). It solves the problem of rotating quotas by keeping isolated profile directories in `~/.agy-cli-manager/accounts/<name>` and syncing one active account into the real `~/.gemini` (the `live_dir`).

## 2. The Core Gotcha: Global OS Keyring
The most critical thing to understand when modifying this codebase is that `agy` on Linux stores its OAuth tokens in the **Global OS Keyring** (via the FreeDesktop Secret Service API / `secret-tool` under `service=gemini` and `username=antigravity`).

Because `agy-cli-manager` supports background operations (like checking quota on standby accounts) and multi-account storage, it heavily relies on swapping tokens in and out of the global keyring.
- **Rule:** If you invoke `agy` programmatically to operate on a *standby* account (e.g., via `subprocess`), you MUST protect the global keyring.
- **Enforcement:** Always use the `_isolated_keyring_warmup` context manager or the manual backup/restore pattern (seen in `list_models`) to ensure you do not overwrite the user's active session token.

## 3. Important Functions
- `login_account`: Wipes `live_dir` entirely to force a clean browser login flow. Crucially, it's wrapped in a `try...finally` block that guarantees the previous active account is restored even if the login times out or is aborted via `Ctrl-C`.
- `refresh_account_usage`: Runs background `agy` tasks to refresh tokens. Wrapped in the `_isolated_keyring_warmup` block to avoid global state pollution.
- `apply_active`: The central function for pushing a selected profile (from `runtime/`) into the live system state (`live_dir` and the global keyring).

## 4. Testing
Tests are located in `tests/`.
You can run them via:
```bash
python3 -m unittest discover -s tests
```

## 5. Development and Installation
If `agy-cli-manager` is installed globally via `uv tool install .`, changes to the local `src/` directory will **not** be immediately reflected because the source is copied to `uv`'s isolated `site-packages`. 
To ensure that local code changes take effect immediately without needing to reinstall, use the editable flag (`-e`):
```bash
uv tool install -e . --force
```
Once installed as editable, you do not need to rerun the install command when you modify `.py` files, as they are symlinked/referenced directly. Reinstallation is only required if you change dependencies or entry points in `pyproject.toml`.

## 6. Logging
- A rolling log of critical manager actions (account switches, failovers, marking accounts bad, etc.) is kept for 7 days.
- **Location:** The log file is located at `~/.agy-cli-manager/logs/manager.log`.

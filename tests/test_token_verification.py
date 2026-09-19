from __future__ import annotations

import base64
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from agy_cli_manager.manager import (
    account_dir,
    build_paths,
    check_token_account_match,
    detect_profile_identity,
    ensure_layout,
    load_state,
    login_account,
    refresh_account_usage,
    save_state,
    verify_account,
    _identity_from_antigravity_token,
)
from agy_cli_manager.cli import (
    DEFAULT_SORT_MODE,
    SORT_MODES,
    _format_countdown,
    _format_natural_duration,
    _format_reset_compact,
    _format_window_summary,
)


def _make_jwt(email: str, sub: str = "123456789", name: str = "Test User") -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({
            "email": email,
            "sub": sub,
            "name": name,
            "email_verified": True,
        }).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def _make_account_with_token(paths, name: str, email: str, expected_email: str | None = None) -> None:
    acct = account_dir(paths, name)
    token_path = acct / ".gemini" / "antigravity-cli"
    token_path.mkdir(parents=True, exist_ok=True)
    token_data = {
        "token": {
            "access_token": "ya29.fake",
            "token_type": "Bearer",
            "refresh_token": "1//fake",
            "expiry": "2030-01-01T00:00:00Z",
        },
        "auth_method": "oauth",
        "id_token": _make_jwt(email),
    }
    (token_path / "antigravity-oauth-token").write_text(json.dumps(token_data), encoding="utf-8")

    state = load_state(paths)
    meta = {
        "enabled": True,
        "status": "standby",
        "expected_email": expected_email or email,
        "identity": {
            "account_name": email,
            "email": email,
            "source": "antigravity-oauth-token.id_token",
        },
    }
    state["accounts"][name] = meta
    save_state(paths, state)


class TokenIdentityExtractionTests(unittest.TestCase):
    def test_extracts_from_top_level_id_token(self) -> None:
        jwt_token = _make_jwt("user@example.com", name="Jane Doe", sub="sub-999")
        token_state = {
            "token": {
                "access_token": "ya29.fake",
                "refresh_token": "1//fake",
            },
            "auth_method": "oauth",
            "id_token": jwt_token,
        }
        identity = _identity_from_antigravity_token(token_state)
        self.assertIsNotNone(identity)
        self.assertEqual(identity["email"], "user@example.com")
        self.assertEqual(identity["account_name"], "user@example.com")
        self.assertEqual(identity["display_name"], "Jane Doe")
        self.assertEqual(identity["subject"], "sub-999")
        self.assertEqual(identity["source"], "antigravity-oauth-token.id_token")

    def test_extracts_from_nested_token_id_token(self) -> None:
        jwt_token = _make_jwt("nested@example.com")
        token_state = {
            "token": {
                "access_token": "ya29.fake",
                "id_token": jwt_token,
            },
        }
        identity = _identity_from_antigravity_token(token_state)
        self.assertIsNotNone(identity)
        self.assertEqual(identity["email"], "nested@example.com")


class TokenAccountMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.paths = build_paths(Path(self._tmp))
        ensure_layout(self.paths)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_matching_token_returns_ok(self) -> None:
        _make_account_with_token(self.paths, "acc1", "acc1@gmail.com")
        source = account_dir(self.paths, "acc1")
        result = check_token_account_match(self.paths, "acc1", source)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.token_email, "acc1@gmail.com")

    def test_mismatched_token_returns_mismatch(self) -> None:
        _make_account_with_token(self.paths, "acc1", "wrong@gmail.com", expected_email="acc1@gmail.com")
        source = account_dir(self.paths, "acc1")
        result = check_token_account_match(self.paths, "acc1", source)
        self.assertEqual(result.status, "mismatch")
        self.assertEqual(result.token_email, "wrong@gmail.com")
        self.assertEqual(result.expected_email, "acc1@gmail.com")
        self.assertIn("Token mismatch", result.message)

    def test_duplicate_token_across_accounts_detected(self) -> None:
        _make_account_with_token(self.paths, "acc1", "shared@gmail.com")
        _make_account_with_token(self.paths, "acc2", "shared@gmail.com", expected_email="acc2@gmail.com")
        source = account_dir(self.paths, "acc2")
        result = check_token_account_match(self.paths, "acc2", source)
        # acc2 has expected acc2@gmail.com but token is shared@gmail.com -> mismatch or duplicate
        self.assertIn(result.status, {"mismatch", "duplicate"})

    def test_duplicate_token_when_no_expected_email(self) -> None:
        _make_account_with_token(self.paths, "acc1", "shared@gmail.com")
        # acc2 has token shared@gmail.com with no distinct expected email set
        acct2 = account_dir(self.paths, "acc2")
        token_path = acct2 / ".gemini" / "antigravity-cli"
        token_path.mkdir(parents=True, exist_ok=True)
        (token_path / "antigravity-oauth-token").write_text(
            json.dumps({"token": {"access_token": "fake"}, "id_token": _make_jwt("shared@gmail.com")}),
            encoding="utf-8",
        )
        state = load_state(self.paths)
        state["accounts"]["acc2"] = {"enabled": True, "status": "standby"}
        save_state(self.paths, state)

        result = check_token_account_match(self.paths, "acc2", acct2)
        self.assertEqual(result.status, "duplicate")
        self.assertEqual(result.colliding_account, "acc1")


class RefreshUsageAbortOnMismatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.paths = build_paths(Path(self._tmp))
        ensure_layout(self.paths)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch("agy_cli_manager.manager._cloudcode_request")
    def test_aborts_before_api_calls_on_mismatch(self, mock_cloudcode) -> None:
        _make_account_with_token(self.paths, "acc1", "wrong@gmail.com", expected_email="acc1@gmail.com")
        with self.assertRaises(ValueError) as ctx:
            refresh_account_usage(self.paths, "acc1")
        self.assertIn("Token mismatch", str(ctx.exception))
        mock_cloudcode.assert_not_called()

        state = load_state(self.paths)
        self.assertEqual(state["accounts"]["acc1"]["health_status"], "token_mismatch")
        self.assertIn("Token mismatch", state["accounts"]["acc1"]["last_live_check_error"])


class VerifyAccountTokenChecksTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.paths = build_paths(Path(self._tmp))
        ensure_layout(self.paths)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_verify_flags_token_mismatch(self) -> None:
        _make_account_with_token(self.paths, "acc1", "wrong@gmail.com", expected_email="acc1@gmail.com")
        state = load_state(self.paths)
        meta = state["accounts"]["acc1"]
        result = verify_account(self.paths, "acc1", meta)
        self.assertEqual(result["problem_status"], "token_mismatch")
        self.assertEqual(result["recommended_action"], "relogin")
        self.assertIn("Token mismatch", result["summary"])


class LoginAccountConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.paths = build_paths(Path(self._tmp))
        ensure_layout(self.paths)
        self.live_dir = self.paths.root / ".gemini"
        state = load_state(self.paths)
        state["live_dir"] = str(self.live_dir.resolve())
        save_state(self.paths, state)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch("os.isatty", return_value=True)
    @patch("subprocess.Popen")
    @patch("builtins.input", return_value="n")
    def test_login_declined_aborts_without_saving(self, mock_input, mock_popen, mock_isatty) -> None:
        def write_token():
            token_dir = self.live_dir / "antigravity-cli"
            token_dir.mkdir(parents=True, exist_ok=True)
            (token_dir / "antigravity-oauth-token").write_text(
                json.dumps({"token": {"access_token": "ya29.test"}, "id_token": _make_jwt("test@gmail.com")}),
                encoding="utf-8",
            )
            return 0

        proc = MagicMock()
        proc.poll.side_effect = write_token
        proc.returncode = 0
        mock_popen.return_value = proc

        saved = login_account(self.paths, "new_acc", agy_binary="/fake/agy")
        self.assertIsNone(saved)
        self.assertFalse(account_dir(self.paths, "new_acc").exists())

    @patch("os.isatty", return_value=True)
    @patch("subprocess.Popen")
    @patch("builtins.input", side_effect=["y", "y"])
    def test_login_confirmed_saves_account_and_expected_email(self, mock_input, mock_popen, mock_isatty) -> None:
        def write_token():
            token_dir = self.live_dir / "antigravity-cli"
            token_dir.mkdir(parents=True, exist_ok=True)
            (token_dir / "antigravity-oauth-token").write_text(
                json.dumps({"token": {"access_token": "ya29.test"}, "id_token": _make_jwt("confirmed@gmail.com")}),
                encoding="utf-8",
            )
            return 0

        proc = MagicMock()
        proc.poll.side_effect = write_token
        proc.returncode = 0
        mock_popen.return_value = proc

        saved = login_account(self.paths, "new_acc", agy_binary="/fake/agy")
        self.assertEqual(saved, "new_acc")
        self.assertTrue(account_dir(self.paths, "new_acc").exists())
        state = load_state(self.paths)
        self.assertEqual(state["accounts"]["new_acc"]["expected_email"], "confirmed@gmail.com")


class DashboardFormattingAndSortTests(unittest.TestCase):
    def test_default_sort_is_usage_low(self) -> None:
        self.assertEqual(DEFAULT_SORT_MODE, "usage-low")
        mode_keys = [mode[0] for mode in SORT_MODES]
        self.assertIn("usage-low", mode_keys)

    def test_natural_duration_formatting(self) -> None:
        # Multi-day
        self.assertEqual(_format_natural_duration(86400 * 6 + 3600 * 0 + 60 * 50), "6d 0h 50m")
        self.assertEqual(_format_natural_duration(86400 * 1 + 3600 * 10 + 60 * 20), "1d 10h 20m")
        # Hours
        self.assertEqual(_format_natural_duration(3600 * 4 + 60 * 15), "4h 15m")
        # Minutes and seconds
        self.assertEqual(_format_natural_duration(60 * 23 + 56), "23m 56s")
        # Sub-minute
        self.assertEqual(_format_natural_duration(45), "45s")
        self.assertEqual(_format_natural_duration(0), "due")

    def test_compact_reset_formatting(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # 6 days away
        win_weekly = {"reset_at": "2026-01-07T12:00:00+00:00"}
        self.assertEqual(_format_reset_compact(win_weekly, now), "6d")
        # 23 minutes away
        win_short = {"reset_at": "2026-01-01T12:23:00+00:00"}
        self.assertEqual(_format_reset_compact(win_short, now), "23m")
        # 4 hours away
        win_hours = {"reset_at": "2026-01-01T16:00:00+00:00"}
        self.assertEqual(_format_reset_compact(win_hours, now), "4h")

    def test_format_countdown_shows_sw_for_both_models(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        meta = {
            "usage_windows": {
                "gemini_short": {"value": 10.0, "status": "ok", "reset_at": "2026-01-01T12:23:00+00:00"},
                "gemini_weekly": {"value": 50.0, "status": "ok", "reset_at": "2026-01-07T12:00:00+00:00"},
                "claude_short": {"value": 20.0, "status": "ok", "reset_at": "2026-01-01T12:12:00+00:00"},
                "claude_weekly": {"value": 60.0, "status": "ok", "reset_at": "2026-01-06T12:00:00+00:00"},
            }
        }
        res = _format_countdown(meta, now)
        self.assertEqual(res, "G:23m/6d C:12m/5d")

    def test_window_summary_uses_natural_duration(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        meta = {
            "usage_windows": {
                "gemini_weekly": {"value": 100.0, "status": "ok", "reset_at": "2026-01-07T12:50:00+00:00"}
            }
        }
        summary = _format_window_summary(meta, "gemini_weekly", now)
        self.assertEqual(summary, "100% (in 6d 0h 50m)")

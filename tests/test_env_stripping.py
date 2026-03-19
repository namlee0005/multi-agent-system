"""
Task 7.1 — Audit CLAUDECODE environment stripping.

Asserts that every subprocess.run() call site in the MAS never passes
CLAUDECODE in the env dict, regardless of whether it is present in
os.environ at call time.

Call sites covered:
  - backends/cli_session.py :: CLISession._get_env()
  - backends/cli_session.py :: CLISession.call()  (integration path)

Run with: python -m unittest tests/test_env_stripping.py -v
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Allow import from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backends.cli_session import CLISession
from backends.session_store import SessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(backend: str = "claude") -> CLISession:
    store = MagicMock(spec=SessionStore)
    store.get.return_value = None  # stateless first call
    return CLISession(
        backend=backend,
        agent_name="TestAgent",
        project_path="/tmp/test_project",
        command="claude",
        model="claude-sonnet-4-6",
        session_store=store,
    )


def _mock_successful_run() -> MagicMock:
    result = SimpleNamespace(
        returncode=0,
        stdout='{"result": "ok", "session_id": "abc-123"}',
        stderr="",
    )
    return MagicMock(return_value=result)


# ---------------------------------------------------------------------------
# Unit tests — _get_env()
# ---------------------------------------------------------------------------

class TestGetEnv(unittest.TestCase):
    """Direct unit tests for CLISession._get_env()."""

    def test_strips_claudecode_when_present(self):
        session = _make_session()
        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=False):
            env = session._get_env()
        self.assertNotIn(
            "CLAUDECODE", env,
            "_get_env() must remove CLAUDECODE even when it is set in os.environ",
        )

    def test_no_error_when_claudecode_absent(self):
        session = _make_session()
        env_without = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        with patch.dict(os.environ, env_without, clear=True):
            env = session._get_env()
        self.assertNotIn("CLAUDECODE", env)

    def test_other_env_vars_preserved(self):
        session = _make_session()
        with patch.dict(os.environ, {"CLAUDECODE": "1", "MY_VAR": "hello"}, clear=False):
            env = session._get_env()
        self.assertEqual(
            env.get("MY_VAR"), "hello",
            "_get_env() must not strip unrelated environment variables",
        )

    def test_returns_copy_not_os_environ(self):
        """Mutating the returned dict must not affect os.environ."""
        session = _make_session()
        env = session._get_env()
        env["__TEST_KEY__"] = "injected"
        self.assertNotIn("__TEST_KEY__", os.environ)

    # Parametric edge cases — expanded manually (no pytest dependency)
    def _assert_value_stripped(self, claudecode_value: str):
        session = _make_session()
        with patch.dict(os.environ, {"CLAUDECODE": claudecode_value}, clear=False):
            env = session._get_env()
        self.assertNotIn(
            "CLAUDECODE", env,
            f"CLAUDECODE={claudecode_value!r} was not stripped",
        )

    def test_strips_claudecode_value_1(self):
        self._assert_value_stripped("1")

    def test_strips_claudecode_value_empty(self):
        self._assert_value_stripped("")

    def test_strips_claudecode_value_true(self):
        self._assert_value_stripped("true")

    def test_strips_claudecode_value_yes(self):
        self._assert_value_stripped("yes")

    def test_strips_claudecode_value_claude_code(self):
        self._assert_value_stripped("claude-code")


# ---------------------------------------------------------------------------
# Integration tests — subprocess.run receives stripped env
# ---------------------------------------------------------------------------

class TestSubprocessEnvStripping(unittest.TestCase):
    """Assert CLAUDECODE never reaches subprocess.run(), even transitively."""

    def test_claudecode_absent_from_subprocess_call_when_set_in_environ(self):
        """
        CLAUDECODE is present in the process environment.
        subprocess.run() must be called with an env dict that lacks it.
        """
        session = _make_session()
        mock_run = _mock_successful_run()

        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=False):
            with patch("backends.cli_session.subprocess.run", mock_run):
                session.call("test prompt")

        self.assertTrue(mock_run.called, "subprocess.run should have been called")
        _, kwargs = mock_run.call_args
        env_passed = kwargs.get("env")
        self.assertIsNotNone(env_passed, "subprocess.run must receive an explicit env kwarg")
        self.assertNotIn(
            "CLAUDECODE", env_passed,
            "CLAUDECODE must be stripped before reaching subprocess.run()",
        )

    def test_claudecode_absent_from_subprocess_call_when_not_in_environ(self):
        """Baseline: CLAUDECODE absent in os.environ → also absent in subprocess env."""
        session = _make_session()
        mock_run = _mock_successful_run()

        env_without = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        with patch.dict(os.environ, env_without, clear=True):
            with patch("backends.cli_session.subprocess.run", mock_run):
                session.call("test prompt")

        _, kwargs = mock_run.call_args
        self.assertNotIn("CLAUDECODE", kwargs["env"])

    def test_retry_call_also_strips_claudecode(self):
        """
        When --resume fails (non-zero returncode) and call() recurses,
        the retry must also strip CLAUDECODE.
        """
        store = MagicMock(spec=SessionStore)
        store.get.return_value = "existing-session-id"  # triggers --resume path
        session = CLISession(
            backend="claude",
            agent_name="RetryAgent",
            project_path="/tmp/retry_project",
            command="claude",
            model="claude-sonnet-4-6",
            session_store=store,
        )

        failed_result = SimpleNamespace(returncode=1, stdout="", stderr="resume failed")
        success_result = SimpleNamespace(
            returncode=0,
            stdout='{"result": "ok", "session_id": "new-123"}',
            stderr="",
        )
        mock_run = MagicMock(side_effect=[failed_result, success_result])

        with patch.dict(os.environ, {"CLAUDECODE": "1"}, clear=False):
            with patch("backends.cli_session.subprocess.run", mock_run):
                session.call("test prompt")

        self.assertEqual(mock_run.call_count, 2, "Expected one retry after failed resume")
        for call_args in mock_run.call_args_list:
            _, kwargs = call_args
            env_passed = kwargs.get("env")
            self.assertIsNotNone(env_passed)
            self.assertNotIn(
                "CLAUDECODE", env_passed,
                "CLAUDECODE must be stripped on every subprocess.run() call, including retries",
            )


if __name__ == "__main__":
    unittest.main()
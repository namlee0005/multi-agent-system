"""
Phase 8 Regression Suite
========================
Tests: ContextStore thread-safety, CLISession JSON parsing + token extraction,
MASError exception hierarchy, BackendCallError raised by Agent.call_llm,
and Orchestrator.__init__ binary check (BinaryNotFoundError).

Run with: python -m pytest tests/regression_suite.py -v
"""

import json
import os
import sys
import threading
import unittest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch

# Ensure project root is on the path when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context_store import ContextStore
from exceptions import (
    BackendCallError,
    BinaryNotFoundError,
    CompressionError,
    MASError,
    PipelineError,
    ReviewError,
    SessionError,
    SessionResumeError,
    ValidationError,
)
from backends.session_store import CLICallResult, SessionStore
from backends.cli_session import CLISession


# ─── 1. Exception hierarchy ───────────────────────────────────────────────────

class TestExceptionHierarchy(unittest.TestCase):
    def test_all_are_mas_error(self):
        for cls in (
            BackendCallError,
            BinaryNotFoundError,
            SessionError,
            SessionResumeError,
            ValidationError,
            ReviewError,
            PipelineError,
            CompressionError,
        ):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, MASError))
                self.assertTrue(issubclass(cls, RuntimeError))

    def test_session_resume_error_is_session_error(self):
        self.assertTrue(issubclass(SessionResumeError, SessionError))

    def test_raise_and_catch_as_runtime_error(self):
        with self.assertRaises(RuntimeError):
            raise BackendCallError("backend died")

    def test_raise_and_catch_as_mas_error(self):
        with self.assertRaises(MASError):
            raise PipelineError("pipeline failed")


# ─── 2. ContextStore ─────────────────────────────────────────────────────────

class TestContextStore(unittest.TestCase):
    def test_set_and_get_scalar(self):
        ctx = ContextStore()
        ctx.set("project_description", "test project")
        self.assertEqual(ctx.get("project_description"), "test project")

    def test_get_missing_key_returns_default(self):
        ctx = ContextStore()
        self.assertIsNone(ctx.get("nonexistent"))
        self.assertEqual(ctx.get("nonexistent", "default"), "default")

    def test_append_to_list_bucket(self):
        ctx = ContextStore()
        ctx.append("proposals", {"agent": "Researcher", "text": "use postgres"})
        ctx.append("proposals", {"agent": "Architect", "text": "use redis"})
        self.assertEqual(len(ctx.get_list("proposals")), 2)

    def test_append_to_scalar_raises_type_error(self):
        ctx = ContextStore()
        ctx.set("scalar_key", "a string")
        with self.assertRaises(TypeError):
            ctx.append("scalar_key", "value")

    def test_snapshot_returns_copy(self):
        ctx = ContextStore()
        ctx.append("errors", {"msg": "fail"})
        snap = ctx.snapshot(keys=["errors"])
        snap["errors"].append({"msg": "injected"})
        # Original must be unaffected
        self.assertEqual(len(ctx.get_list("errors")), 1)

    def test_snapshot_filters_keys(self):
        ctx = ContextStore()
        ctx.set("a", 1)
        ctx.set("b", 2)
        snap = ctx.snapshot(keys=["a"])
        self.assertIn("a", snap)
        self.assertNotIn("b", snap)

    def test_thread_safety(self):
        ctx = ContextStore()
        errors = []

        def writer(i):
            try:
                for j in range(50):
                    ctx.append("proposals", {"agent": f"agent-{i}", "item": j})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertEqual(len(ctx.get_list("proposals")), 500)


# ─── 3. CLISession JSON parsing + token extraction ────────────────────────────

class TestCLISessionParsing(unittest.TestCase):
    def _make_session(self):
        store = SessionStore(storage_path="/tmp/test_mas_sessions.json")
        return CLISession(
            backend="claude",
            agent_name="TestAgent",
            project_path="/tmp",
            command="claude",
            model="claude-sonnet-4-6",
            session_store=store,
        )

    def _run_with_stdout(self, session, stdout: str, returncode: int = 0):
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = stdout
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            return session.call("test prompt")

    def test_parses_result_field(self):
        session = self._make_session()
        payload = json.dumps({
            "result": "Hello from Claude",
            "session_id": "abc-123",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
        result = self._run_with_stdout(session, payload)
        self.assertEqual(result.content, "Hello from Claude")
        self.assertEqual(result.session_id, "abc-123")

    def test_token_extraction_plain(self):
        session = self._make_session()
        payload = json.dumps({
            "result": "ok",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        })
        result = self._run_with_stdout(session, payload)
        self.assertEqual(result.input_tokens, 100)
        self.assertEqual(result.output_tokens, 50)

    def test_token_extraction_with_cache_fields(self):
        """Task 7.6: resumed sessions report tokens via cache fields."""
        session = self._make_session()
        payload = json.dumps({
            "result": "ok",
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 800,
                "cache_creation_input_tokens": 200,
                "output_tokens": 60,
            },
        })
        result = self._run_with_stdout(session, payload)
        self.assertEqual(result.input_tokens, 1010)  # 10 + 800 + 200
        self.assertEqual(result.output_tokens, 60)

    def test_non_json_stdout_falls_back_to_raw(self):
        session = self._make_session()
        result = self._run_with_stdout(session, "plain text response")
        self.assertEqual(result.content, "plain text response")
        self.assertIsNone(result.input_tokens)

    def test_nonzero_returncode_returns_error_result(self):
        session = self._make_session()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "command not found"
        # Disable retry by having stateless session
        with patch("subprocess.run", return_value=mock_result):
            result = session.call("test prompt")
        self.assertNotEqual(result.returncode, 0)


# ─── 4. BackendCallError raised by Agent.call_llm ────────────────────────────

class TestAgentBackendCallError(unittest.TestCase):
    def test_call_llm_raises_backend_call_error_on_nonzero(self):
        from agents import Agent
        from backends.session_store import SessionStore

        agent = Agent(
            name="TestAgent",
            role="test",
            system_prompt="You are a test agent.",
            backend="claude",
            model="claude-sonnet-4-6",
            session_store=SessionStore(storage_path="/tmp/test_mas_sessions.json"),
        )

        failing_result = CLICallResult(
            content="fatal error from CLI",
            returncode=1,
            duration_s=0.1,
        )

        with patch("backends.cli_session.CLISession.call", return_value=failing_result):
            with self.assertRaises(BackendCallError) as ctx:
                agent.call_llm("hello", {"claude": {"command": "claude"}})

        self.assertIn("exited 1", str(ctx.exception))
        self.assertIsInstance(ctx.exception, MASError)

    def test_call_llm_returns_content_on_success(self):
        from agents import Agent

        agent = Agent(
            name="TestAgent",
            role="test",
            system_prompt="You are a test agent.",
            backend="claude",
            model="claude-sonnet-4-6",
            session_store=SessionStore(storage_path="/tmp/test_mas_sessions.json"),
        )

        ok_result = CLICallResult(
            content="great response",
            returncode=0,
            duration_s=0.5,
            session_id="sess-xyz",
        )

        with patch("backends.cli_session.CLISession.call", return_value=ok_result):
            content = agent.call_llm("hello", {"claude": {"command": "claude"}})

        self.assertEqual(content, "great response")


# ─── 5. Orchestrator: BinaryNotFoundError at init ─────────────────────────────

class TestOrchestratorBinaryCheck(unittest.TestCase):
    def _minimal_config(self, command: str) -> dict:
        return {
            "backends": {"claude": {"command": command}},
            "debate": {"max_rounds": 2, "min_agents": 3, "max_agents": 5},
            "defaults": {"backend": "claude", "model": "claude-sonnet-4-6"},
        }

    def test_raises_binary_not_found_error_for_missing_command(self):
        from orchestrator import Orchestrator

        cfg = self._minimal_config("__nonexistent_binary_xyz__")
        with self.assertRaises(BinaryNotFoundError) as ctx:
            Orchestrator(cfg)
        self.assertIn("__nonexistent_binary_xyz__", str(ctx.exception))
        self.assertIsInstance(ctx.exception, MASError)

    def test_no_error_when_command_exists(self):
        from orchestrator import Orchestrator

        # 'true' exists on all POSIX systems
        cfg = self._minimal_config("true")
        # Also need a spec.md — patch open to avoid FileNotFoundError
        with patch("builtins.open", side_effect=FileNotFoundError):
            try:
                Orchestrator(cfg)
            except BinaryNotFoundError:
                self.fail("BinaryNotFoundError raised for existing command 'true'")
            except (FileNotFoundError, Exception):
                pass  # Expected — no spec.md in test environment


if __name__ == "__main__":
    unittest.main(verbosity=2)
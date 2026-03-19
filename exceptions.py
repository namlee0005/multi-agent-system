"""
Structured error taxonomy for the Multi-Agent System (Phase 8.1).

All MAS exceptions inherit from both MASError and RuntimeError so that
existing `except RuntimeError` catch sites are unaffected while callers
can narrow on specific error types as needed.
"""


class MASError(RuntimeError):
    """Base class for all MAS-specific errors."""


class BinaryNotFoundError(MASError):
    """Raised at Orchestrator.__init__ when a required CLI binary is missing."""


class SessionError(MASError):
    """Raised when a CLISession subprocess call fails."""


class SessionResumeError(SessionError):
    """Raised when --resume returns a non-zero exit code after one stateless retry."""


class BackendCallError(MASError):
    """Raised by Agent.call_llm when the LLM backend returns a non-zero exit code."""


class ValidationError(MASError):
    """Raised when an agent response exhausts all validation retry attempts."""


class ReviewError(MASError):
    """Raised when the CodeReviewer returns FAIL and retries are exhausted."""


class PipelineError(MASError):
    """Raised when more than 50% of agents in a debate round fail."""


class CompressionError(MASError):
    """Raised when the compression gate fails to produce any summaries."""
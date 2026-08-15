"""Error hierarchy for tr-cli.

Exit code mapping (stable contract for scripts):
  0 OK, 1 GENERIC, 2 USAGE, 3 NEEDS_LOGIN, 4 RATE_LIMITED, 5 LOGIN_FAILED, 6 PROTOCOL
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_NEEDS_LOGIN = 3
EXIT_RATE_LIMITED = 4
EXIT_LOGIN_FAILED = 5
EXIT_PROTOCOL = 6


class TrCliError(Exception):
    """Base class for all expected tr-cli failures."""

    exit_code = EXIT_GENERIC


class UsageError(TrCliError):
    exit_code = EXIT_USAGE


class NeedsLogin(TrCliError):
    """A saved session is required but missing/expired."""

    exit_code = EXIT_NEEDS_LOGIN


class RateLimited(TrCliError):
    """TR answered 429 TOO_MANY_REQUESTS; includes cooldown info when known."""

    exit_code = EXIT_RATE_LIMITED

    def __init__(
        self,
        message: str,
        *,
        wait_seconds: int | None = None,
        next_attempt_at: str | None = None,
    ):
        super().__init__(message)
        self.wait_seconds = wait_seconds
        self.next_attempt_at = next_attempt_at


class LoginFailed(TrCliError):
    """Credentials rejected or login process failed."""

    exit_code = EXIT_LOGIN_FAILED


class ApprovalTimeout(LoginFailed):
    """User never approved the login push in time."""


class ProtocolError(TrCliError):
    """Unexpected/undecodable data from TR (or the mock)."""

    exit_code = EXIT_PROTOCOL

"""Execution-layer error boundaries."""

from __future__ import annotations


class ExecutorError(Exception):
    """Base class for executor-layer failures."""


class UnknownActionError(ExecutorError):
    """Raised when a requested tool or skill is not registered."""


class SchemaValidationError(ExecutorError):
    """Raised when request parameters do not satisfy the declared schema."""


class PreconditionsFailedError(ExecutorError):
    """Raised when declared preconditions are not met."""


class RetryableExecutionError(ExecutorError):
    """Raised for operational failures that should be retried."""


class NonRetryableExecutionError(ExecutorError):
    """Raised for hard failures that should not be retried."""

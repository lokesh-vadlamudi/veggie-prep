"""Recoverable error types for the AI meal-suggestion provider.

Every failure that the UI can show the user derives from
:class:`AIProviderError`; the message is written to be safe to render
directly in a form banner (no secrets, no internal stack details).
No provider failure may leave a partial suggestion or any inventory
mutation behind — the generation service enforces that.
"""


class AIProviderError(Exception):
    """Base class for all AI provider failures (user-safe messages)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AIConfigError(AIProviderError):
    """The provider is disabled or misconfigured on the server."""


class AIRequestError(AIProviderError):
    """The HTTP request failed: timeout, HTTP error, or unreachable host."""


class AIMalformedOutputError(AIProviderError):
    """The provider responded, but the output was unusable: invalid JSON,
    missing structure, schema violations, unsupported units, or
    negative/non-finite/imprecise quantities."""


class AIOutputTooLargeError(AIProviderError):
    """The provider response exceeded the bounded size limit."""

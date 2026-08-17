"""AI provider package: interface, OpenAI-compatible implementation, and
validation.

``get_provider()`` is the single seam the generation service calls. It
builds a provider from the server-side environment and raises
:class:`AIConfigError` when the provider is disabled or misconfigured —
the one place tests patch to inject a deterministic fake.
"""

from .exceptions import (
    AIConfigError,
    AIMalformedOutputError,
    AIOutputTooLargeError,
    AIProviderError,
    AIRequestError,
)
from .openai import OpenAICompatibleProvider
from .schema import (
    IngredientProposal,
    MealProposal,
    validate_proposal,
)


def get_provider() -> OpenAICompatibleProvider:
    """Build the configured provider; raise ``AIConfigError`` if disabled."""
    return OpenAICompatibleProvider()


__all__ = [
    "AIConfigError",
    "AIMalformedOutputError",
    "AIOutputTooLargeError",
    "AIProviderError",
    "AIRequestError",
    "IngredientProposal",
    "MealProposal",
    "OpenAICompatibleProvider",
    "get_provider",
    "validate_proposal",
]

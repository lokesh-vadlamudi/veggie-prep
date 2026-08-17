"""OpenAI-compatible chat-completions provider.

Talks to ``{AI_BASE_URL}/chat/completions`` over plain HTTPS/HTTP using
only the standard library (``urllib``), so no network library is a
dependency. Configuration is read from the environment at provider
construction time:

* ``AI_BASE_URL``  (required) – provider base URL, e.g. a local vLLM
  endpoint. Empty/missing means the feature is disabled.
* ``AI_MODEL``     (required) – model identifier to request.
* ``AI_API_KEY``   (optional) – if set, sent as a ``Authorization: Bearer``
  header. Never logged, never stored, never echoed into error messages.
* ``AI_TIMEOUT``   (optional) – socket timeout in seconds; defaults to
  :data:`DEFAULT_TIMEOUT`, capped at :data:`MAX_TIMEOUT`.

Responses are read with a hard byte cap (:data:`MAX_RESPONSE_BYTES`) so an
oversized completion cannot exhaust memory. Every failure raises an
:class:`~inventory.ai.exceptions.AIProviderError` subclass with a
user-safe message.
"""

import json
import os
import socket
import urllib.error
import urllib.request

from .exceptions import (
    AIConfigError,
    AIMalformedOutputError,
    AIOutputTooLargeError,
    AIRequestError,
)

DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0
MAX_RESPONSE_BYTES = 256 * 1024

_SYSTEM_PROMPT = """\
You plan one dinner from the household's current pantry. Reply with a
single JSON object and nothing else (no markdown, no commentary).

Schema:
{
  "title": string,            # short dish name, <= 160 chars
  "servings": integer,
  "time_minutes": integer,    # total cook time, within the request's max
  "steps": [string],          # 1-15 imperative cooking steps
  "substitutions": [string],  # optional, <= 8 swap suggestions
  "safety_note": string,      # optional, short food-safety advice or ""
  "rationale": string,        # 1-3 plain sentences: why this meal, <= 400 chars
  "ingredients": [
    {"name": string, "unit": string, "quantity": number}
  ]
}

Rules:
- "unit" must be exactly one of: count, each, g, kg, ml, l.
- "quantity" is a positive number with at most 3 decimal places.
- Prefer ingredients that are present in the provided inventory, matching
  the inventory's exact product names and units; list each ingredient once.
- Prioritize using lots flagged "expiry_soon" (expiring within 2 days) and,
  only when they were explicitly included, lots flagged "expired".
- Respect the request's servings, max minutes, dietary exclusions, and
  preference when choosing the meal.
- Do not invent inventory; ingredients not in the pantry may be listed and
  will simply be reported as missing.
"""


class OpenAICompatibleProvider:
    """HTTP provider for any OpenAI-compatible chat-completions endpoint."""

    def __init__(self):
        self.base_url = (os.environ.get("AI_BASE_URL") or "").strip().rstrip("/")
        self.model = (os.environ.get("AI_MODEL") or "").strip()
        self.api_key = (os.environ.get("AI_API_KEY") or "").strip()
        if not self.base_url:
            raise AIConfigError(
                "AI meal suggestions are not configured: set AI_BASE_URL "
                "(and AI_MODEL) on the server, or ask me to suggest a meal "
                "when the provider is available."
            )
        if not self.model:
            raise AIConfigError(
                "AI meal suggestions are not configured: AI_MODEL is "
                "required when AI_BASE_URL is set."
            )
        raw_timeout = os.environ.get("AI_TIMEOUT")
        if raw_timeout is None or not str(raw_timeout).strip():
            self.timeout = DEFAULT_TIMEOUT
        else:
            try:
                self.timeout = float(str(raw_timeout).strip())
            except ValueError:
                raise AIConfigError(
                    "AI_TIMEOUT must be a number of seconds."
                ) from None
            if not (0 < self.timeout <= MAX_TIMEOUT):
                raise AIConfigError(
                    f"AI_TIMEOUT must be between 1 and {int(MAX_TIMEOUT)} "
                    f"seconds."
                )

    @property
    def model_name(self):
        """The model identifier, for recording on the suggestion."""
        return self.model

    def generate(self, snapshot, requirements) -> dict:
        """Call the provider; return the decoded JSON proposal object.

        ``snapshot`` is the structured inventory snapshot and
        ``requirements`` the user's constraints; both are serializable and
        contain no secrets. Raises :class:`AIProviderError` subclasses on
        every failure mode; never returns partial data.
        """
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"inventory": snapshot,
                             "requirements": requirements},
                            separators=(",", ":"),
                        ),
                    },
                ],
                "temperature": 0.3,
            },
            separators=(",", ":"),
        ).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"
        request = urllib.request.Request(
            url, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except socket.timeout as exc:
            raise AIRequestError(
                f"The AI request timed out after {self.timeout:g} seconds; "
                "your inventory was not changed."
            ) from exc
        except urllib.error.HTTPError as exc:
            raise AIRequestError(
                f"The AI provider returned HTTP {exc.code}; "
                "your inventory was not changed."
            ) from exc
        except urllib.error.URLError as exc:
            raise AIRequestError(
                f"Could not reach the AI provider ({exc.reason}); "
                "your inventory was not changed."
            ) from exc
        except OSError:
            raise AIRequestError(
                "The AI request failed; your inventory was not changed."
            ) from None

        if len(raw) > MAX_RESPONSE_BYTES:
            raise AIOutputTooLargeError(
                "The AI response was larger than the allowed size; the "
                "suggestion was discarded."
            )
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AIMalformedOutputError(
                "The AI response was not valid JSON; please try again."
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError) as exc:
            raise AIMalformedOutputError(
                "The AI response is missing the expected completion "
                "payload; please try again."
            ) from exc
        if not isinstance(content, str):
            raise AIMalformedOutputError(
                "The AI completion content must be a string; please try "
                "again."
            )
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIMalformedOutputError(
                "The AI completion was not valid JSON; please try again."
            ) from exc
        return payload

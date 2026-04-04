"""
Structured output inference helper.

Provides a generic retry loop that coerces an LLM's free-text reply into a
validated Pydantic model, without depending on any specific model or provider.
"""

import json
import logging
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Matches optional ```json … ``` or ``` … ``` fences.
_CODE_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\n?(.*?)\n?```\s*$",
    re.DOTALL,
)

_SCHEMA_INSTRUCTION = (
    "Respond with ONLY valid JSON matching this schema. No markdown wrapping."
)


def _strip_fences(text: str) -> str:
    """Remove optional ```json / ``` fences from the model's reply."""
    stripped = text.strip()
    m = _CODE_FENCE_RE.match(stripped)
    return m.group(1).strip() if m else stripped


def _schema_system_message(response_model: Type[BaseModel]) -> dict:
    schema_json = json.dumps(response_model.model_json_schema(), indent=2)
    content = f"{_SCHEMA_INSTRUCTION}\n\nJSON Schema:\n{schema_json}"
    return {"role": "system", "content": content}


async def request_structured_output(
    llm_client,
    messages: list[dict],
    response_model: Type[T],
    max_retries: int = 2,
    temperature: float = 0.0,
) -> T | None:
    """
    Call *llm_client* and coerce the reply into a validated *response_model*.

    A system message carrying the JSON schema is appended to *messages* before
    the first attempt.  On parse / validation failure the error is fed back as
    a user message and the loop retries up to *max_retries* additional times
    (i.e. at most ``max_retries + 1`` total attempts).

    Args:
        llm_client: Any client that exposes an async
            ``chat(messages, temperature) -> object`` method whose return value
            has a ``.content`` attribute containing the model's text reply.
        messages: Conversation history.  **Mutated in-place** during retries so
            that error feedback accumulates naturally.
        response_model: Pydantic model class the reply must conform to.
        max_retries: Number of *additional* attempts after the first failure.
        temperature: Sampling temperature forwarded to *llm_client*.

    Returns:
        A validated instance of *response_model*, or ``None`` if all attempts
        are exhausted.  Callers **must** handle the ``None`` case.
    """
    # Build a working copy so we don't permanently alter the caller's list,
    # but still let retry feedback accumulate within this call.
    working_messages = list(messages) + [_schema_system_message(response_model)]

    attempts = max_retries + 1

    for attempt in range(1, attempts + 1):
        logger.debug(
            "request_structured_output: attempt %d/%d for %s",
            attempt,
            attempts,
            response_model.__name__,
        )

        try:
            response = await llm_client.chat(
                working_messages, temperature=temperature
            )
            raw_text: str = response.content or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM call failed on attempt %d: %s", attempt, exc
            )
            if attempt <= max_retries:
                working_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"The previous request raised an error: {exc}. "
                            "Please try again and return only valid JSON."
                        ),
                    }
                )
            continue

        cleaned = _strip_fences(raw_text)

        try:
            data = json.loads(cleaned)
            validated = response_model.model_validate(data)
            logger.debug(
                "request_structured_output: success on attempt %d", attempt
            )
            return validated

        except json.JSONDecodeError as exc:
            feedback = (
                f"Your reply could not be parsed as JSON: {exc}. "
                f"Raw reply was:\n{raw_text}\n"
                "Please respond with ONLY valid JSON matching the schema."
            )
            logger.warning(
                "JSONDecodeError on attempt %d: %s", attempt, exc
            )

        except ValidationError as exc:
            feedback = (
                f"The JSON you returned did not match the required schema:\n"
                f"{exc}\n"
                "Please fix the issues and return only the corrected JSON."
            )
            logger.warning(
                "ValidationError on attempt %d: %s", attempt, exc
            )

        # Feed the error back so the model can self-correct on the next round.
        if attempt <= max_retries:
            working_messages.append({"role": "user", "content": feedback})

    logger.error(
        "request_structured_output: all %d attempt(s) exhausted for %s",
        attempts,
        response_model.__name__,
    )
    return None

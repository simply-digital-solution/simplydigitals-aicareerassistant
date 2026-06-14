import json
import re
from typing import TypeVar, Type, Optional
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# Status strings returned alongside the parsed result
STATUS_VALID = "valid_json"
STATUS_EXTRACTED = "extracted_json"
STATUS_FAILED = "failed"


def _try_parse(raw: str, schema: Type[T]) -> tuple[Optional[T], Optional[str]]:
    """Single parse attempt. Returns (model, None) on success or (None, error_str) on failure."""
    try:
        data = json.loads(raw.strip())
        return schema.model_validate(data), None
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {e}"
    except ValidationError as e:
        return None, f"Schema validation error: {e}"


def _extract_json_block(text: str) -> Optional[str]:
    """Try to find a JSON block inside ```json ... ``` or the first { ... } block."""
    # Fenced code block
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        return m.group(1).strip()
    # Bare JSON object or array
    m = re.search(r"(\{[\s\S]+\}|\[[\s\S]+\])", text)
    if m:
        return m.group(1).strip()
    return None


def parse_agent_output(
    raw_text: str,
    schema: Type[T],
) -> tuple[Optional[T], str]:
    """
    Phase 0 parser — no LLM retry (that lives in api_client).
    Returns (parsed_model | None, status).

    Strategy:
    1. Direct json.loads() on full text
    2. Extract JSON block from fenced code or bare braces
    3. Return None + STATUS_FAILED
    """
    # Step 1 — direct parse
    model, _ = _try_parse(raw_text, schema)
    if model is not None:
        return model, STATUS_VALID

    # Step 2 — extract block
    extracted = _extract_json_block(raw_text)
    if extracted:
        model, err = _try_parse(extracted, schema)
        if model is not None:
            return model, STATUS_EXTRACTED

        # Step 3 — if extracted is a bare array, try wrapping it in the first
        # list field the schema expects (handles LLMs that return [...] instead of {"key": [...]})
        if extracted.strip().startswith("["):
            schema_fields = schema.model_fields
            list_keys = [k for k, f in schema_fields.items()
                         if hasattr(f.annotation, '__origin__') and f.annotation.__origin__ is list]
            for key in list_keys:
                model, _ = _try_parse(f'{{"{key}": {extracted}}}', schema)
                if model is not None:
                    return model, STATUS_EXTRACTED

    return None, STATUS_FAILED


def build_reflexion_prompt(
    raw_text: str,
    schema: Type[BaseModel],
    attempt: int,
    max_attempts: int,
    last_error: str,
) -> str:
    """Builds the self-correction message sent back to Claude on parse failure."""
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    return (
        f"Your previous response failed JSON validation "
        f"(attempt {attempt}/{max_attempts}).\n\n"
        f"Error: {last_error}\n\n"
        f"Required schema:\n```json\n{schema_json}\n```\n\n"
        f"Rules:\n"
        f"- Return ONLY valid JSON — no surrounding text, no markdown fences.\n"
        f"- Do not invent data. Use 'N/A' for missing optional fields.\n"
        f"- All required fields must be present.\n\n"
        f"Your corrected response:"
    )

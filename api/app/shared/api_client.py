"""
LLM client abstraction.

BaseLLMClient owns the full run_agent() lifecycle: secret scrubbing,
reflexion loop, DB recording, usage logging, budget update.

Concrete subclasses only implement _call() — the raw HTTP exchange.
Provider is selected at startup via the llm_provider config setting.
"""
import asyncio
import re
import json
import time
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone, date
from typing import TypeVar, Type, Optional

import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.shared.config import get_settings
from .parser import parse_agent_output, build_reflexion_prompt
from .schemas import AgentError

T = TypeVar("T", bound=BaseModel)

OLLAMA_BASE_URL = "http://localhost:11434"

# Patterns that must never appear in prompts
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-_\.]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"[Pp]assword\s*[:=]\s*\S{8,}"),
]


class SecurityError(Exception):
    pass


# ------------------------------------------------------------------
# Base class — shared lifecycle, subclasses implement _call()
# ------------------------------------------------------------------

def _flatten_content(content: str | list[str]) -> str:
    """
    run_agent() sends a user message's content as [cacheable_prefix,
    user_message] when prompt caching is requested. Only AnthropicClient
    understands that shape; every other provider flattens it back to a
    plain string via this helper.
    """
    if isinstance(content, list):
        return "".join(content)
    return content


class BaseLLMClient(ABC):
    """
    Owns run_agent(): scrubbing → _call() → reflexion → DB record → budget.
    Subclasses must set self._model and implement _call().
    """

    _model: str
    _max_corrections: int

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run_agent(
        self,
        agent_name: str,
        system_prompt: str,
        user_message: str,
        output_schema: Type[T],
        db: Optional[AsyncSession] = None,
        application_id: Optional[int] = None,
        user_id: Optional[int] = None,
        job_posting_id: Optional[int] = None,
        request_type: str = "unknown",
        use_coordinator: bool = False,
        stream_callback: Optional[callable] = None,
        max_self_corrections: Optional[int] = None,
        cacheable_prefix: Optional[str] = None,
    ) -> tuple[T | AgentError, dict]:
        """
        cacheable_prefix: optional text that's identical across repeated
        calls (e.g. the candidate's profile+resume across a batch of
        scoring calls). When given, user_message is sent as two pieces —
        [cacheable_prefix, user_message] — so a provider that supports
        prompt caching (AnthropicClient) can mark the prefix reusable.
        Providers without a caching concept just concatenate the two
        pieces back into one string, matching today's behavior.
        """
        import logging
        _log = logging.getLogger("llm_timing")

        self._scrub_secrets(system_prompt + (cacheable_prefix or "") + user_message)

        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()

        user_content = (
            [cacheable_prefix, user_message] if cacheable_prefix is not None else user_message
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        input_chars = len(system_prompt) + (len(cacheable_prefix) if cacheable_prefix else 0) + len(user_message)
        _log.info("TIMING [%s] LLM call start — input ~%d chars", agent_name, input_chars)
        raw_text, usage = await self._call(
            messages, stream_callback,
            user_id=user_id, job_posting_id=job_posting_id, request_type=request_type, db=db,
        )
        t_llm = time.monotonic() - t0
        _log.info("TIMING [%s] LLM call done — %.2fs, output %d chars", agent_name, t_llm, len(raw_text))

        duration_ms = int(t_llm * 1000)

        parsed, status = parse_agent_output(raw_text, output_schema)
        _log.info("TIMING [%s] parse attempt 0: %s", agent_name, status)

        # Reflexion: retry on parse failure
        max_corrections = max_self_corrections if max_self_corrections is not None else self._max_corrections
        attempt = 1
        last_error = status
        while parsed is None and attempt <= max_corrections:
            correction_prompt = build_reflexion_prompt(
                raw_text, output_schema, attempt, max_corrections, last_error
            )
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": correction_prompt})

            await asyncio.sleep(5)
            t_retry = time.monotonic()
            raw_text, extra_usage = await self._call(
                messages, stream_callback,
                user_id=user_id, job_posting_id=job_posting_id,
                request_type=f"{request_type}_retry{attempt}", db=db,
            )
            _log.info("TIMING [%s] LLM retry %d — %.2fs, output %d chars", agent_name, attempt, time.monotonic() - t_retry, len(raw_text))
            usage = _merge_usage(usage, extra_usage)
            parsed, status = parse_agent_output(raw_text, output_schema)
            _log.info("TIMING [%s] parse attempt %d: %s", agent_name, attempt, status)
            attempt += 1
            last_error = status

        final_status = "complete" if parsed is not None else "failed"

        run_id = None
        if db is not None:
            run_id = await self._record_run(
                db=db,
                agent_name=agent_name,
                raw_output=raw_text,
                usage=usage,
                status=final_status,
                duration_ms=duration_ms,
                started_at=started_at,
                application_id=application_id,
                user_id=user_id,
                attempt_number=attempt,
                system_prompt=system_prompt,
            )
            await _update_budget(db, agent_name, usage)

        meta = {
            "run_id": run_id,
            "status": final_status,
            "model": self._model,
            "attempts": attempt,
            "duration_ms": duration_ms,
            "cost_usd": 0.0,
            **usage,
        }

        if parsed is not None:
            return parsed, meta

        return AgentError(
            error=f"Failed to parse after {self._max_corrections} attempts. Last error: {last_error}",
            raw_output=raw_text,
            needs_human_review=True,
        ), meta

    # ------------------------------------------------------------------
    # Abstract — each provider implements this
    # ------------------------------------------------------------------

    @abstractmethod
    async def _call(
        self,
        messages: list[dict],
        stream_callback: Optional[callable] = None,
        *,
        user_id: Optional[int] = None,
        job_posting_id: Optional[int] = None,
        request_type: str = "unknown",
        db: Optional[AsyncSession] = None,
    ) -> tuple[str, dict]:
        """Make the HTTP call and return (full_text, usage_dict)."""

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _scrub_secrets(self, text: str) -> None:
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                raise SecurityError("Secret pattern detected in prompt. Call aborted.")

    async def _persist_usage(
        self,
        *,
        user_id: Optional[int],
        job_posting_id: Optional[int],
        request_type: str,
        input_tokens: int,
        output_tokens: int,
        requested_at: datetime,
        responded_at: datetime,
        db: Optional[AsyncSession],
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        from app.shared.llm_logger import log_llm_call

        duration_s = (responded_at - requested_at).total_seconds()

        log_llm_call(
            user_id=user_id,
            job_posting_id=job_posting_id,
            request_type=request_type,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requested_at=requested_at.isoformat(),
            responded_at=responded_at.isoformat(),
            duration_s=duration_s,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

        if db is not None:
            try:
                await db.execute(
                    text("""
                        INSERT INTO llm_usage_logs
                            (user_id, job_posting_id, request_type, model,
                             input_tokens, output_tokens, requested_at, responded_at)
                        VALUES
                            (:user_id, :job_posting_id, :request_type, :model,
                             :input_tokens, :output_tokens, :requested_at, :responded_at)
                    """),
                    {
                        "user_id": user_id,
                        "job_posting_id": job_posting_id,
                        "request_type": request_type,
                        "model": self._model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "requested_at": requested_at,
                        "responded_at": responded_at,
                    },
                )
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "llm_usage_logs insert failed (non-fatal)", exc_info=True
                )

    async def _record_run(
        self,
        db: AsyncSession,
        agent_name: str,
        raw_output: str,
        usage: dict,
        status: str,
        duration_ms: int,
        started_at: datetime,
        application_id: Optional[int],
        user_id: Optional[int],
        attempt_number: int,
        system_prompt: str,
    ) -> int:
        prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()
        insert_result = await db.execute(
            text("""
                INSERT INTO agent_runs
                    (user_id, application_id, agent_name, reasoning_pattern, status,
                     attempt_number, system_prompt, final_output,
                     input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                     cost_usd, started_at, completed_at)
                VALUES
                    (:uid, :aid, :name, :pattern, :status,
                     :attempt, :prompt, :output,
                     :it, :ot, :crt, :cct,
                     :cost, :started, :completed)
                RETURNING id
            """),
            {
                "uid": user_id,
                "aid": application_id,
                "name": agent_name,
                "pattern": "single_call",
                "status": status,
                "attempt": attempt_number,
                "prompt": prompt_hash,
                "output": raw_output,
                "it": usage.get("input_tokens", 0),
                "ot": usage.get("output_tokens", 0),
                "crt": usage.get("cache_read_tokens", 0),
                "cct": usage.get("cache_creation_tokens", 0),
                "cost": 0.0,
                "started": started_at,
                "completed": datetime.now(timezone.utc),
            },
        )
        return insert_result.scalar_one_or_none()


# ------------------------------------------------------------------
# Ollama provider
# ------------------------------------------------------------------

class OllamaClient(BaseLLMClient):
    def __init__(self):
        settings = get_settings()
        self._model = settings.specialist_model
        self._max_corrections = settings.max_self_corrections

    async def _call(
        self,
        messages: list[dict],
        stream_callback: Optional[callable] = None,
        *,
        user_id: Optional[int] = None,
        job_posting_id: Optional[int] = None,
        request_type: str = "unknown",
        db: Optional[AsyncSession] = None,
    ) -> tuple[str, dict]:
        # Ollama has no caching concept, so a list-shaped content (from
        # run_agent()'s cacheable_prefix split, normally only used by
        # AnthropicClient) is flattened back into one plain string.
        messages = [
            {**m, "content": _flatten_content(m["content"])} for m in messages
        ]

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": stream_callback is not None,
            "options": {"temperature": 0.1, "num_predict": 6144, "num_ctx": 16384},
        }

        full_text = ""
        input_tokens = sum(len(m["content"].split()) for m in messages)
        requested_at = datetime.now(timezone.utc)

        async with httpx.AsyncClient(timeout=300.0) as client:
            if stream_callback is not None:
                async with client.stream(
                    "POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            full_text += token
                            if token:
                                await stream_callback(token)
                        except json.JSONDecodeError:
                            continue
            else:
                payload["stream"] = False
                resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                full_text = data.get("message", {}).get("content", "")

        responded_at = datetime.now(timezone.utc)
        output_tokens = len(full_text.split())

        await self._persist_usage(
            user_id=user_id,
            job_posting_id=job_posting_id,
            request_type=request_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requested_at=requested_at,
            responded_at=responded_at,
            db=db,
        )

        return full_text, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }


# ------------------------------------------------------------------
# Gemini provider
# ------------------------------------------------------------------

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient(BaseLLMClient):
    def __init__(self):
        settings = get_settings()
        self._model = settings.gemini_model
        self._fallback_model = settings.gemini_fallback_model
        self._api_key = settings.gemini_api_key
        self._max_corrections = settings.max_self_corrections

    async def _call(
        self,
        messages: list[dict],
        stream_callback: Optional[callable] = None,
        *,
        user_id: Optional[int] = None,
        job_posting_id: Optional[int] = None,
        request_type: str = "unknown",
        db: Optional[AsyncSession] = None,
    ) -> tuple[str, dict]:
        from app.shared.rate_limiter import gemini_rate_limiter
        await gemini_rate_limiter.acquire()

        # Gemini has no caching concept, so a list-shaped content (from
        # run_agent()'s cacheable_prefix split, normally only used by
        # AnthropicClient) is flattened back into one plain string.
        messages = [
            {**m, "content": _flatten_content(m["content"])} for m in messages
        ]

        # Convert OpenAI-style messages to Gemini contents format.
        # System message becomes the first user turn with a "SYSTEM:" prefix
        # so the conversation alternates user/model as Gemini requires.
        contents = []
        for m in messages:
            role = "user" if m["role"] in ("system", "user") else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,
            },
        }

        input_tokens = sum(len(m["content"].split()) for m in messages)
        requested_at = datetime.now(timezone.utc)
        full_text = ""

        headers = {"X-goog-api-key": self._api_key, "Content-Type": "application/json"}
        models_to_try = [self._model]
        if self._fallback_model and self._fallback_model != self._model:
            models_to_try.append(self._fallback_model)

        data = None
        for model in models_to_try:
            url = f"{GEMINI_BASE_URL}/{model}:generateContent"
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 503 and model != models_to_try[-1]:
                    import logging as _logging
                    _logging.getLogger(__name__).warning(
                        "GeminiClient: %s returned 503, retrying with fallback %s",
                        model, models_to_try[-1],
                    )
                    continue
                resp.raise_for_status()
                data = resp.json()
                break

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            full_text = "".join(p.get("text", "") for p in parts)

        # Gemini returns real token counts in usageMetadata
        usage_meta = data.get("usageMetadata", {})
        input_tokens = usage_meta.get("promptTokenCount", input_tokens)
        output_tokens = usage_meta.get("candidatesTokenCount", len(full_text.split()))

        responded_at = datetime.now(timezone.utc)

        if stream_callback is not None:
            await stream_callback(full_text)

        await self._persist_usage(
            user_id=user_id,
            job_posting_id=job_posting_id,
            request_type=request_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requested_at=requested_at,
            responded_at=responded_at,
            db=db,
        )

        return full_text, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }


# ------------------------------------------------------------------
# Anthropic provider
# ------------------------------------------------------------------

class AnthropicClient(BaseLLMClient):
    """
    Anthropic Claude provider. Unlike GeminiClient/OllamaClient, the model
    is passed in at construction rather than read from a single settings
    field — callers create one instance per task (e.g. Haiku for
    classification, Sonnet for scoring) rather than sharing one global model.

    The system prompt is sent with cache_control so repeated identical
    system prompts (e.g. the classifier/scorer prompt, unchanged across
    every call) are cached server-side — real cache token counts are
    reported back in the usage dict, unlike Gemini/Ollama which have no
    caching mechanism and always report 0.
    """

    def __init__(self, model: str):
        import anthropic

        settings = get_settings()
        self._model = model
        self._api_key = settings.anthropic_api_key
        self._max_corrections = settings.max_self_corrections
        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)

    async def _call(
        self,
        messages: list[dict],
        stream_callback: Optional[callable] = None,
        *,
        user_id: Optional[int] = None,
        job_posting_id: Optional[int] = None,
        request_type: str = "unknown",
        db: Optional[AsyncSession] = None,
    ) -> tuple[str, dict]:
        import anthropic

        # run_agent() always sends [{"role": "system", ...}, {"role": "user", ...}],
        # and appends further user/assistant turns for reflexion retries.
        # Anthropic takes `system` as a separate top-level param, not a
        # message with role "system" — split it out, cache the rest as-is.
        # A user message's content may be [cacheable_prefix, user_message]
        # (set by run_agent() when it's given a cacheable_prefix) — turn
        # that into two text blocks with the cache marker on the first, so
        # the identical prefix across repeated calls (e.g. the candidate's
        # profile+resume across a batch of scoring calls) is cached
        # server-side instead of being billed in full every time.
        system_blocks: list[dict] = []
        api_messages: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                system_blocks.append({
                    "type": "text",
                    "text": m["content"],
                    "cache_control": {"type": "ephemeral"},
                })
            elif isinstance(m["content"], list):
                cacheable_prefix, variable_suffix = m["content"]
                api_messages.append({
                    "role": m["role"],
                    "content": [
                        {
                            "type": "text",
                            "text": cacheable_prefix,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": variable_suffix},
                    ],
                })
            else:
                api_messages.append({"role": m["role"], "content": m["content"]})

        requested_at = datetime.now(timezone.utc)

        import logging
        _log = logging.getLogger(__name__)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=8192,
                system=system_blocks,
                messages=api_messages,
            )
        except anthropic.RateLimitError as e:
            _log.warning("AnthropicClient: rate limited for model=%s: %s", self._model, e)
            raise
        except anthropic.APIStatusError as e:
            _log.warning("AnthropicClient: API error (%s) for model=%s: %s", e.status_code, self._model, e)
            raise
        except anthropic.APIConnectionError as e:
            _log.warning("AnthropicClient: connection error for model=%s: %s", self._model, e)
            raise

        full_text = "".join(
            block.text for block in response.content if block.type == "text"
        )

        usage = response.usage
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        cache_read_tokens = usage.cache_read_input_tokens or 0
        cache_creation_tokens = usage.cache_creation_input_tokens or 0

        responded_at = datetime.now(timezone.utc)

        if stream_callback is not None:
            await stream_callback(full_text)

        await self._persist_usage(
            user_id=user_id,
            job_posting_id=job_posting_id,
            request_type=request_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            requested_at=requested_at,
            responded_at=responded_at,
            db=db,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )

        return full_text, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
        }


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _merge_usage(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


async def _update_budget(db: AsyncSession, agent_name: str, usage: dict):
    today = date.today()
    await db.execute(
        text("""
            INSERT INTO budget_records
                (date, agent_name, total_input_tokens, total_output_tokens,
                 total_cache_read_tokens, total_cache_creation_tokens, total_cost_usd, call_count)
            VALUES
                (:date, :name, :it, :ot, 0, 0, 0.0, 1)
            ON CONFLICT(date, agent_name) DO UPDATE SET
                total_input_tokens = budget_records.total_input_tokens + excluded.total_input_tokens,
                total_output_tokens = budget_records.total_output_tokens + excluded.total_output_tokens,
                call_count = budget_records.call_count + 1
        """),
        {
            "date": today,
            "name": agent_name,
            "it": usage.get("input_tokens", 0),
            "ot": usage.get("output_tokens", 0),
        },
    )


# Singleton
_client: Optional[BaseLLMClient] = None


def get_llm_client() -> BaseLLMClient:
    """
    Legacy global client — NOT used for classification, scoring or resume
    generation (those use get_classifier_client/get_scorer_client/
    get_resume_client, which return Anthropic Haiku when ANTHROPIC_API_KEY
    is set). Still used by the non-scoring research path, industry_refinement,
    and as the fallback when ANTHROPIC_API_KEY is empty.

    Returns GeminiClient if GEMINI_API_KEY is set.
    Falls back to OllamaClient in development only.
    Raises RuntimeError in production if GEMINI_API_KEY is missing.
    """
    global _client
    if _client is None:
        settings = get_settings()
        if settings.gemini_api_key:
            _client = GeminiClient()
        elif settings.app_env == "production":
            raise RuntimeError(
                "GEMINI_API_KEY is required in production. "
                "Set it as a GitHub Secret and ensure the CI pipeline writes it to .env."
            )
        else:
            _client = OllamaClient()
    return _client


# Separate singletons from the global `_client` above — these are opt-in
# per-task overrides, not a replacement for get_llm_client(). Every other
# caller (interview prep, profile extraction, the non-scoring research
# agent path, ...) keeps using get_llm_client() untouched.
_classifier_client: Optional[BaseLLMClient] = None
_scorer_client: Optional[BaseLLMClient] = None
_resume_client: Optional[BaseLLMClient] = None


def _build_anthropic_task_client(model: str) -> BaseLLMClient:
    """
    Returns an AnthropicClient on the given model if ANTHROPIC_API_KEY is
    set, else falls back to get_llm_client() (Gemini/Ollama) — safe to
    deploy before an Anthropic key is configured anywhere. Shared by the
    per-task client getters below so each one stays an independently
    swappable model choice without duplicating the fallback logic.
    """
    settings = get_settings()
    if settings.anthropic_api_key:
        return AnthropicClient(model=model)
    return get_llm_client()


def get_classifier_client() -> BaseLLMClient:
    """Returns the per-task client for industry classification (Haiku)."""
    global _classifier_client
    if _classifier_client is None:
        _classifier_client = _build_anthropic_task_client(get_settings().anthropic_haiku_model)
    return _classifier_client


def get_scorer_client() -> BaseLLMClient:
    """Returns the per-task client for job-fit scoring (Haiku)."""
    global _scorer_client
    if _scorer_client is None:
        _scorer_client = _build_anthropic_task_client(get_settings().anthropic_haiku_model)
    return _scorer_client


def get_resume_client() -> BaseLLMClient:
    """Returns the per-task client for resume generation (Haiku)."""
    global _resume_client
    if _resume_client is None:
        _resume_client = _build_anthropic_task_client(get_settings().anthropic_haiku_model)
    return _resume_client

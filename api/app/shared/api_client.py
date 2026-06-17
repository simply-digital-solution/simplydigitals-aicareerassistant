"""
LLM client abstraction.

BaseLLMClient owns the full run_agent() lifecycle: secret scrubbing,
reflexion loop, DB recording, usage logging, budget update.

Concrete subclasses only implement _call() — the raw HTTP exchange.
Provider is selected at startup via the llm_provider config setting.
"""
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
    ) -> tuple[T | AgentError, dict]:
        import logging
        _log = logging.getLogger("llm_timing")

        self._scrub_secrets(system_prompt + user_message)

        started_at = datetime.now(timezone.utc)
        t0 = time.monotonic()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]

        input_chars = sum(len(m["content"]) for m in messages)
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
        attempt = 1
        last_error = status
        while parsed is None and attempt <= self._max_corrections:
            correction_prompt = build_reflexion_prompt(
                raw_text, output_schema, attempt, self._max_corrections, last_error
            )
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": correction_prompt})

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
                        "requested_at": requested_at.isoformat(),
                        "responded_at": responded_at.isoformat(),
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
        await db.execute(
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
                "crt": 0,
                "cct": 0,
                "cost": 0.0,
                "started": started_at.isoformat(),
                "completed": datetime.now(timezone.utc).isoformat(),
            },
        )
        row = await db.execute(text("SELECT last_insert_rowid()"))
        return row.scalar()


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
# Module-level helpers
# ------------------------------------------------------------------

def _merge_usage(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


async def _update_budget(db: AsyncSession, agent_name: str, usage: dict):
    today = date.today().isoformat()
    await db.execute(
        text("""
            INSERT INTO budget_records
                (date, agent_name, total_input_tokens, total_output_tokens,
                 total_cache_read_tokens, total_cache_creation_tokens, total_cost_usd, call_count)
            VALUES
                (:date, :name, :it, :ot, 0, 0, 0.0, 1)
            ON CONFLICT(date, agent_name) DO UPDATE SET
                total_input_tokens = total_input_tokens + excluded.total_input_tokens,
                total_output_tokens = total_output_tokens + excluded.total_output_tokens,
                call_count = call_count + 1
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


def get_claude_client() -> BaseLLMClient:
    """Returns the configured LLM client. Name kept for compatibility."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client

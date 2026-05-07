"""
ClaudeCodeBackend — routes QuantaAlpha LLM calls through the local Claude Code
session via the official `claude-agent-sdk` package, draining the user's Max
subscription instead of paying per token to Anthropic API directly.

Key design choice: pin one Claude Code conversation per QuantaAlpha "branch"
(one per evolution direction/round), so the 5-step inner loop reuses one
context. The backtest step in the middle of each loop spaces calls out
naturally; Max 20× budget absorbs sequential experiments comfortably.

Authentication is implicit — the user must have run `claude login` locally.
There is no API key. If not authenticated, ClaudeSDKClient construction fails.

Embeddings are NOT supported by Claude. Callers must route embeddings to a
separate provider (OpenAI / Voyage / DashScope) or disable the CoSTEER
knowledge base.
"""

from __future__ import annotations

import asyncio
import contextvars
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

from quantaalpha.llm.config import LLM_SETTINGS
from quantaalpha.log import logger


# ── Session-key context (set by AlphaAgentLoop.run; read on each LLM call) ──
# When unset, all calls share a single "global" Claude Code session.
_session_key_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "claude_code_session_key", default="global"
)


def set_session_key(key: str) -> contextvars.Token:
    """Bind subsequent LLM calls in this context to a specific session.

    Returns a Token; pass to ``_session_key_var.reset(token)`` to undo.
    """
    return _session_key_var.set(key)


def reset_session_key(token: contextvars.Token) -> None:
    _session_key_var.reset(token)


# ── Errors ─────────────────────────────────────────────────────────────────


class ClaudeCodeError(Exception):
    """Base error for ClaudeCodeBackend."""


class ClaudeCodeRateLimitError(ClaudeCodeError):
    """The local subscription's usage budget appears exhausted."""


class ClaudeCodeSessionUnavailableError(ClaudeCodeError):
    """No authenticated Claude Code session is available locally."""


class ClaudeCodeSDKMissingError(ClaudeCodeError):
    """The claude-agent-sdk package is not installed."""


# ── Per-conversation handle ────────────────────────────────────────────────


@dataclass
class _SessionHandle:
    """One Claude Code conversation, bound to a QuantaAlpha branch key."""

    session_id: str
    client: Any  # ClaudeSDKClient — typed as Any to avoid hard import at module load
    created_at: float
    call_count: int = 0
    estimated_tokens: int = 0


# ── Backend ────────────────────────────────────────────────────────────────


class ClaudeCodeBackend:
    """Drives QuantaAlpha LLM calls through the local Claude Code session.

    The public method names mirror APIBackend so this can be substituted
    transparently. Only methods QuantaAlpha actually invokes are implemented;
    the rest raise NotImplementedError.
    """

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        max_turns_per_session: Optional[int] = None,
        rate_limit_cooldown_seconds: Optional[int] = None,
        disable_tools: Optional[bool] = None,
    ) -> None:
        self.model = model if model is not None else LLM_SETTINGS.claude_code_model
        self.max_turns_per_session = (
            max_turns_per_session
            if max_turns_per_session is not None
            else LLM_SETTINGS.claude_code_max_turns_per_session
        )
        self.rate_limit_cooldown = (
            rate_limit_cooldown_seconds
            if rate_limit_cooldown_seconds is not None
            else LLM_SETTINGS.claude_code_rate_limit_cooldown
        )
        self.disable_tools = (
            disable_tools
            if disable_tools is not None
            else LLM_SETTINGS.claude_code_disable_tools
        )

        self._sessions: dict[str, _SessionHandle] = {}
        self._rate_limited_until: float = 0.0

        # Persistent event loop owned by this backend. The Claude Agent SDK's
        # subprocess transport binds its stdin/stdout streams to whatever loop
        # opened them — so we cannot use asyncio.run() per call (which creates
        # and destroys a loop each time, killing the subprocess streams). One
        # loop, reused across all open/send/close calls, keeps streams alive.
        if sys.platform == "win32":
            # Subprocess support on Windows requires the proactor loop.
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        self._loop = asyncio.new_event_loop()

        self._import_sdk_or_fail()
        logger.info(
            "[ClaudeCode] backend ready"
            f" (model={self.model or 'default'},"
            f" max_turns={self.max_turns_per_session},"
            f" disable_tools={self.disable_tools})"
        )

    # ── Public API surface (mirrors APIBackend) ─────────────────────────

    def build_messages_and_create_chat_completion(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        former_messages: Optional[list] = None,
        chat_cache_prefix: str = "",
        *,
        shrink_multiple_break: bool = False,
        json_mode: bool = False,
        session_key: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        self._guard_rate_limit()

        if shrink_multiple_break:
            while user_prompt and "\n\n\n" in user_prompt:
                user_prompt = user_prompt.replace("\n\n\n", "\n\n")
            if system_prompt:
                while "\n\n\n" in system_prompt:
                    system_prompt = system_prompt.replace("\n\n\n", "\n\n")

        key = session_key or _session_key_var.get()
        # IMPORTANT: open the session with no system prompt so the per-call
        # system_prompt below isn't shadowed. Claude Code sessions only
        # accept a system prompt at open time; per-call system prompts
        # would otherwise be silently dropped. We inline the system prompt
        # into each user message instead.
        handle = self._get_or_create_session(key, system_prompt=None)

        prompt = self._format_prompt(
            user_prompt, system_prompt, former_messages, json_mode
        )
        return self._send(handle, prompt)

    def build_messages_and_calculate_token(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        former_messages: Optional[list] = None,
        **kwargs: Any,
    ) -> int:
        # Heuristic ~4 chars/token; used only for context-budget decisions,
        # not billing. Anthropic's actual token count is ~10–20% off.
        parts = [user_prompt or "", system_prompt or ""]
        if former_messages:
            for m in former_messages:
                content = m.get("content", "") if isinstance(m, dict) else str(m)
                parts.append(content)
        return sum(len(p) // 4 for p in parts)

    def build_chat_session(self, *args: Any, **kwargs: Any) -> Any:
        """Compatibility shim. QuantaAlpha's ChatSession class expects an
        api_backend argument and uses it for one-off chat completions; we
        return self so it routes back through this backend.
        """
        from quantaalpha.llm.client import ChatSession  # local import to avoid cycle

        conversation_id = kwargs.pop("conversation_id", None)
        system_prompt = kwargs.pop("session_system_prompt", None) or kwargs.pop(
            "system_prompt", None
        )
        return ChatSession(
            api_backend=self, conversation_id=conversation_id, system_prompt=system_prompt
        )

    def create_embedding(self, input_content: Any = None, *args: Any, **kwargs: Any) -> Any:
        """Return zero-vector embeddings.

        Claude has no embedding API. Rather than raise (which crashes the
        CoSTEER RAG path that calls this for code-knowledge similarity),
        we return zero vectors so the downstream similarity calculation
        produces uniform near-zero similarity — i.e. RAG returns "nothing
        relevant" and CoSTEER falls back to its no-context code generation.

        The factor mining still works; CoSTEER just refines without the
        benefit of historical error→fix examples. Slightly more LLM calls
        per refinement loop, but no crashes.

        For better quality, set EMBEDDING_BASE_URL/EMBEDDING_API_KEY in .env
        to a real embedding provider (OpenAI / Voyage / DashScope) and the
        APIBackend's openai-compatible embedding path will be used instead.
        See QUANTAALPHA_CLAUDE_CODE_DESIGN.md §6.
        """
        # OpenAI's text-embedding-3-small uses 1536 dims; pick that as a
        # reasonable default. Callers do similarity, not exact size checks.
        EMB_DIM = 1536

        if input_content is None and args:
            input_content = args[0]

        if isinstance(input_content, str):
            return [0.0] * EMB_DIM

        if isinstance(input_content, list):
            return [[0.0] * EMB_DIM for _ in input_content]

        return [0.0] * EMB_DIM

    def close_session(self, key: str) -> None:
        handle = self._sessions.pop(key, None)
        if handle is None:
            return
        try:
            self._loop.run_until_complete(self._close_async(handle))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[ClaudeCode] error closing session {key}: {exc}")
        else:
            logger.info(f"[ClaudeCode] closed session: {key}")

    def close_all(self) -> None:
        for k in list(self._sessions.keys()):
            self.close_session(k)
        # Tear down the event loop. After this, the backend cannot be used
        # again — caller must create a new instance (or use reset_global_backend).
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001
                pass

    def stats(self) -> dict[str, Any]:
        return {
            "sessions_open": len(self._sessions),
            "total_turns": sum(h.call_count for h in self._sessions.values()),
            "estimated_tokens": sum(h.estimated_tokens for h in self._sessions.values()),
            "rate_limited_until": (
                time.ctime(self._rate_limited_until)
                if self._rate_limited_until > time.time()
                else None
            ),
        }

    # ── Session lifecycle ──────────────────────────────────────────────

    def _get_or_create_session(
        self, key: str, system_prompt: Optional[str]
    ) -> _SessionHandle:
        handle = self._sessions.get(key)
        if handle is not None and handle.call_count < self.max_turns_per_session:
            return handle

        if handle is not None:
            # Hit the per-session turn cap; rotate the session.
            logger.info(
                f"[ClaudeCode] rotating session {key} after"
                f" {handle.call_count} turns"
            )
            self.close_session(key)

        return self._open_session(key, system_prompt)

    def _open_session(
        self, key: str, system_prompt: Optional[str]
    ) -> _SessionHandle:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

        options_kwargs: dict[str, Any] = {}
        if self.disable_tools:
            options_kwargs["allowed_tools"] = []
        if self.model:
            options_kwargs["model"] = self.model
        if system_prompt:
            options_kwargs["system_prompt"] = system_prompt
        elif LLM_SETTINGS.default_system_prompt:
            options_kwargs["system_prompt"] = LLM_SETTINGS.default_system_prompt

        options = ClaudeAgentOptions(**options_kwargs)
        client = ClaudeSDKClient(options=options)
        # ClaudeSDKClient must be entered as an async context manager; we
        # manage it manually so the same client survives across query() calls.
        # We run on our persistent loop so subprocess streams stay alive.
        try:
            self._loop.run_until_complete(client.__aenter__())
        except Exception as exc:  # noqa: BLE001
            if self._is_auth_error(exc):
                raise ClaudeCodeSessionUnavailableError(
                    "Claude Code is not authenticated. Run `claude login` "
                    "(or open the Claude Code app and sign in) and retry."
                ) from exc
            raise

        handle = _SessionHandle(
            session_id=key, client=client, created_at=time.time()
        )
        self._sessions[key] = handle
        logger.info(f"[ClaudeCode] opened session: {key}")
        return handle

    async def _close_async(self, handle: _SessionHandle) -> None:
        try:
            await handle.client.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            # best-effort cleanup
            pass

    # ── Send ───────────────────────────────────────────────────────────

    def _send(self, handle: _SessionHandle, prompt: str) -> str:
        try:
            text = self._loop.run_until_complete(self._send_async(handle, prompt))
        except Exception as exc:
            if self._is_rate_limit(exc):
                self._mark_rate_limited()
                # Drop the (probably-poisoned) session so the next call opens
                # a fresh one once cooldown expires.
                self._sessions.pop(handle.session_id, None)
                raise ClaudeCodeRateLimitError(str(exc)) from exc
            if self._is_auth_error(exc):
                raise ClaudeCodeSessionUnavailableError(str(exc)) from exc
            raise

        handle.call_count += 1
        handle.estimated_tokens += (len(prompt) + len(text)) // 4
        return text

    async def _send_async(self, handle: _SessionHandle, prompt: str) -> str:
        from claude_agent_sdk import AssistantMessage, TextBlock

        await handle.client.query(prompt)

        chunks: list[str] = []
        message_types_seen: list[str] = []
        block_types_seen: list[str] = []

        async for message in handle.client.receive_response():
            message_types_seen.append(type(message).__name__)
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    block_types_seen.append(type(block).__name__)
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
                    elif hasattr(block, "text"):
                        # Defensive: some SDK versions wrap text differently.
                        chunks.append(block.text)

        result = "".join(chunks)

        if not result.strip():
            # Empty response — log diagnostics so we can see what happened.
            logger.warning(
                f"[ClaudeCode] empty response from session {handle.session_id} "
                f"after {handle.call_count + 1} turns. "
                f"prompt_len={len(prompt)}, "
                f"messages={message_types_seen}, "
                f"blocks={block_types_seen}"
            )
            # Truncate prompt for readability when logging the head
            head = prompt[:200].replace("\n", " ")
            logger.warning(f"[ClaudeCode] prompt head: {head!r}")

        return result

    # ── Prompt formatting ──────────────────────────────────────────────

    def _format_prompt(
        self,
        user_prompt: str,
        system_prompt: Optional[str],
        former_messages: Optional[list],
        json_mode: bool,
    ) -> str:
        parts: list[str] = []

        # Inline the per-call system prompt. We can't change the session's
        # system prompt mid-conversation (Claude Code locks it at open time),
        # so we prepend it as a [SYSTEM] section in every user message. The
        # downside is some token redundancy across turns; the upside is each
        # call gets the right instructions even when reusing a session.
        if system_prompt:
            parts.append(f"[SYSTEM INSTRUCTIONS]\n{system_prompt}")

        # former_messages is QuantaAlpha-supplied chat history that the caller
        # wants prepended for THIS turn — typically empty in the inner loop.
        # Within a Claude Code session, prior turns of THIS conversation are
        # already in context, but former_messages might come from elsewhere.
        if former_messages:
            for m in former_messages:
                if isinstance(m, dict):
                    role = m.get("role", "user").upper()
                    content = m.get("content", "")
                    parts.append(f"[{role}]\n{content}")

        parts.append(f"[USER REQUEST]\n{user_prompt}" if system_prompt else user_prompt)

        if json_mode:
            parts.append(
                "[OUTPUT FORMAT] Respond with valid JSON only. "
                "No prose, no markdown fences, no commentary before or after. "
                "Match the schema in the system instructions exactly."
            )

        return "\n\n".join(parts)

    # ── Health checks ──────────────────────────────────────────────────

    def _import_sdk_or_fail(self) -> None:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError as exc:
            raise ClaudeCodeSDKMissingError(
                "claude-agent-sdk is not installed. Run: "
                "pip install claude-agent-sdk"
            ) from exc

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        msg = str(exc).lower()
        markers = (
            "rate limit",
            "rate-limit",
            "rate_limit",
            "usage limit",
            "quota",
            "exceeded",
            "5-hour",
            "5 hour",
            "throttl",
            "429",
            "too many requests",
        )
        return any(m in msg for m in markers)

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        markers = (
            "not authenticated",
            "unauthorized",
            "401",
            "invalid credentials",
            "please log in",
            "claude login",
            "no session",
            "cli not found",
        )
        return any(m in msg for m in markers)

    def _mark_rate_limited(self) -> None:
        self._rate_limited_until = time.time() + self.rate_limit_cooldown
        logger.warning(
            "[ClaudeCode] rate-limit-classified error; cooling down for "
            f"{self.rate_limit_cooldown}s "
            f"(until {time.ctime(self._rate_limited_until)})"
        )

    def _guard_rate_limit(self) -> None:
        if time.time() < self._rate_limited_until:
            raise ClaudeCodeRateLimitError(
                f"Subscription cooldown active until "
                f"{time.ctime(self._rate_limited_until)}"
            )


# ── Module-level singleton ─────────────────────────────────────────────────
# APIBackend() is instantiated at ~35 call sites without arguments. Without a
# singleton, each call would build a fresh ClaudeCodeBackend with its own
# session pool, defeating the session-pinning design. We expose a process-wide
# instance so all APIBackend objects share one Claude Code session pool.

_global_backend_instance: Optional[ClaudeCodeBackend] = None


def get_global_backend() -> ClaudeCodeBackend:
    """Return the process-wide ClaudeCodeBackend, constructing it on first call."""
    global _global_backend_instance
    if _global_backend_instance is None:
        _global_backend_instance = ClaudeCodeBackend()
    return _global_backend_instance


def reset_global_backend() -> None:
    """Tear down the global backend (closes all sessions). For tests / shutdown."""
    global _global_backend_instance
    if _global_backend_instance is not None:
        _global_backend_instance.close_all()
        _global_backend_instance = None

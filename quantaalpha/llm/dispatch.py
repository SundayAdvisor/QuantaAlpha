"""
DispatchingBackend — wraps a primary LLM backend and a chain of fallbacks.
On rate-limit / auth errors from the primary, fails over to the next backend
and keeps it as the active one for the rest of the run (no automatic retry of
primary; the primary stays cold until cooldown expires).

This lets QuantaAlpha use the Claude Code subscription as the primary path
while transparently falling back to the Anthropic API or an OpenAI-compatible
endpoint when the subscription budget is exhausted.
"""

from __future__ import annotations

from typing import Any

from quantaalpha.log import logger


class DispatchingBackend:
    def __init__(self, primary: Any, fallbacks: list[Any] | None = None) -> None:
        self._primary = primary
        self._fallbacks: list[Any] = list(fallbacks or [])
        self._active = primary
        self._failover_count = 0

    # The methods QuantaAlpha actually calls. We don't use __getattr__-only
    # delegation because we want explicit failover for the call methods and
    # plain pass-through for everything else.

    def build_messages_and_create_chat_completion(
        self, *args: Any, **kwargs: Any
    ) -> str:
        return self._with_failover(
            "build_messages_and_create_chat_completion", *args, **kwargs
        )

    def build_messages_and_calculate_token(self, *args: Any, **kwargs: Any) -> int:
        # Token counting is local-only (heuristic or tiktoken); no failover needed.
        return self._active.build_messages_and_calculate_token(*args, **kwargs)

    def build_chat_session(self, *args: Any, **kwargs: Any) -> Any:
        return self._active.build_chat_session(*args, **kwargs)

    def create_embedding(self, *args: Any, **kwargs: Any) -> Any:
        # Embeddings always go to a non-Claude backend if configured; if the
        # active backend doesn't support them, surface the NotImplementedError.
        return self._active.create_embedding(*args, **kwargs)

    # Pass-through for any other attribute the caller might touch
    def __getattr__(self, name: str) -> Any:
        return getattr(self._active, name)

    # ── Internals ──────────────────────────────────────────────────────

    def _with_failover(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        from quantaalpha.llm.claude_code_backend import (
            ClaudeCodeRateLimitError,
            ClaudeCodeSessionUnavailableError,
        )

        try:
            method = getattr(self._active, method_name)
            return method(*args, **kwargs)
        except (
            ClaudeCodeRateLimitError,
            ClaudeCodeSessionUnavailableError,
        ) as exc:
            if not self._fallbacks:
                logger.error(
                    f"[Dispatch] primary backend exhausted "
                    f"({type(exc).__name__}); no fallbacks configured."
                )
                raise

            previous = type(self._active).__name__
            self._active = self._fallbacks.pop(0)
            self._failover_count += 1
            new = type(self._active).__name__
            logger.warning(
                f"[Dispatch] failover #{self._failover_count}: "
                f"{previous} -> {new} (reason: {type(exc).__name__}: {exc})"
            )

            method = getattr(self._active, method_name)
            return method(*args, **kwargs)

    @property
    def failover_count(self) -> int:
        return self._failover_count

    @property
    def active_backend_name(self) -> str:
        return type(self._active).__name__

    def stats(self) -> dict[str, Any]:
        primary_stats = (
            self._primary.stats() if hasattr(self._primary, "stats") else {}
        )
        return {
            "active": self.active_backend_name,
            "failovers": self._failover_count,
            "fallbacks_remaining": len(self._fallbacks),
            "primary_stats": primary_stats,
        }

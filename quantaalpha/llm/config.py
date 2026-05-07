"""
QuantaAlpha LLM configuration.

All LLM-related settings; loaded from env via Pydantic-settings (e.g. CHAT_MODEL).
"""

from __future__ import annotations

from pathlib import Path

from quantaalpha.core.conf import ExtendedBaseSettings


class LLMSettings(ExtendedBaseSettings):
    log_llm_chat_content: bool = True
    max_retry: int = 30
    retry_wait_seconds: int = 15
    dump_chat_cache: bool = False
    use_chat_cache: bool = False
    dump_embedding_cache: bool = False
    use_embedding_cache: bool = False
    prompt_cache_path: str = str(Path.cwd() / "prompt_cache.db")
    max_past_message_include: int = 10

    use_auto_chat_cache_seed_gen: bool = False
    init_chat_cache_seed: int = 42

    openai_api_key: str = ""
    openai_base_url: str = ""
    chat_openai_api_key: str = ""
    chat_model: str = "gpt-4-turbo"
    reasoning_model: str = ""
    chat_max_tokens: int = 3000
    chat_temperature: float = 0.5
    chat_stream: bool = True
    chat_seed: int | None = None
    chat_frequency_penalty: float = 0.0
    chat_presence_penalty: float = 0.0
    chat_token_limit: int = 100000
    default_system_prompt: str = "You are an AI assistant who helps to answer user's questions."
    factor_mining_timeout: int = 999999

    # Embedding
    embedding_openai_api_key: str = ""
    embedding_model: str = ""
    embedding_max_str_num: int = 3
    embedding_batch_wait_seconds: float = 2.0
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    # Azure (optional)
    use_azure: bool = False
    chat_use_azure_token_provider: bool = False
    embedding_use_azure_token_provider: bool = False
    managed_identity_client_id: str | None = None
    chat_azure_api_base: str = ""
    chat_azure_api_version: str = ""
    embedding_azure_api_base: str = ""
    embedding_azure_api_version: str = ""

    # Offline/endpoint (rarely used)
    use_llama2: bool = False
    use_gcr_endpoint: bool = False

    chat_model_map: str = "{}"

    # ── Claude Code subscription path (claude-agent-sdk) ────────────
    # llm_provider: "openai" (default OpenAI-compatible), "claude_code"
    # (route through local Claude Code session — uses Max subscription),
    # or "anthropic" (direct Anthropic API — pay per token).
    llm_provider: str = "openai"

    # claude_code: max query() calls per session before opening a fresh one.
    # Sessions accumulate context; rotating prevents unbounded prompt growth.
    claude_code_max_turns_per_session: int = 30

    # claude_code: cooldown after a rate-limit-classified error before
    # the dispatcher retries the primary backend (seconds).
    claude_code_rate_limit_cooldown: int = 300

    # claude_code: fallback chain when subscription is exhausted.
    #   "anthropic" -> use Anthropic API direct (pay per token)
    #   "openai"    -> use the OpenAI-compatible config below
    #   "none"      -> no fallback; raise on rate limit
    claude_code_fallback: str = "anthropic"

    # claude_code: which Claude model the session should use. None = let
    # the local Claude Code default take over. Otherwise pass through to
    # ClaudeAgentOptions(model=...).
    claude_code_model: str | None = None

    # claude_code: bypass FS/Bash/Web tool permission prompts. Always set
    # because we want pure inference, no tool calls.
    claude_code_disable_tools: bool = True

    # ── Anthropic API direct (used as claude_code fallback or standalone) ──
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"


LLM_SETTINGS = LLMSettings()

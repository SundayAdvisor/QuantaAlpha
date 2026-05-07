"""
Claude Code SDK smoke test.

Run this BEFORE attempting a QuantaAlpha experiment with LLM_PROVIDER=claude_code.
Verifies that:
  1. The claude-agent-sdk package is installed correctly
  2. Your local Claude Code session is authenticated
  3. A round-trip query() call works end-to-end
  4. Multi-turn (session) continuation works
  5. ClaudeCodeBackend (the QuantaAlpha wrapper) works

Usage:
    python scratch/claude_smoke.py

Expected output: 5 PASS lines and a final "All checks passed".
If any check fails, the rest of the integration won't work either — fix that
first.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path


def header(label: str) -> None:
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def pass_(msg: str) -> None:
    print(f"PASS: {msg}")


# ── 1. SDK import ──────────────────────────────────────────────────────────


def check_import() -> None:
    header("1. Importing claude-agent-sdk")
    try:
        import claude_agent_sdk  # noqa: F401
        from claude_agent_sdk import (  # noqa: F401
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            TextBlock,
            query,
        )
    except ImportError as exc:
        fail(
            f"claude-agent-sdk not installed: {exc}\n"
            "Run: pip install claude-agent-sdk"
        )
    pass_("claude-agent-sdk imported")


# ── 2. Single one-shot query ───────────────────────────────────────────────


def check_oneshot() -> None:
    header("2. One-shot query (no session)")

    async def go() -> str:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            TextBlock,
            query,
        )

        options = ClaudeAgentOptions(allowed_tools=[])
        chunks: list[str] = []
        async for msg in query(
            prompt="Reply with exactly the four characters: PONG",
            options=options,
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
        return "".join(chunks).strip()

    try:
        result = asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        fail(
            f"one-shot query failed: {exc}\n"
            "Most likely: you are not logged in. Run `claude login` (or open "
            "Claude Code and sign in)."
        )

    print(f"     response: {result!r}")
    if "PONG" not in result.upper():
        fail(f"unexpected response: {result!r}")
    pass_("one-shot query succeeded")


# ── 3. Multi-turn session ──────────────────────────────────────────────────


def check_session() -> None:
    header("3. Multi-turn session (context continuation)")

    async def go() -> tuple[str, str]:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ClaudeSDKClient,
            TextBlock,
        )

        options = ClaudeAgentOptions(allowed_tools=[])
        async with ClaudeSDKClient(options=options) as client:
            await client.query("My favourite number is 42. Reply with just OK.")
            first_chunks: list[str] = []
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            first_chunks.append(block.text)

            await client.query(
                "What number did I just say? Reply with only the number, nothing else."
            )
            second_chunks: list[str] = []
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            second_chunks.append(block.text)

        return "".join(first_chunks).strip(), "".join(second_chunks).strip()

    try:
        first, second = asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        fail(f"multi-turn session failed: {exc}")

    print(f"     turn 1: {first!r}")
    print(f"     turn 2: {second!r}")
    if "42" not in second:
        fail(
            "context not preserved across turns; expected '42' in second response."
        )
    pass_("multi-turn session preserves context")


# ── 4. ClaudeCodeBackend (the QuantaAlpha wrapper) ─────────────────────────


def check_quantaalpha_backend() -> None:
    header("4. ClaudeCodeBackend wrapper")

    # Make QuantaAlpha importable when running from scratch/.
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    try:
        from quantaalpha.llm.claude_code_backend import (
            ClaudeCodeBackend,
            set_session_key,
            reset_session_key,
        )
    except ImportError as exc:
        traceback.print_exc()
        fail(f"could not import ClaudeCodeBackend: {exc}")

    backend = ClaudeCodeBackend(model=None, max_turns_per_session=10)
    token = set_session_key("smoke_test_session")
    try:
        out1 = backend.build_messages_and_create_chat_completion(
            user_prompt="My secret word is BANANA. Reply with exactly: noted.",
        )
        print(f"     turn 1: {out1!r}")
        out2 = backend.build_messages_and_create_chat_completion(
            user_prompt="What was my secret word? Reply with the single word in caps, nothing else.",
        )
        print(f"     turn 2: {out2!r}")
        if "BANANA" not in out2.upper():
            fail("ClaudeCodeBackend did not preserve session context")
    finally:
        reset_session_key(token)
        backend.close_all()
    pass_("ClaudeCodeBackend session reuse works")


# ── 5. JSON-mode round trip ────────────────────────────────────────────────


def check_json_mode() -> None:
    header("5. JSON-mode prompt")

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))

    from quantaalpha.llm.claude_code_backend import ClaudeCodeBackend

    backend = ClaudeCodeBackend(max_turns_per_session=5)
    try:
        raw = backend.build_messages_and_create_chat_completion(
            user_prompt=(
                'Output a JSON object with exactly this shape: '
                '{"directions": ["a", "b"]}'
            ),
            json_mode=True,
            session_key="smoke_json",
        )
        print(f"     raw: {raw!r}")

        # Try the project's robust parser.
        from quantaalpha.llm.client import robust_json_parse

        parsed = robust_json_parse(raw)
        print(f"     parsed: {parsed}")
        if "directions" not in parsed or not isinstance(parsed["directions"], list):
            fail("response did not contain expected 'directions' list")
    finally:
        backend.close_all()
    pass_("JSON-mode prompt + parse round trip works")


# ── Driver ─────────────────────────────────────────────────────────────────


def main() -> None:
    print("Claude Code SDK smoke test")
    print("Project: QuantaAlpha")

    check_import()
    check_oneshot()
    check_session()
    check_quantaalpha_backend()
    check_json_mode()

    print("\n" + "=" * 60)
    print("All checks passed. You can now run a QuantaAlpha experiment with")
    print("  LLM_PROVIDER=claude_code")
    print("=" * 60)


if __name__ == "__main__":
    main()

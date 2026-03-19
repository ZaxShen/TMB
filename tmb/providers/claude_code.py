"""ChatClaudeCode: LangChain BaseChatModel wrapper for the Claude Code CLI."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Iterator, List, Optional

from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tmb.config import LLMConnectionError


class ChatClaudeCode(BaseChatModel):
    """LangChain-compatible chat model that delegates to the Claude Code CLI.

    Uses ``claude -p --output-format json`` for non-interactive prompting.
    Claude Code manages its own tool execution, so ``bind_tools`` is a no-op.
    """

    model: str = "sonnet"
    temperature: float = 0
    timeout: int = 300
    disallowed_tools: List[str] = []
    allowed_tools: Optional[List[str]] = None

    @property
    def _llm_type(self) -> str:
        return "claude-code"

    # ------------------------------------------------------------------
    # Message formatting helpers
    # ------------------------------------------------------------------

    def _format_messages(self, messages: List[BaseMessage]) -> tuple[str, str]:
        """Split messages into (system_prompt, user_prompt).

        System messages are concatenated into a single string.
        All other messages are serialised into a single prompt string:
        - A lone HumanMessage is used verbatim.
        - Multiple messages are labelled by role.
        """
        system_parts: list[str] = []
        non_system: list[BaseMessage] = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                system_parts.append(content)
            else:
                non_system.append(msg)

        system_prompt = "\n\n".join(system_parts)

        # Single HumanMessage → use content directly
        if len(non_system) == 1 and isinstance(non_system[0], HumanMessage):
            content = non_system[0].content
            user_prompt = content if isinstance(content, str) else str(content)
        else:
            parts: list[str] = []
            for msg in non_system:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if isinstance(msg, HumanMessage):
                    parts.append(content)
                elif isinstance(msg, AIMessage):
                    parts.append(f"[Assistant]: {content}")
                else:
                    # ToolMessage and anything else
                    parts.append(f"[Tool Result]: {content}")
            user_prompt = "\n".join(parts)

        return system_prompt, user_prompt

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Run the Claude Code CLI and return a ChatResult."""
        system_prompt, user_prompt = self._format_messages(messages)

        cmd: list[str] = [
            "claude", "-p", user_prompt,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
        ]

        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        if self.model:
            cmd += ["--model", self.model]
        if self.allowed_tools is not None:
            cmd += ["--tools", ",".join(self.allowed_tools)]
        if self.disallowed_tools:
            cmd += ["--disallowed-tools"] + self.disallowed_tools

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise LLMConnectionError(
                "Claude Code CLI not found. Install it: https://docs.anthropic.com/en/docs/claude-code"
            )
        except subprocess.TimeoutExpired:
            raise LLMConnectionError(
                f"Claude Code timed out after {self.timeout}s. "
                "Try increasing the 'timeout' field on ChatClaudeCode."
            )

        if proc.returncode != 0:
            raise LLMConnectionError(
                f"Claude Code error (exit {proc.returncode}): {proc.stderr[:500]}"
            )

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMConnectionError(
                f"Claude Code returned invalid JSON. "
                f"stdout length={len(proc.stdout)}, "
                f"first 500 chars={proc.stdout[:500]!r}, "
                f"error={exc}"
            )

        if data.get("is_error"):
            raise LLMConnectionError(
                f"Claude Code error: {data.get('result', 'unknown')}"
            )

        text = data.get("result", "")
        usage = data.get("usage", {})
        metadata: dict[str, Any] = {
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            "cost_usd": data.get("total_cost_usd", 0),
            "session_id": data.get("session_id", ""),
            "stop_reason": data.get("stop_reason", ""),
        }

        message = AIMessage(content=text, response_metadata=metadata)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    # ------------------------------------------------------------------
    # Tool binding (no-op)
    # ------------------------------------------------------------------

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ChatClaudeCode":
        """No-op: Claude Code uses its own built-in tools."""
        return self

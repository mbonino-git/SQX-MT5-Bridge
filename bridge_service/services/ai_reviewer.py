"""AI Provider Router for MQL5 code review and compilation error fixing.

Uses OpenAI-compatible chat completions API, which works with:
- OpenAI, LM Studio, vLLM, SGLang, Claude (via compatibility layer), etc.
"""

import re
from typing import Any

import httpx

from models import AIProvider


# ── Custom Exception ─────────────────────────────────────────────


class AIReviewError(Exception):
    """Raised when an AI review or fix request fails."""


# ── Default Prompts ──────────────────────────────────────────────

DEFAULT_REVIEW_SYSTEM_PROMPT = """\
You are an MQL5 expert. Review this StrategyQuant X generated \
Expert Advisor code. Fix common issues:
- Missing #include directives
- Deprecated function calls
- Incorrect lot sizing calculations
- Missing error handling
- Wrong exit logic
Return only the fixed code, no explanations."""

DEFAULT_FIX_SYSTEM_PROMPT = """\
This MQL5 code has compilation errors. Fix them.
Return only the fixed code, no explanations."""


# ── AIReviewer Class ────────────────────────────────────────────


class AIReviewer:
    """Routes AI requests to the configured provider using OpenAI-compatible API."""

    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider
        self.base_url = provider.base_url or ""
        self.api_key = provider.api_key
        self.model = provider.model or "gpt-4"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

    # ── Public API ──────────────────────────────────────────────

    async def review_code(
        self,
        code: str,
        system_prompt: str | None = None,
    ) -> str:
        """Pre-review SQX-generated MQL5 code and fix common issues.

        Args:
            code: The MQL5 source code to review.
            system_prompt: Optional override for the system prompt.

        Returns:
            The fixed code as a string.

        Raises:
            AIReviewError: If the API call fails.
        """
        prompt = system_prompt or DEFAULT_REVIEW_SYSTEM_PROMPT
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": code},
        ]
        raw_response = await self._call_api(messages)
        return self._extract_code(raw_response)

    async def fix_errors(
        self,
        code: str,
        errors: str,
        system_prompt: str | None = None,
    ) -> str:
        """Fix MQL5 compilation errors using AI.

        Args:
            code: The current MQL5 source code.
            errors: The metaeditor64.exe compilation error output.
            system_prompt: Optional override for the system prompt.

        Returns:
            The fixed code as a string.

        Raises:
            AIReviewError: If the API call fails.
        """
        prompt = system_prompt or DEFAULT_FIX_SYSTEM_PROMPT
        user_message = (
            f"Errors:\n{errors}\n\nCode:\n{code}"
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ]
        raw_response = await self._call_api(messages)
        return self._extract_code(raw_response)

    # ── Response Parser ─────────────────────────────────────────

    def _extract_code(self, response: str) -> str:
        """Extract code from an AI response that may contain markdown fences or explanations.

        Priority:
        1. ````mql5` fenced block
        2. ````cpp` fenced block
        3. ````c` fenced block
        4. Any last fenced block
        5. Plain text (stripped)
        """
        response = response.strip()

        # Try language-specific fences first (in priority order)
        for lang in ("mql5", "cpp", "c"):
            pattern = rf"```(?:{lang})\s*\n(.*?)```"
            match = re.search(pattern, response, re.DOTALL)
            if match:
                return match.group(1).strip()

        # Fallback: grab the last fenced block of any kind
        all_blocks = re.findall(r"```\w*\s*\n(.*?)```", response, re.DOTALL)
        if all_blocks:
            return all_blocks[-1].strip()

        # No fences found — return the raw response stripped
        return response

    # ── Internal HTTP ───────────────────────────────────────────

    async def _call_api(self, messages: list[dict[str, str]]) -> str:
        """Send a chat completions request to the provider.

        Returns:
            The assistant's message content.

        Raises:
            AIReviewError: On HTTP errors or malformed responses.
        """
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }

        try:
            response = await self.client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AIReviewError(
                f"AI provider returned HTTP {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise AIReviewError(
                f"Failed to connect to AI provider at {url}: {exc}"
            ) from exc

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIReviewError(
                f"Unexpected response format from AI provider: {data}"
            ) from exc

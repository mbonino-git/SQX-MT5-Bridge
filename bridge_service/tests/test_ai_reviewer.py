"""Tests for AIReviewer: AI provider router for MQL5 code review and fixing."""

import os
import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Adjust import path for tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import AIProvider


# ── AIReviewer Initialization Tests ─────────────────────────────


class TestAIReviewerInit:
    """Tests for AIReviewer initialization with AIProvider config."""

    def test_create_with_openai_provider(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="OpenAI",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4",
        )
        reviewer = AIReviewer(provider)
        assert reviewer.provider == provider
        assert reviewer.base_url == "https://api.openai.com/v1"
        assert reviewer.api_key == "sk-test"
        assert reviewer.model == "gpt-4"

    def test_create_with_lm_studio_provider(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="LM Studio",
            type="openai-compatible",
            base_url="http://localhost:1234/v1",
            model="local-model",
        )
        reviewer = AIReviewer(provider)
        assert reviewer.base_url == "http://localhost:1234/v1"
        assert reviewer.model == "local-model"
        assert reviewer.api_key is None  # LM Studio doesn't need auth

    def test_create_with_claude_provider(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="Claude",
            type="claude",
            api_key="sk-ant-test",
            model="claude-3-opus",
        )
        reviewer = AIReviewer(provider)
        assert reviewer.api_key == "sk-ant-test"
        assert reviewer.model == "claude-3-opus"

    def test_provider_without_model_uses_default(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Custom", type="openai-compatible", base_url="http://localhost:8080/v1")
        reviewer = AIReviewer(provider)
        assert reviewer.model == "gpt-4"  # default fallback


# ── Prompt Construction Tests ────────────────────────────────────


class TestReviewPromptConstruction:
    """Tests for the review_code prompt construction."""

    def test_review_prompt_contains_code(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)
        prompt = reviewer._build_review_prompt("int OnInit() { return(INIT_SUCCEEDED); }")
        assert "int OnInit() { return(INIT_SUCCEEDED); }" in prompt
        assert "MQL5" in prompt
        assert "Expert Advisor" in prompt

    def test_review_prompt_uses_default_system_prompt(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)
        prompt = reviewer._build_review_prompt("code here")
        assert "#include" in prompt
        assert "deprecated" in prompt.lower()
        assert "lot sizing" in prompt.lower()


class TestFixPromptConstruction:
    """Tests for the fix_errors prompt construction."""

    def test_fix_prompt_contains_errors_and_code(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)
        errors = "1:1 error: undeclared identifier 'x'"
        code = "void OnTick() { x = 1; }"
        prompt = reviewer._build_fix_prompt(code, errors)
        assert errors in prompt
        assert code in prompt
        assert "compilation errors" in prompt.lower()


# ── Response Parsing Tests ───────────────────────────────────────


class TestResponseParsing:
    """Tests for extracting code from AI responses."""

    def test_extract_code_from_markdown_fenced(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)
        response = '```mql5\nvoid OnTick() {\n    Print("hello");\n}\n```'
        code = reviewer._extract_code(response)
        assert 'Print("hello")' in code
        assert "```" not in code

    def test_extract_code_from_plain_response(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)
        response = "void OnTick() {\n    Print(\"hello\");\n}"
        code = reviewer._extract_code(response)
        assert code == response.strip()

    def test_extract_code_strips_explanations(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)
        response = "Here is the fixed code:\n```mql5\nvoid OnTick() {}\n```\nThis fixes the issue."
        code = reviewer._extract_code(response)
        assert "void OnTick()" in code
        assert "Here is the fixed code" not in code

    def test_extract_code_c_multiple_blocks(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)
        response = '```cpp\nvoid OnTick() {}\n```\n\n```mql5\nvoid OnTick() { Print("v2"); }\n```'
        code = reviewer._extract_code(response)
        # Should prefer mql5 block if present, else last block
        assert "Print" in code


# ── Async API Call Tests (Mocked) ────────────────────────────────


class TestReviewCodeAsync:
    """Tests for review_code method with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_review_code_sends_correct_request(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="Test",
            type="openai-compatible",
            base_url="http://localhost:1234/v1",
            api_key="sk-test",
            model="test-model",
        )
        reviewer = AIReviewer(provider)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "```mql5\nvoid OnTick() { Print(\"fixed\"); }\n```"}}]
        }

        with patch.object(reviewer.client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await reviewer.review_code("void OnTick() {}")
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://localhost:1234/v1/chat/completions"
            assert call_args[1]["headers"]["Authorization"] == "sk-test"
            assert "test-model" in str(call_args[1]["json"])
            assert result == 'void OnTick() { Print("fixed"); }'

    @pytest.mark.asyncio
    async def test_review_code_handles_api_error(self):
        import httpx

        from services.ai_reviewer import AIReviewer, AIReviewError

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1", model="m")
        reviewer = AIReviewer(provider)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        # Build a real httpx.HTTPStatusError so our except clause catches it
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        http_response = httpx.Response(500, request=request, text="Internal Server Error")
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=request, response=http_response,
        )

        with patch.object(reviewer.client, "post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(AIReviewError):
                await reviewer.review_code("code")

    @pytest.mark.asyncio
    async def test_fix_errors_sends_correct_request(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="Test",
            type="openai-compatible",
            base_url="http://localhost:1234/v1",
            api_key="sk-test",
            model="test-model",
        )
        reviewer = AIReviewer(provider)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "void OnTick() { /* fixed */ }"}}]
        }

        with patch.object(reviewer.client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await reviewer.fix_errors("void OnTick() {}", "1:1 error: undeclared 'x'")
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            messages = call_args[1]["json"]["messages"]
            assert any("compilation errors" in m["content"].lower() for m in messages)
            assert result == "void OnTick() { /* fixed */ }"

    @pytest.mark.asyncio
    async def test_review_code_no_api_key(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(name="Test", type="openai-compatible", base_url="http://localhost:1234/v1")
        reviewer = AIReviewer(provider)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "code"}}]
        }

        with patch.object(reviewer.client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await reviewer.review_code("code")
            headers = mock_post.call_args[1]["headers"]
            assert "Authorization" not in headers  # no auth header when no key


# ── Provider Type Routing Tests ──────────────────────────────────


class TestProviderRouting:
    """Tests that different provider types use correct API endpoints."""

    @pytest.mark.asyncio
    async def test_openai_compatible_uses_chat_completions(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="LM Studio",
            type="openai-compatible",
            base_url="http://localhost:1234/v1",
            model="local",
        )
        reviewer = AIReviewer(provider)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

        with patch.object(reviewer.client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await reviewer.review_code("code")
            url = mock_post.call_args[0][0]
            assert "/chat/completions" in url

    @pytest.mark.asyncio
    async def test_openai_uses_chat_completions(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="OpenAI",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-4",
        )
        reviewer = AIReviewer(provider)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

        with patch.object(reviewer.client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await reviewer.review_code("code")
            url = mock_post.call_args[0][0]
            assert url.endswith("/chat/completions")

    @pytest.mark.asyncio
    async def test_claude_uses_chat_completions(self):
        from services.ai_reviewer import AIReviewer

        provider = AIProvider(
            name="Claude",
            type="claude",
            api_key="sk-ant-test",
            model="claude-3-opus",
        )
        reviewer = AIReviewer(provider)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

        with patch.object(reviewer.client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await reviewer.review_code("code")
            url = mock_post.call_args[0][0]
            assert "/chat/completions" in url

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import create_access_token
from app.core.config import Settings
from app.llm.pii import redact_pii
from app.llm.router import LLMRouter
from tests.conftest import make_test_app


def test_pii_redactor_scrubs_sensitive_tokens_only() -> None:
    sample = (
        "Pay PO-2026-1001 ($24000.00) to vendor@cloudcore.io, SSN 123-45-6789, "
        "EIN 84-2104911, phone (415) 555-0199, routing 121000358, "
        "account 9876543210, card 4111 1111 1111 1111."
    )
    res = redact_pii(sample)
    assert "vendor@cloudcore.io" not in res.redacted_text
    assert "123-45-6789" not in res.redacted_text
    assert "84-2104911" not in res.redacted_text
    assert "555-0199" not in res.redacted_text
    assert "121000358" not in res.redacted_text
    assert "9876543210" not in res.redacted_text
    assert "4111 1111 1111 1111" not in res.redacted_text
    # Non-PII business identifiers remain intact
    assert "PO-2026-1001" in res.redacted_text
    assert "$24000.00" in res.redacted_text
    assert res.total_redactions == 7


@pytest.mark.asyncio
async def test_llm_router_redacts_cloud_prompt_and_falls_back() -> None:
    seen_prompts: list[str] = []

    class FakeGemini:
        provider_name = "gemini"
        model_name = "gemini-test"

        async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
            _ = (system_prompt, task_type)
            seen_prompts.append(prompt)
            return "Cloud summary"

    cfg = Settings(
        llm_default_provider="gemini",
        llm_fallback_providers="mock",
        llm_redact_pii_for_cloud=True,
    )
    router = LLMRouter(cfg)
    router.adapters["gemini"] = FakeGemini()

    res = await router.generate("Contact alice@corp.com SSN 123-45-6789 for INV-1.")
    assert res.provider == "gemini"
    assert res.pii_redacted is True
    assert res.redaction_count == 2
    assert "alice@corp.com" not in seen_prompts[0]
    assert "[REDACTED_EMAIL]" in seen_prompts[0]
    assert "[REDACTED_SSN]" in seen_prompts[0]

    # When cloud adapter errors, router falls back cleanly to deterministic mock
    class FailingGemini:
        provider_name = "gemini"
        model_name = "gemini-test"

        async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
            _ = (prompt, system_prompt, task_type)
            raise RuntimeError("Upstream timeout")

    router.adapters["gemini"] = FailingGemini()
    fallback_res = await router.generate("Summarize variance", task_type="three_way_match")
    assert fallback_res.provider == "mock"
    assert "3-way match" in fallback_res.content


@pytest.mark.asyncio
async def test_bearer_token_auth_and_production_gate(tmp_path: Path) -> None:
    prod_secret = "a-very-secure-production-secret-key-32-bytes"
    prod_app = make_test_app(
        tmp_path,
        app_env="production",
        auth_secret_key=prod_secret,
        cors_origins="https://finops.example.com",
    )
    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unauth = await client.get("/api/v1/auth/me")
        assert unauth.status_code == 401

        dev_token = await client.post(
            "/api/v1/auth/token",
            json={"email": "c@example.com", "role": "controller"},
        )
        assert dev_token.status_code == 403

        token = create_access_token("c@example.com", "controller", prod_secret)
        authed = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert authed.status_code == 200
        assert authed.json()["email"] == "c@example.com"
        assert authed.json()["role"] == "controller"

from pydantic import BaseModel

from app.llm.embeddings import EmbeddingService, cosine_similarity

CHART_OF_ACCOUNTS: list[tuple[str, str, str]] = [
    (
        "6100-CLOUD",
        "Cloud & Infrastructure Hosting",
        "cloud gpu server node hosting compute aws gcp kubernetes storage bandwidth",
    ),
    (
        "5200-FREIGHT",
        "Freight & Logistics",
        "freight shipping logistics cargo carrier transport warehouse delivery pallet",
    ),
    (
        "1500-EQUIPMENT",
        "Capital Hardware & Equipment",
        "hardware laptop workstation dock server rack monitor equipment device",
    ),
    (
        "6400-SEC",
        "Security & Compliance Audits",
        "security soc2 penetration audit compliance vulnerability identity firewall",
    ),
    (
        "6300-ADVISORY",
        "Professional & Advisory Services",
        "advisory consulting legal accounting audit fractional cfo retainer services",
    ),
    (
        "6200-SOFTWARE",
        "SaaS & Software Subscriptions",
        "software saas license seats subscription issue tracker crm erp productivity",
    ),
    (
        "6500-MEALS",
        "Meals & Team Hospitality",
        "meals lunch dinner restaurant catering coffee bistro steakhouse dining",
    ),
    (
        "6600-TRAVEL",
        "Corporate Travel & Lodging",
        "travel airfare flight hotel lodging airline uber taxi rail mileage",
    ),
    (
        "6700-FACILITIES",
        "Office Lease & Facilities",
        "rent lease office facilities utilities maintenance workspace building",
    ),
    (
        "5000-AP",
        "General Accounts Payable",
        "general vendor supplies miscellaneous expense purchase order invoice",
    ),
]


class GLSuggestionOut(BaseModel):
    gl_account: str
    gl_name: str
    confidence: float
    reason: str


async def suggest_gl_account(
    *,
    description: str,
    vendor_name: str,
    default_gl: str | None,
    embedding_service: EmbeddingService,
) -> GLSuggestionOut:
    """Rank Chart-of-Accounts candidates via semantic embedding similarity."""
    query = f"{vendor_name} {description}".strip()
    query_vec, _ = await embedding_service.embed(query)

    best_code = default_gl or "5000-AP"
    best_name = "General Accounts Payable"
    best_score = 0.0

    for code, name, keywords in CHART_OF_ACCOUNTS:
        cat_vec, _ = await embedding_service.embed(f"{name} {keywords}")
        score = cosine_similarity(query_vec, cat_vec)
        if default_gl and code == default_gl:
            score += 0.15
        if score > best_score:
            best_score = score
            best_code = code
            best_name = name

    confidence = round(min(0.99, max(0.35, best_score + 0.30)), 2)
    reason = f"Matched '{query[:80]}' to {best_code} ({best_name})"
    return GLSuggestionOut(
        gl_account=best_code,
        gl_name=best_name,
        confidence=confidence,
        reason=reason,
    )

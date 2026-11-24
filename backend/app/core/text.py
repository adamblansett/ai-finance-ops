import re

_BANK_NOISE_RE = re.compile(
    r"\b(?:ACH\s+DEBIT|ACH\s+CREDIT|WIRE\s+TRANSFER|WIRE|POS\s+PURCHASE|POS|"
    r"DIRECT\s+DEBIT|PAYMENT\s+TO|PAYMENT\s+FROM|CHECK\s*#?\s*\d*|TXN|REF)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^A-Z0-9\s]+")
_SPACE_RE = re.compile(r"\s+")


def normalize_counterparty(raw: str) -> str:
    """Normalize bank memo or vendor/customer strings for deterministic matching."""
    upper = raw.upper()
    cleaned = _BANK_NOISE_RE.sub(" ", upper)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def counterparty_similarity(left: str, right: str) -> float:
    """Compute token similarity in [0.0, 1.0] between two normalized counterparty names."""
    norm_l = normalize_counterparty(left)
    norm_r = normalize_counterparty(right)
    if not norm_l or not norm_r:
        return 0.0
    if norm_l == norm_r:
        return 1.0
    if norm_l in norm_r or norm_r in norm_l:
        return 0.85

    stop_words = {"INC", "LLC", "CORP", "LTD", "CO", "THE", "AND", "OF"}
    tokens_l = {t for t in norm_l.split() if t not in stop_words and len(t) > 1}
    tokens_r = {t for t in norm_r.split() if t not in stop_words and len(t) > 1}
    if not tokens_l or not tokens_r:
        return 0.0
    intersection = len(tokens_l & tokens_r)
    union = len(tokens_l | tokens_r)
    return intersection / union if union > 0 else 0.0

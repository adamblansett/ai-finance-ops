from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

CONTROLLER_HEADERS = {
    "X-Actor-Email": "controller@test.local",
    "X-Actor-Role": "controller",
}
ANALYST_HEADERS = {
    "X-Actor-Email": "analyst@test.local",
    "X-Actor-Role": "analyst",
}


def make_test_app(tmp_path: Path, **overrides: Any) -> FastAPI:
    """Create an isolated FastAPI app backed by a per-test SQLite file."""
    db_file = tmp_path / "test_finops.db"
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        llm_default_provider="mock",
        auto_create_tables=True,
        seed_demo_data=False,
        **overrides,
    )
    return create_app(cfg)


def build_minimal_pdf(lines: list[str]) -> bytes:
    """Build a minimal valid single-page PDF containing extractable text lines."""
    escaped_ops = []
    for idx, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if idx == 0:
            escaped_ops.append(f"({safe}) Tj")
        else:
            escaped_ops.append(f"0 -16 Td ({safe}) Tj")
    stream_text = "BT /F1 11 Tf 50 740 Td " + " ".join(escaped_ops) + " ET"
    stream_bytes = stream_text.encode("latin-1")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        (
            b"4 0 obj\n<< /Type /Font /Subtype /Type1 "
            b"/BaseFont /Helvetica >>\nendobj\n"
        ),
        (
            f"5 0 obj\n<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin-1")
            + stream_bytes
            + b"\nendstream\nendobj\n"
        ),
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj in objects:
        offsets.append(len(buf))
        buf.extend(obj)

    xref_pos = len(buf)
    buf.extend(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    buf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.extend(f"{off:010d} 00000 n \n".encode("latin-1"))

    buf.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("latin-1")
    )
    return bytes(buf)

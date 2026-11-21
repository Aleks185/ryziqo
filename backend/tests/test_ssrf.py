"""Unit tests for anti-SSRF URL validation."""

from __future__ import annotations

import pytest

from app.scraper.ssrf import SSRFError, validate_public_url


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "file:///etc/passwd",
        "ftp://example.com/data",
        "http://localhost:8000/api/v1/health",
        "http://127.0.0.1:11434/api/tags",
        "http://[::1]:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/admin",
        "http://172.16.0.5/internal",
        "http://192.168.1.1/router",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://host.docker.internal:11434/",
        "https://user:pass@example.com/",
    ],
)
def test_ssrf_blocks_dangerous_urls(bad_url: str) -> None:
    with pytest.raises(SSRFError):
        validate_public_url(bad_url)


def test_ssrf_allows_public_ip_literal() -> None:
    assert validate_public_url("https://1.1.1.1/") == "https://1.1.1.1/"

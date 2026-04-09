"""
Threat Intelligence enrichment via AbuseIPDB.

Checks whether a given IP address is known to be malicious using the
AbuseIPDB public API (https://www.abuseipdb.com/).

Caching strategy:
  - Results are cached in Redis for 24 hours to stay within the free-tier
    rate limit (1 000 checks/day).
  - If Redis is unavailable, results are returned without caching.

Required environment variable:
  ABUSEIPDB_API_KEY  — API key from https://www.abuseipdb.com/account/api

Usage:
    from services.threat_intel import check_ip
    result = await check_ip("1.2.3.4", redis_client)
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx

from core.observability import THREAT_INTEL_HITS_TOTAL

_API_KEY: str = os.getenv("ABUSEIPDB_API_KEY", "")
_ABUSEIPDB_URL = "https://api.abuseipdb.com/api/v2/check"
_CACHE_TTL = 86_400          # 24 hours
_MALICIOUS_THRESHOLD = 25    # confidence score >= 25 → flagged as malicious
_REQUEST_TIMEOUT = 5.0       # seconds


def _cache_key(ip: str) -> str:
    return f"threat_intel:{ip}"


async def check_ip(
    ip: str,
    redis_client: Any,
    max_age_days: int = 90,
) -> dict:
    """
    Return an AbuseIPDB threat-intelligence report for *ip*.

    Args:
        ip:           IPv4 or IPv6 address to check.
        redis_client: Redis client instance (sync or async). Pass None to skip cache.
        max_age_days: Only consider reports filed within this many days (default 90).

    Returns:
        dict with keys:
            ip                    — queried IP address
            abuse_confidence_score — 0–100 (None if API unavailable)
            is_malicious          — True if score >= 25
            total_reports         — number of abuse reports
            country_code          — ISO 3166-1 alpha-2 country code
            usage_type            — e.g. "Data Center/Web Hosting/Transit"
            domain                — reverse-DNS domain
            cached                — True if result came from Redis cache
            error                 — error message if the API call failed
    """
    key = _cache_key(ip)

    # ── 1. Try cache ──────────────────────────────────────────────────────────
    if redis_client is not None:
        try:
            raw = redis_client.get(key)
            if raw:
                data = json.loads(raw)
                data["cached"] = True
                return data
        except Exception:
            pass  # Cache read failure is non-fatal

    # ── 2. Guard: API key required ────────────────────────────────────────────
    if not _API_KEY:
        return {
            "ip": ip,
            "abuse_confidence_score": None,
            "is_malicious": None,
            "total_reports": None,
            "country_code": None,
            "usage_type": None,
            "domain": None,
            "cached": False,
            "error": "ABUSEIPDB_API_KEY environment variable not set.",
        }

    # ── 3. Query AbuseIPDB ────────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(
                _ABUSEIPDB_URL,
                headers={
                    "Key": _API_KEY,
                    "Accept": "application/json",
                },
                params={
                    "ipAddress": ip,
                    "maxAgeInDays": max_age_days,
                    "verbose": "false",
                },
            )
            resp.raise_for_status()
            payload: dict = resp.json()["data"]

    except httpx.HTTPStatusError as exc:
        return {
            "ip": ip,
            "abuse_confidence_score": None,
            "is_malicious": None,
            "total_reports": None,
            "country_code": None,
            "usage_type": None,
            "domain": None,
            "cached": False,
            "error": f"AbuseIPDB API error: HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        return {
            "ip": ip,
            "abuse_confidence_score": None,
            "is_malicious": None,
            "total_reports": None,
            "country_code": None,
            "usage_type": None,
            "domain": None,
            "cached": False,
            "error": str(exc),
        }

    # ── 4. Build result ───────────────────────────────────────────────────────
    score: Optional[int] = payload.get("abuseConfidenceScore")
    is_malicious = (score is not None) and (score >= _MALICIOUS_THRESHOLD)

    result = {
        "ip": ip,
        "abuse_confidence_score": score,
        "is_malicious": is_malicious,
        "total_reports": payload.get("totalReports"),
        "country_code": payload.get("countryCode"),
        "usage_type": payload.get("usageType"),
        "domain": payload.get("domain"),
        "cached": False,
    }

    # ── 5. Increment Prometheus counter if malicious ──────────────────────────
    if is_malicious:
        THREAT_INTEL_HITS_TOTAL.labels(country=result["country_code"] or "unknown").inc()

    # ── 6. Store in cache ─────────────────────────────────────────────────────
    if redis_client is not None:
        try:
            cache_payload = {k: v for k, v in result.items() if k != "cached"}
            redis_client.setex(key, _CACHE_TTL, json.dumps(cache_payload))
        except Exception:
            pass  # Cache write failure is non-fatal

    return result

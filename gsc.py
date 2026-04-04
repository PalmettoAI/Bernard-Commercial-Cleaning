"""
gsc.py — Google Search Console API integration.

Fetches top keyword opportunities for a site:
  - High impressions, low CTR, position 5–30
  - These are queries Google already associates with the site
    but where the content isn't good enough to earn clicks yet.

Environment variables:
    GSC_CREDENTIALS   Required. Full JSON string of the service account key file.
    GSC_SITE_URL      Optional. Defaults to sc-domain:bernardjanitorial.com
                      Use sc-domain:yourdomain.com for domain properties.
"""

import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

GSC_SITE_URL = os.environ.get("GSC_SITE_URL", "sc-domain:bernardjanitorial.com")
TOKEN_URI    = "https://oauth2.googleapis.com/token"
SCOPE        = "https://www.googleapis.com/auth/webmasters.readonly"


def _get_access_token(creds: dict) -> str:
    """Exchange service account credentials for a short-lived access token using JWT."""
    import base64
    import hashlib
    import hmac
    import struct

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        USE_CRYPTOGRAPHY = True
    except ImportError:
        USE_CRYPTOGRAPHY = False

    now = int(time.time())
    header  = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss":   creds["client_email"],
        "scope": SCOPE,
        "aud":   TOKEN_URI,
        "iat":   now,
        "exp":   now + 3600,
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    h = b64url(json.dumps(header,  separators=(",", ":")).encode())
    p = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()

    if not USE_CRYPTOGRAPHY:
        raise EnvironmentError(
            "cryptography package required for GSC auth. "
            "Add 'cryptography' to your Dockerfile pip install."
        )

    private_key = serialization.load_pem_private_key(
        creds["private_key"].encode(),
        password=None,
        backend=default_backend(),
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{h}.{p}.{b64url(signature)}"

    # Exchange JWT for access token
    body = (
        f"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
        f"&assertion={jwt}"
    ).encode()

    req = urllib.request.Request(
        TOKEN_URI, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())

    if "access_token" not in data:
        raise RuntimeError(f"Token exchange failed: {data}")

    return data["access_token"]


def _query_search_analytics(token: str, site_url: str, start_date: str, end_date: str) -> list[dict]:
    """Pull query-level search analytics from GSC."""
    url = (
        "https://searchconsole.googleapis.com/webmasters/v3/sites/"
        + urllib.parse.quote(site_url, safe="")
        + "/searchAnalytics/query"
    )

    body = json.dumps({
        "startDate":  start_date,
        "endDate":    end_date,
        "dimensions": ["query"],
        "rowLimit":   500,
        "startRow":   0,
    }).encode()

    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        return data.get("rows", [])
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"GSC API error {e.code}: {error_body}")


def _score_opportunity(row: dict) -> float:
    """
    Score a query by opportunity value.
    High score = high impressions, low CTR, mid-range position (5-30).
    Position 1-4 = already ranking well, skip.
    Position 30+ = too far down to benefit from one post.
    """
    impressions = row.get("impressions", 0)
    clicks      = row.get("clicks", 0)
    ctr         = row.get("ctr", 0)
    position    = row.get("position", 100)

    if impressions < 20:
        return 0
    if position < 4 or position > 40:
        return 0

    # Sweet spot: position 5-20 is best (close enough to move up)
    position_score = max(0, 1 - abs(position - 12) / 20)
    missed_clicks  = impressions * (1 - ctr)

    return missed_clicks * position_score


def get_opportunities(site_url: str | None = None, top_n: int = 15) -> list[dict]:
    """
    Return top keyword opportunities from GSC for the last 90 days.

    Each item: { "query": str, "impressions": int, "clicks": int,
                 "ctr": float, "position": float, "score": float }
    """
    creds_json = os.environ.get("GSC_CREDENTIALS", "")
    if not creds_json:
        print("  [GSC] GSC_CREDENTIALS not set — skipping GSC topic targeting.")
        return []

    # Try JSON first, then base64-encoded JSON
    # (base64 is the recommended format to avoid Railway UI mangling special chars)
    try:
        creds = json.loads(creds_json)
    except json.JSONDecodeError:
        try:
            import base64
            creds = json.loads(base64.b64decode(creds_json.strip()).decode())
        except Exception:
            print("  [GSC] GSC_CREDENTIALS is not valid JSON or base64-encoded JSON — skipping.")
            return []

    site = site_url or GSC_SITE_URL

    try:
        print("  [GSC] Authenticating with Google...")
        token = _get_access_token(creds)

        end_date   = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=90)

        print(f"  [GSC] Fetching query data for {site} ({start_date} → {end_date})...")
        rows = _query_search_analytics(
            token, site,
            str(start_date), str(end_date),
        )
        print(f"  [GSC] {len(rows)} queries returned.")

        # Score and filter
        opportunities = []
        for row in rows:
            score = _score_opportunity(row)
            if score <= 0:
                continue
            query = row["keys"][0]
            # Skip branded queries
            if any(brand in query.lower() for brand in ["bernard", "bernardjanitorial"]):
                continue
            opportunities.append({
                "query":       query,
                "impressions": row.get("impressions", 0),
                "clicks":      row.get("clicks", 0),
                "ctr":         round(row.get("ctr", 0) * 100, 1),
                "position":    round(row.get("position", 0), 1),
                "score":       round(score, 1),
            })

        opportunities.sort(key=lambda x: x["score"], reverse=True)
        top = opportunities[:top_n]

        print(f"  [GSC] Top opportunity: '{top[0]['query']}' "
              f"({top[0]['impressions']} impressions, pos {top[0]['position']})" if top else "  [GSC] No opportunities found.")

        return top

    except Exception as e:
        print(f"  [GSC] Error fetching data: {e} — falling back to LLM topic selection.")
        return []

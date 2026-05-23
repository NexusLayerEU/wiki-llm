"""
SSO JWT Middleware for WikiLLM / WikiForge.
Validates Bearer tokens issued by AIIdentityServer using the shared JWT secret.
"""
import os
import time
from typing import Optional

import jwt
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SSO_JWT_SECRET = os.getenv(
    "SSO_JWT_SECRET",
    "nexuslayer-shared-sso-secret-change-in-production-64chars!!",
)
IDS_URL = os.getenv("IDENTITY_SERVER_URL", "http://192.168.68.111:8087")
PRODUCT_NAME = "wikillm"
TRIAL_DAYS_S = 7 * 24 * 60 * 60

bearer_scheme = HTTPBearer(auto_error=False)


def decode_sso_token(token: str) -> Optional[dict]:
    """Decode and validate an SSO JWT token. Returns claims or None if invalid."""
    try:
        return jwt.decode(token, SSO_JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None


def get_current_user_from_token(authorization: str) -> Optional[dict]:
    """Extract user info from Authorization header (Bearer <token>)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    return decode_sso_token(token)


def is_pro_active(claims: dict) -> bool:
    if claims.get("tier") != "PRO":
        return False
    expires = claims.get("planExpiresAt")
    return expires is None or expires > int(time.time() * 1000)


def is_trial_active(claims: dict) -> bool:
    started = claims.get("trialStartedAt", 0)
    return int(time.time() * 1000) < started + TRIAL_DAYS_S * 1000


async def consume_usage(token: str) -> bool:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{IDS_URL}/api/v1/usage/consume",
                json={"product": PRODUCT_NAME},
                headers={"Authorization": f"Bearer {token}"}
            )
            data = resp.json()
            return data.get("allowed", True)
    except Exception:
        return True  # fail open


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = credentials.credentials
    claims = decode_sso_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid token")
    request.state.sso_claims = claims
    request.state.sso_token = token
    return claims


async def require_action(request: Request) -> None:
    """Enforce usage limit on action endpoints (RAG queries, writes)."""
    claims = getattr(request.state, "sso_claims", None)
    token = getattr(request.state, "sso_token", None)
    if claims is None or token is None:
        return
    if is_pro_active(claims) or is_trial_active(claims):
        return
    allowed = await consume_usage(token)
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail="Daily limit reached. Upgrade to Pro — contact admin@nexuslayer.eu"
        )

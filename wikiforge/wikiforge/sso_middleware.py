"""
SSO JWT Middleware for WikiLLM / WikiForge.
Validates Bearer tokens issued by AIIdentityServer using the shared JWT secret.
Install: pip install PyJWT
"""
import os
from typing import Optional

import jwt

SSO_JWT_SECRET = os.getenv(
    "SSO_JWT_SECRET",
    "nexlayer-shared-sso-secret-change-in-production-64chars!!",
)
SSO_ALGORITHM = "HS256"
IDENTITY_SERVER_URL = os.getenv("IDENTITY_SERVER_URL", "http://192.168.68.111:3007")


def decode_sso_token(token: str) -> Optional[dict]:
    """Decode and validate an SSO JWT token. Returns claims or None if invalid."""
    try:
        payload = jwt.decode(token, SSO_JWT_SECRET, algorithms=[SSO_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user_from_token(authorization: str) -> Optional[dict]:
    """Extract user info from Authorization header (Bearer <token>)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    return decode_sso_token(token)

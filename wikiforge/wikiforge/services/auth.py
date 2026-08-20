"""Request authentication.

Wraps the surviving `sso_middleware` so routers depend on one small thing. With
`WIKIFORGE_REQUIRE_AUTH` off every caller is an anonymous MAX user, which is how
local development runs; the deployed service turns it on.
"""
from dataclasses import dataclass

from fastapi import Header, HTTPException

from ..config import get_settings
from ..sso_middleware import decode_sso_token


@dataclass(frozen=True)
class CurrentUser:
    email: str
    name: str
    tier: str
    role: str

    @property
    def is_anonymous(self) -> bool:
        return self.email == "anonymous"


ANONYMOUS = CurrentUser(email="anonymous", name="Anonymous", tier="MAX", role="USER")


async def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    settings = get_settings()

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token:
        if settings.require_auth:
            raise HTTPException(status_code=401, detail="A NexusLayer SSO token is required.")
        return ANONYMOUS

    claims = decode_sso_token(token)
    if claims is None:
        # An invalid token is rejected even when auth is optional: presenting a bad
        # credential is a different situation from presenting none.
        raise HTTPException(status_code=401, detail="That SSO token is not valid.")

    return CurrentUser(
        # NexusLayer puts the email in `sub`, not an `email` claim.
        email=str(claims.get("sub") or "unknown"),
        name=str(claims.get("name") or claims.get("sub") or "User"),
        tier=str(claims.get("tier") or "FREE"),
        role=str(claims.get("role") or "USER"),
    )

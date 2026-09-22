"""
auth.py — API key authentication dependency.

Every ingest and query route requires the caller to supply an
  X-API-Key: <value>
HTTP header whose value must exactly match the API_KEY environment variable.

Security note
-------------
The dashboard's JavaScript reads the key from the browser's localStorage
and sends it as a request header.  This means anyone who opens DevTools can
see the key.  For a single-user, single-device college project this is an
acceptable trade-off: the key still prevents anonymous Internet traffic from
writing garbage into the database or scraping your posture data.

If you later need stronger security: move to a server-side reverse-proxy that
injects the header (so it never reaches the browser), or implement JWT-based
user authentication.
"""

import os

from dotenv import load_dotenv
from fastapi import Header, HTTPException, status

load_dotenv()

# Cached at module import time so we don't hit os.environ on every request.
_API_KEY: str = os.environ.get("API_KEY", "")


async def require_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
) -> None:
    """
    FastAPI dependency.  Raises HTTP 401 if the supplied header value does
    not match the API_KEY environment variable.

    Add to a route or router like this:
        @router.post("/api/wearable", dependencies=[Depends(require_api_key)])
    or to an entire router:
        router = APIRouter(dependencies=[Depends(require_api_key)])
    """
    if not _API_KEY:
        # Server is mis-configured — don't silently accept all traffic.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API_KEY environment variable is not set on the server.",
        )
    if x_api_key != _API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

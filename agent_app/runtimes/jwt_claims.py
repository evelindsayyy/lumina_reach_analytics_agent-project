# -*- coding: utf-8 -*-

"""
Who is asking: the ``sub`` claim of the caller's JWT.

Deployed, the agent runtime sits behind AgentCore's JWT authorizer, which
verifies the token's signature, issuer, expiry and client against the Cognito
user pool before the request reaches this process. So the claims here are read,
not verified again: a request with a bad token never arrives. The header comes
through only because ``agentcore.json`` allowlists ``Authorization``.

Locally there is no authorizer and no token, and every function returns None.
"""

import base64
import json

#: The header the authorizer checked, as the runtime SDK names it.
AUTHORIZATION_HEADER = "Authorization"


def bearer_token(headers: dict[str, str] | None) -> str | None:
    """
    The token of an ``Authorization: Bearer <token>`` header, else None.
    """
    for name, value in (headers or {}).items():
        if name.lower() == AUTHORIZATION_HEADER.lower():
            scheme, _, token = (value or "").partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                return token.strip()
    return None


def jwt_claims(token: str) -> dict:
    """
    The payload of a JWT, decoded without checking the signature (see the
    module docstring for why that is right here).

    :raises ValueError: the token is not three base64url parts with a JSON
        object in the middle.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a JWT: expected three dot-separated parts")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"Not a JWT payload: {e}") from e
    if not isinstance(claims, dict):
        raise ValueError("Not a JWT payload: not a JSON object")
    return claims


def user_id_from_headers(headers: dict[str, str] | None) -> str | None:
    """
    The ``sub`` of the bearer token in ``headers``, or None when there is no
    token or it does not decode (local development, or a direct call).
    """
    token = bearer_token(headers)
    if token is None:
        return None
    try:
        sub = jwt_claims(token).get("sub")
    except ValueError:
        return None
    return sub if isinstance(sub, str) and sub else None

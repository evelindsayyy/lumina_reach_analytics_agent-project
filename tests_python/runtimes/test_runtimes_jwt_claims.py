# -*- coding: utf-8 -*-

"""
Reading the caller from the (already verified) JWT. Fictional tokens.
"""

import base64
import json

import pytest

from agent_app.runtimes import jwt_claims


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(claims) -> str:
    header = b64url(json.dumps({"alg": "RS256", "kid": "k"}).encode())
    payload = b64url(json.dumps(claims).encode())
    return f"{header}.{payload}.sig"


class TestBearerToken:
    @pytest.mark.parametrize("name", ["Authorization", "authorization", "AUTHORIZATION"])
    def test_any_header_casing(self, name):
        assert jwt_claims.bearer_token({name: "Bearer abc"}) == "abc"

    @pytest.mark.parametrize(
        "headers", [None, {}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}, {"X-Other": "Bearer abc"}]
    )
    def test_no_bearer_token(self, headers):
        assert jwt_claims.bearer_token(headers) is None


class TestJwtClaims:
    def test_decodes_unpadded_base64url(self):
        claims = {"sub": "a1b2-c3", "client_id": "acme", "n": "é"}
        assert jwt_claims.jwt_claims(make_jwt(claims)) == claims

    @pytest.mark.parametrize("token", ["abc", "a.b", "a.!!!.c", f"a.{b64url(b'[1]')}.c", f"a.{b64url(b'nope')}.c"])
    def test_garbage_is_a_value_error(self, token):
        with pytest.raises(ValueError):
            jwt_claims.jwt_claims(token)


class TestUserId:
    def test_the_sub_of_the_bearer_token(self):
        headers = {"Authorization": "Bearer " + make_jwt({"sub": "user-123"})}
        assert jwt_claims.user_id_from_headers(headers) == "user-123"

    @pytest.mark.parametrize(
        "headers",
        [
            None,
            {"Authorization": "Bearer not-a-jwt"},
            {"Authorization": "Bearer " + make_jwt({"client_id": "acme"})},
            {"Authorization": "Bearer " + make_jwt({"sub": 42})},
        ],
    )
    def test_no_user(self, headers):
        assert jwt_claims.user_id_from_headers(headers) is None

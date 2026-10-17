# tests/test_security.py
"""Password hashing, tokens and the role ladder. No database needed."""

import time

import jwt
import pytest

from app.api.deps import ROLE_LEVEL
from app.core import security as security_module
from app.core.security import create_token, decode_token, hash_password, verify_password


# ------------------------------------------------------------------ passwords

def test_a_hashed_password_verifies_and_a_wrong_one_does_not():
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$2")
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong horse", hashed)


@pytest.mark.parametrize("bad_hash", ["", None, "not-a-bcrypt-hash"])
def test_an_empty_or_malformed_hash_is_rejected_without_raising(bad_hash):
    assert verify_password("anything", bad_hash) is False


# ------------------------------------------------------------------ tokens

def test_a_token_round_trips_its_subject_and_role():
    payload = decode_token(create_token(42, "admin"))
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"


def test_a_tampered_or_garbage_token_is_rejected():
    token = create_token(1, "user")
    assert decode_token(token[:-2] + ("A" if token[-1] != "A" else "B") + token[-1]) is None
    assert decode_token("not.a.token") is None


def test_a_token_signed_with_another_key_is_rejected():
    forged = jwt.encode({"sub": "1", "role": "admin"}, "some-other-secret", algorithm="HS256")
    assert decode_token(forged) is None


def test_a_non_numeric_subject_is_rejected():
    token = jwt.encode(
        {"sub": "admin", "exp": int(time.time()) + 60},
        security_module.config.jwt_secret,
        algorithm=security_module.config.jwt_algorithm,
    )
    assert decode_token(token) is None


def test_an_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr(security_module.config, "jwt_expire_minutes", -1)
    assert decode_token(create_token(1, "user")) is None


# ------------------------------------------------------------------ roles

@pytest.mark.parametrize(
    "role, minimum, allowed",
    [("user", "user", True), ("admin", "user", True), ("admin", "admin", True), ("user", "admin", False)],
)
def test_the_role_ladder(role, minimum, allowed):
    assert (ROLE_LEVEL[role] >= ROLE_LEVEL[minimum]) is allowed

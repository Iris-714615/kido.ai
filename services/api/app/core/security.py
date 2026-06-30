from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Any

import jwt


PBKDF2_ITERATIONS = 120_000
JWT_ALGORITHM = "HS256"


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, secret_key: str) -> str:
    # 每个密码使用独立随机 salt，防止彩虹表攻击（secret_key 保留用于兼容旧实现签名）
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(password: str, stored_hash: str, secret_key: str) -> bool:
    try:
        scheme, iterations, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        expected_iterations = int(iterations)
        salt = _b64decode(salt_b64)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, expected_iterations)
        return hmac.compare_digest(_b64encode(derived), hash_b64)
    except Exception:
        return False


def create_access_token(user_id: int, role: str, secret_key: str, ttl_minutes: int) -> str:
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "exp": int(time.time()) + ttl_minutes * 60,
    }
    return jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, secret_key: str) -> dict[str, object]:
    payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
    return payload


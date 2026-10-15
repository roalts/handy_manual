"""Signed session cookie carrying only the user ID (http-api.md, Sessions)."""
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE = "copilot_session"


class Sessions:
    def __init__(self, secret: str, max_age: int, secure: bool = False) -> None:
        """`max_age` is in seconds; `secure` sets the cookie's Secure flag."""
        self._s = URLSafeTimedSerializer(secret, salt="copilot-session")
        self.max_age = max_age
        self.secure = secure

    def sign(self, user_id: str) -> str:
        """A signed, timestamped session cookie value for the user."""
        return self._s.dumps(user_id)

    def user_id(self, token: str | None) -> str | None:
        """The signed user ID, or None for a missing, tampered or expired cookie."""
        if not token:
            return None
        try:
            value = self._s.loads(token, max_age=self.max_age)
        except BadSignature:  # includes SignatureExpired
            return None
        return value if isinstance(value, str) else None

    def cookie_args(self) -> dict:
        """Cookie attributes shared by set_cookie and delete_cookie."""
        return {"key": COOKIE, "httponly": True, "samesite": "lax", "path": "/",
                "secure": self.secure}

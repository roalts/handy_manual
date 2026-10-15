"""The only way the harness reaches the system: the HTTP API (FR-001), signed in as each user
through the development sign-in."""
import time

import httpx


class InfrastructureError(RuntimeError):
    """The API can't be used (down, 5xx, model unavailable): the run stops without a score."""


class Api:
    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None,
                 timeout: float = 180.0) -> None:
        """`transport` lets tests replace the network; signed-in clients are kept per user."""
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout
        self._clients: dict[str, httpx.Client] = {}

    def _client(self) -> httpx.Client:
        """A new client, not signed in."""
        return httpx.Client(base_url=self.base_url, transport=self.transport,
                            timeout=self.timeout)

    def _call(self, client: httpx.Client, method: str, path: str, **kw) -> httpx.Response:
        """Send a request; a transport error becomes InfrastructureError."""
        try:
            return client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise InfrastructureError(f"{method} {path}: {e}") from e

    def health(self) -> dict:
        """Body of `/api/health`; any status but 200 is an InfrastructureError."""
        with self._client() as c:
            r = self._call(c, "GET", "/api/health")
        if r.status_code != 200:
            raise InfrastructureError(f"/api/health returned {r.status_code}")
        return r.json()

    def as_user(self, user_id: str) -> httpx.Client:
        """Client signed in as `user_id` through the development sign-in, cached after first use."""
        if user_id not in self._clients:
            c = self._client()
            r = self._call(c, "POST", "/api/session", json={"user_id": user_id})
            if r.status_code != 200 or r.json().get("user_id") != user_id:
                raise InfrastructureError(f"sign-in as {user_id} failed: {r.status_code}")
            self._clients[user_id] = c
        return self._clients[user_id]

    def ask(self, user_id: str, question: str, previous: dict | None = None
            ) -> tuple[dict, float]:
        """Raw `/api/ask` body as the user and the seconds it took; any status but 200 is an
        InfrastructureError."""
        body: dict = {"question": question}
        if previous:
            body["previous"] = previous
        start = time.monotonic()
        r = self._call(self.as_user(user_id), "POST", "/api/ask", json=body)
        seconds = time.monotonic() - start
        if r.status_code != 200:
            err = r.json().get("error") if r.headers.get("content-type", "").startswith(
                "application/json") else None
            raise InfrastructureError(f"/api/ask as {user_id} returned {r.status_code} {err}")
        return r.json(), seconds

    def source(self, user_id: str, passage_id: str) -> tuple[int, dict]:
        """Status and body of `GET /api/sources/{id}` as the user ({} if not JSON); only a 5xx
        raises, since a 403 or 404 is a result the checks judge."""
        r = self._call(self.as_user(user_id), "GET", f"/api/sources/{passage_id}")
        if r.status_code >= 500:
            raise InfrastructureError(f"/api/sources/{passage_id} returned {r.status_code}")
        try:
            body = r.json()
        except ValueError:
            body = {}
        return r.status_code, body

    def close(self) -> None:
        """Close and forget every signed-in client."""
        for c in self._clients.values():
            c.close()
        self._clients.clear()

from __future__ import annotations

from typing import Mapping
from urllib.parse import urlsplit

import requests
from azure.core.credentials import TokenCredential
from .errors import AzureHttpError, DemoError
from .network import resolve_private


def json_object(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DemoError(f"{description} must be a JSON object.")
    return value


class AzureHttpClient:
    def __init__(
        self,
        endpoint: str,
        credential: TokenCredential,
        scope: str,
        *,
        private: bool = True,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.credential = credential
        self.scope = scope
        self.private = private
        self.session = requests.Session()
        self.session.trust_env = False

    def close(self) -> None:
        self.session.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        document: Mapping[str, object] | None = None,
        params: Mapping[str, str] | None = None,
        content_type: str = "application/json",
        timeout: float = 60,
    ) -> requests.Response:
        if not path.startswith("/") or path.startswith("//") or "#" in path:
            raise DemoError("An API request must use a relative absolute path.")
        url = self.endpoint + path
        parsed = urlsplit(url)
        if parsed.netloc != urlsplit(self.endpoint).netloc:
            raise DemoError("Refusing a request to a different Azure endpoint.")
        if self.private:
            resolve_private(self.endpoint)
        token = self.credential.get_token(self.scope)
        response = self.session.request(
            method,
            url,
            params=params,
            data=body,
            json=document,
            headers={
                "Authorization": f"Bearer {token.token}",
                "Content-Type": content_type,
            },
            timeout=(min(10, timeout), timeout),
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            # Do not log a response body that could contain document contents.
            request_id = response.headers.get("x-ms-request-id", "not supplied")
            raise AzureHttpError(
                method, response.status_code, request_id, response.headers.get("Retry-After")
            )
        return response

    def get_object(
        self, path: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, object]:
        return json_object(self.request("GET", path, params=params).json(), "Azure response")

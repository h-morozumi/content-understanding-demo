from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from azure.core.credentials import TokenCredential

from .config import CU_API_VERSION, Settings
from .errors import AzureHttpError, DemoError
from .http_client import AzureHttpClient, json_object

CU_SCOPE = "https://cognitiveservices.azure.com/.default"


def operation_path(endpoint: str, location: str | None) -> str:
    if not location:
        raise DemoError("CU did not return Operation-Location.")
    url = urlsplit(urljoin(endpoint + "/", location))
    base = urlsplit(endpoint)
    expected_prefix = "/contentunderstanding/analyzerResults/"
    try:
        valid_port = url.port in (None, 443)
    except ValueError as exc:
        raise DemoError("Invalid CU polling URL.") from exc
    if (
        url.scheme != "https"
        or url.hostname != base.hostname
        or not valid_port
        or url.username is not None
        or url.password is not None
        or url.fragment
        or not url.path.startswith(expected_prefix)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", url.path.removeprefix(expected_prefix))
    ):
        raise DemoError("CU returned an unexpected polling URL; refusing to send a token.")
    query = parse_qs(url.query)
    if query and query != {"api-version": [CU_API_VERSION]}:
        raise DemoError("CU returned an unexpected polling API version or query.")
    return url.path


def poll_delay(header: str | None) -> float:
    if header is None:
        return 2
    try:
        value = float(header)
    except ValueError:
        try:
            until = parsedate_to_datetime(header)
        except (TypeError, ValueError) as exc:
            raise DemoError("CU returned an invalid Retry-After header.") from exc
        if until.tzinfo is None:
            raise DemoError("CU returned Retry-After without a time zone.")
        return max(0, (until - datetime.now(timezone.utc)).total_seconds())
    if not math.isfinite(value) or value < 0:
        raise DemoError("CU returned an invalid Retry-After header.")
    return value


class ContentUnderstanding:
    def __init__(self, settings: Settings, credential: TokenCredential) -> None:
        self.settings = settings
        self.http = AzureHttpClient(settings.cu_endpoint, credential, CU_SCOPE)

    def close(self) -> None:
        self.http.close()

    def configure_defaults(self) -> dict[str, object]:
        analyzer = self.http.get_object(
            f"/contentunderstanding/analyzers/{self.settings.analyzer_id}",
            params={"api-version": CU_API_VERSION},
        )
        supported = json_object(analyzer.get("supportedModels"), "Analyzer supportedModels")
        for kind, model in (
            ("completion", self.settings.completion_model),
            ("embedding", self.settings.embedding_model),
        ):
            models = supported.get(kind)
            if not isinstance(models, list) or model not in models:
                raise DemoError(
                    f"{self.settings.analyzer_id} does not advertise support for {model}. "
                    "Choose a supported model deployment before setting CU defaults."
                )
        deployments = {
            self.settings.completion_model: self.settings.completion_deployment,
            self.settings.embedding_model: self.settings.embedding_deployment,
            "prebuilt-analyzer-completion": self.settings.completion_deployment,
            "prebuilt-analyzer-completion-mini": self.settings.completion_deployment,
            "prebuilt-analyzer-embedding": self.settings.embedding_deployment,
        }
        self.http.request(
            "PATCH",
            "/contentunderstanding/defaults",
            params={"api-version": CU_API_VERSION},
            document={"modelDeployments": deployments},
        )
        configured = self.http.get_object(
            "/contentunderstanding/defaults", params={"api-version": CU_API_VERSION}
        )
        actual = json_object(configured.get("modelDeployments"), "CU default deployments")
        if any(actual.get(key) != value for key, value in deployments.items()):
            raise DemoError("CU defaults read-back does not match the requested deployments.")
        return configured

    def analyze(self, content: bytes, content_type: str) -> dict[str, object]:
        if not content or len(content) > self.settings.max_document_bytes:
            raise DemoError(
                f"Document must contain 1-{self.settings.max_document_bytes} bytes."
            )
        response = self.http.request(
            "POST",
            f"/contentunderstanding/analyzers/{self.settings.analyzer_id}:analyzeBinary",
            params={"api-version": CU_API_VERSION, "processingLocation": "global"},
            body=content,
            content_type=content_type,
        )
        if response.status_code != 202:
            raise DemoError(f"Expected CU HTTP 202, received {response.status_code}.")
        path = operation_path(
            self.settings.cu_endpoint, response.headers.get("Operation-Location")
        )
        deadline = time.monotonic() + self.settings.analysis_timeout
        delay = poll_delay(response.headers.get("Retry-After"))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DemoError(
                    f"CU analysis timed out after {self.settings.analysis_timeout}s. "
                    "The accepted service operation may still be running."
                )
            time.sleep(min(delay, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            try:
                result_response = self.http.request(
                    "GET",
                    path,
                    params={"api-version": CU_API_VERSION},
                    timeout=min(60, remaining),
                )
            except AzureHttpError as exc:
                if exc.status_code not in (429, 500, 502, 503, 504):
                    raise
                delay = poll_delay(exc.retry_after)
                continue
            operation = json_object(result_response.json(), "CU operation")
            status = operation.get("status")
            if status == "Succeeded":
                result = json_object(operation.get("result"), "CU analysis result")
                if not isinstance(result.get("contents"), list) or not result["contents"]:
                    raise DemoError("CU succeeded but returned no document content.")
                return result
            if status in ("Failed", "Canceled", "Cancelled"):
                error = operation.get("error")
                code = error.get("code", "Unknown") if isinstance(error, dict) else "Unknown"
                raise DemoError(f"CU analysis {status}: {code}. Operation: {path}")
            if status not in ("Running", "NotStarted"):
                raise DemoError(f"CU returned an unknown operation status: {status!r}.")
            delay = poll_delay(result_response.headers.get("Retry-After"))

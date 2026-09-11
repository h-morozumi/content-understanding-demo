from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from .errors import DemoError

CU_API_VERSION = "2025-11-01"
DEFAULT_ANALYZER = "prebuilt-invoice"
DEFAULT_AGENT_NAME = "private-cu-agent"
SERVICE_DOCUMENT_LIMIT = 200 * 1024 * 1024


def required(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DemoError(f"Missing {name}. Export the selected azd environment first.")
    return value.strip()


def optional(values: Mapping[str, object], name: str, default: str) -> str:
    if name not in values:
        return default
    return required(values, name)


def positive_int(
    values: Mapping[str, object], name: str, default: int, maximum: int
) -> int:
    raw = values.get(name, str(default))
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise DemoError(f"{name} must be an integer from 1 to {maximum}.")
    try:
        value = int(raw)
    except ValueError as exc:
        raise DemoError(f"{name} must be an integer from 1 to {maximum}.") from exc
    if not 1 <= value <= maximum:
        raise DemoError(f"{name} must be an integer from 1 to {maximum}.")
    return value


def validate_endpoint(value: str, suffix: str, *, project: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise DemoError("Invalid Azure endpoint.") from exc
    hostname = parsed.hostname or ""
    prefix = hostname.removesuffix(suffix)
    valid_path = (
        re.fullmatch(r"/api/projects/[A-Za-z0-9_-]+", parsed.path.rstrip("/"))
        if project
        else parsed.path in ("", "/")
    )
    if (
        parsed.scheme != "https"
        or not hostname.endswith(suffix)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", prefix)
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not valid_path
    ):
        raise DemoError(f"Expected a public-cloud Azure {suffix} HTTPS endpoint.")
    return value.rstrip("/")


def validate_agent_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", name):
        raise DemoError("Agent name must be 1-63 alphanumeric/hyphen characters.")
    return name


def validate_blob_name(name: str) -> str:
    if (
        not name
        or len(name) > 1024
        or name.startswith("/")
        or "\\" in name
        or ":" in name
        or any(ord(char) < 32 for char in name)
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise DemoError("Use a relative blob name, not a URL, path traversal, or SAS.")
    return name


@dataclass(frozen=True, slots=True)
class Settings:
    project_endpoint: str
    cu_endpoint: str
    blob_endpoint: str
    container_name: str
    model_deployment: str
    completion_deployment: str
    embedding_deployment: str
    network_mode: str
    agent_name: str = DEFAULT_AGENT_NAME
    analyzer_id: str = DEFAULT_ANALYZER
    max_document_bytes: int = 20 * 1024 * 1024
    analysis_timeout: int = 600
    completion_model: str = "gpt-5.2"
    embedding_model: str = "text-embedding-3-large"
    account_id: str = ""
    storage_id: str = ""
    project_id: str = ""

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Settings:
        container = required(values, "DOCUMENT_CONTAINER_NAME")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9]|-(?!-)){1,61}[a-z0-9]", container):
            raise DemoError("DOCUMENT_CONTAINER_NAME is not a valid Blob container.")
        mode = required(values, "FOUNDRY_NETWORK_MODE")
        if mode not in ("byo", "managed"):
            raise DemoError("FOUNDRY_NETWORK_MODE must be byo or managed.")
        analyzer = optional(values, "CU_ANALYZER_ID", DEFAULT_ANALYZER)
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", analyzer):
            raise DemoError("CU_ANALYZER_ID is not a valid analyzer identifier.")
        return cls(
            project_endpoint=validate_endpoint(
                required(values, "AZURE_AI_PROJECT_ENDPOINT"),
                ".services.ai.azure.com",
                project=True,
            ),
            cu_endpoint=validate_endpoint(
                required(values, "CONTENT_UNDERSTANDING_ENDPOINT"),
                ".cognitiveservices.azure.com",
            ),
            blob_endpoint=validate_endpoint(
                required(values, "DOCUMENT_BLOB_ENDPOINT"), ".blob.core.windows.net"
            ),
            container_name=container,
            model_deployment=required(values, "AZURE_AI_MODEL_DEPLOYMENT_NAME"),
            completion_deployment=required(values, "CU_COMPLETION_DEPLOYMENT"),
            embedding_deployment=required(values, "CU_EMBEDDING_DEPLOYMENT"),
            network_mode=mode,
            agent_name=validate_agent_name(
                optional(values, "HOSTED_AGENT_NAME", DEFAULT_AGENT_NAME)
            ),
            analyzer_id=analyzer,
            max_document_bytes=positive_int(
                values, "MAX_DOCUMENT_BYTES", 20 * 1024 * 1024, SERVICE_DOCUMENT_LIMIT
            ),
            analysis_timeout=positive_int(values, "ANALYSIS_TIMEOUT_SECONDS", 600, 3600),
            completion_model=optional(values, "CU_COMPLETION_MODEL_NAME", "gpt-5.2"),
            embedding_model=optional(
                values, "CU_EMBEDDING_MODEL_NAME", "text-embedding-3-large"
            ),
            account_id=str(values.get("AZURE_AI_ACCOUNT_ID", "")),
            storage_id=str(values.get("DOCUMENT_STORAGE_ACCOUNT_ID", "")),
            project_id=str(values.get("AZURE_AI_PROJECT_ID", "")),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        if path is None:
            return cls.from_mapping(os.environ)
        with path.open(encoding="utf-8-sig") as source:
            values = json.load(source)
        if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
            raise DemoError("The configuration file must be a JSON object.")
        # A selected file is authoritative; do not mix two azd environments.
        return cls.from_mapping(values)

    def runtime_environment(self) -> dict[str, str]:
        return {
            "AZURE_AI_PROJECT_ENDPOINT": self.project_endpoint,
            "FOUNDRY_PROJECT_ENDPOINT": self.project_endpoint,
            "CONTENT_UNDERSTANDING_ENDPOINT": self.cu_endpoint,
            "DOCUMENT_BLOB_ENDPOINT": self.blob_endpoint,
            "DOCUMENT_CONTAINER_NAME": self.container_name,
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": self.model_deployment,
            "CU_COMPLETION_DEPLOYMENT": self.completion_deployment,
            "CU_EMBEDDING_DEPLOYMENT": self.embedding_deployment,
            "CU_COMPLETION_MODEL_NAME": self.completion_model,
            "CU_EMBEDDING_MODEL_NAME": self.embedding_model,
            "FOUNDRY_NETWORK_MODE": self.network_mode,
            "HOSTED_AGENT_NAME": self.agent_name,
            "CU_ANALYZER_ID": self.analyzer_id,
            "MAX_DOCUMENT_BYTES": str(self.max_document_bytes),
            "ANALYSIS_TIMEOUT_SECONDS": str(self.analysis_timeout),
            "OTEL_SDK_DISABLED": "true",
        }

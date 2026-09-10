from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from azure.core import MatchConditions
from azure.core.credentials import TokenCredential
from azure.core.pipeline.transport import RequestsTransport
from azure.storage.blob import BlobClient, ContentSettings

from .config import Settings, validate_blob_name
from .cu import ContentUnderstanding
from .errors import DemoError
from .network import resolve_private

DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".docx"}
)


def document_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix not in DOCUMENT_EXTENSIONS:
        raise DemoError(
            f"Unsupported demo document type {suffix!r}; use PDF, TXT, DOCX, or an image."
        )
    if suffix == ".txt":
        return "text/plain"
    content_type, _ = mimetypes.guess_type(name)
    if not content_type:
        raise DemoError(f"Cannot determine the document media type for {name!r}.")
    return content_type


class DocumentAnalysis:
    def __init__(self, settings: Settings, credential: TokenCredential) -> None:
        self.settings = settings
        self.credential = credential
        self.cu = ContentUnderstanding(settings, credential)

    def close(self) -> None:
        self.cu.close()

    def blob_client(self, name: str) -> BlobClient:
        validate_blob_name(name)
        resolve_private(self.settings.blob_endpoint)
        return BlobClient(
            account_url=self.settings.blob_endpoint,
            container_name=self.settings.container_name,
            blob_name=name,
            credential=self.credential,
            transport=RequestsTransport(use_env_settings=False),
            connection_timeout=10,
            read_timeout=60,
            retry_total=3,
        )

    def upload(self, source: Path, name: str, *, overwrite: bool = False) -> dict[str, object]:
        validate_blob_name(name)
        media_type = document_type(name)
        size = source.stat().st_size
        if not source.is_file() or not 0 < size <= self.settings.max_document_bytes:
            raise DemoError(
                f"Select a file containing 1-{self.settings.max_document_bytes} bytes."
            )
        with self.blob_client(name) as blob, source.open("rb") as content:
            result = blob.upload_blob(
                content,
                length=size,
                overwrite=overwrite,
                content_settings=ContentSettings(content_type=media_type),
            )
        return {
            "container": self.settings.container_name,
            "blob": name,
            "bytes": size,
            "etag": result["etag"],
        }

    def analyze(self, name: str, *, execution_location: str) -> dict[str, object]:
        validate_blob_name(name)
        media_type = document_type(name)
        blob_addresses = resolve_private(self.settings.blob_endpoint)
        cu_addresses = resolve_private(self.settings.cu_endpoint)
        with self.blob_client(name) as blob:
            properties = blob.get_blob_properties()
            size = properties.size
            if not 0 < size <= self.settings.max_document_bytes:
                raise DemoError(
                    f"Blob size {size} exceeds the demo limit "
                    f"of {self.settings.max_document_bytes} bytes, or is empty."
                )
            # Pin the read to the inspected version and bound the in-memory download.
            content = blob.download_blob(
                offset=0,
                length=size,
                etag=properties.etag,
                match_condition=MatchConditions.IfNotModified,
                max_concurrency=1,
            ).readall()
            if len(content) != size:
                raise DemoError("The Blob download length does not match its properties.")
        result = self.cu.analyze(content, media_type)
        return {
            "source": {
                "container": self.settings.container_name,
                "blob": name,
                "etag": properties.etag,
                "bytes": size,
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            "execution": {
                "location": execution_location,
                "network_mode": self.settings.network_mode,
                "blob_addresses": blob_addresses,
                "cu_addresses": cu_addresses,
                "cu_api_version": "2025-11-01",
                "processing_location": "global",
            },
            "analysis": result,
        }


def agent_evidence(report: dict[str, object]) -> dict[str, object]:
    analysis = report.get("analysis")
    if not isinstance(analysis, dict) or not isinstance(analysis.get("contents"), list):
        raise DemoError("The CU report has no content to use as agent evidence.")
    contents = []
    for item in analysis["contents"]:
        if not isinstance(item, dict):
            raise DemoError("The CU report contains an invalid content entry.")
        contents.append(
            {key: item[key] for key in ("path", "markdown", "fields") if key in item}
        )
    return {
        "source": report["source"],
        "execution": report["execution"],
        "analyzer_id": analysis.get("analyzerId"),
        "contents": contents,
        "warnings": analysis.get("warnings", []),
    }

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tempfile
import time
import tomllib
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    CodeConfiguration,
    FixedRatioVersionSelectionRule,
    HostedAgentDefinition,
    ProtocolConfiguration,
    ProtocolVersionRecord,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.core.credentials import TokenCredential

from .config import Settings
from .errors import DemoError
from .http_client import AzureHttpClient, json_object
from .network import resolve_private

RUNTIME_FILES = (
    "__init__.py",
    "config.py",
    "errors.py",
    "network.py",
    "http_client.py",
    "cu.py",
    "documents.py",
    "hosted.py",
)
ARM_ENDPOINT = "https://management.azure.com"
ARM_SCOPE = ARM_ENDPOINT + "/.default"
ROLE_API_VERSION = "2022-04-01"


def normalized_uuid(value: str, description: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise DemoError(f"{description} must be a valid UUID.") from exc


def make_archive(root: Path, requirements: str) -> bytes:
    source = root / "src" / "private_cu_demo"
    entries = {"main.py": root / "hosted" / "main.py"}
    entries.update({f"private_cu_demo/{name}": source / name for name in RUNTIME_FILES})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in entries.items():
            if (
                not path.is_file()
                or path.is_symlink()
                or not path.resolve().is_relative_to(root.resolve())
            ):
                raise DemoError(f"Missing or unsafe runtime source file: {path}")
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, path.read_bytes())
        entry = zipfile.ZipInfo("requirements.txt", date_time=(1980, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        archive.writestr(entry, requirements.encode("utf-8"))
    payload = output.getvalue()
    if len(payload) > 250 * 1024 * 1024:
        raise DemoError("The source package exceeds Foundry's 250 MB limit.")
    return payload


def export_requirements(root: Path) -> str:
    if not (root / "uv.lock").is_file():
        raise DemoError("uv.lock is missing. Run uv sync in the repository first.")
    with (root / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)
    indexes = project.get("tool", {}).get("uv", {}).get("index", [])
    defaults = [index for index in indexes if index.get("default") is True]
    if len(defaults) > 1:
        raise DemoError("Only one default Python package index is supported.")
    index_url = defaults[0]["url"] if defaults else "https://pypi.org/simple/"
    parsed = urlsplit(index_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in index_url)
    ):
        raise DemoError("Package index must be HTTPS and contain no embedded credentials.")
    exported = subprocess.run(
        ["uv", "export", "--locked", "--no-dev", "--no-emit-project", "--no-editable"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    if not exported.stdout.strip():
        raise DemoError("uv exported an empty requirements file.")
    return f"--index-url {index_url}\n{exported.stdout}"


def validate_resource_id(value: str, provider: str, resource_type: str) -> str:
    pattern = (
        r"/subscriptions/([0-9a-fA-F-]{36})/resourceGroups/[A-Za-z0-9_.()-]+"
        rf"/providers/{re.escape(provider)}/{re.escape(resource_type)}/[A-Za-z0-9_-]+"
    )
    match = re.fullmatch(pattern, value, flags=re.IGNORECASE)
    if not match:
        raise DemoError(f"Invalid {provider}/{resource_type} resource ID in configuration.")
    normalized_uuid(match.group(1), "Subscription ID")
    return value.rstrip("/")


def validate_admin_targets(settings: Settings) -> str:
    account = validate_resource_id(
        settings.account_id, "Microsoft.CognitiveServices", "accounts"
    )
    storage = validate_resource_id(settings.storage_id, "Microsoft.Storage", "storageAccounts")
    if (
        account.split("/")[2].lower() != storage.split("/")[2].lower()
        or urlsplit(settings.cu_endpoint).hostname != account.split("/")[-1].lower()
        + ".cognitiveservices.azure.com"
        or urlsplit(settings.blob_endpoint).hostname != storage.split("/")[-1].lower()
        + ".blob.core.windows.net"
        or urlsplit(settings.project_endpoint).hostname != account.split("/")[-1].lower()
        + ".services.ai.azure.com"
        or settings.project_id.lower()
        != (account + "/projects/" + settings.project_endpoint.split("/")[-1]).lower()
    ):
        raise DemoError("ARM IDs and private endpoints belong to different resources.")
    return account.split("/")[2]


class AgentPermissions:
    def __init__(self, settings: Settings, credential: TokenCredential) -> None:
        self.settings = settings
        self.subscription_id = validate_admin_targets(settings)
        self.http = AzureHttpClient(ARM_ENDPOINT, credential, ARM_SCOPE, private=False)

    def close(self) -> None:
        self.http.close()

    def role_definition(self, name: str) -> str:
        result = self.http.get_object(
            f"{self.settings.account_id}/providers/Microsoft.Authorization/roleDefinitions",
            params={"api-version": ROLE_API_VERSION, "$filter": f"roleName eq '{name}'"},
        )
        roles = result.get("value")
        if not isinstance(roles, list) or len(roles) != 1:
            raise DemoError(f"Expected one built-in role named {name!r}.")
        role = json_object(roles[0], "Role definition")
        properties = json_object(role.get("properties"), "Role properties")
        role_id = role.get("id")
        if (
            properties.get("roleName") != name
            or properties.get("type") != "BuiltInRole"
            or not isinstance(role_id, str)
        ):
            raise DemoError(f"Role lookup did not return the built-in {name!r} role.")
        normalized_uuid(role_id.rsplit("/", 1)[-1], "Role definition ID")
        return role_id

    def grant(self, principal_id: str) -> list[dict[str, str]]:
        principal_id = normalized_uuid(principal_id, "Agent principal ID")
        targets = (
            (
                self.settings.storage_id
                + "/blobServices/default/containers/"
                + self.settings.container_name,
                "Storage Blob Data Reader",
            ),
            (self.settings.account_id, "Cognitive Services Content Understanding Reader"),
        )
        assignments = []
        for scope, role_name in targets:
            role_id = self.role_definition(role_name)
            name = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}/{principal_id}/{role_id}".lower())
            )
            self.http.request(
                "PUT",
                f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}",
                params={"api-version": ROLE_API_VERSION},
                document={
                    "properties": {
                        "principalId": principal_id,
                        "principalType": "ServicePrincipal",
                        "roleDefinitionId": role_id,
                    }
                },
            )
            assignments.append({"scope": scope, "role": role_name, "principal_id": principal_id})
        return assignments


def wait_for_version(
    project: AIProjectClient, agent_name: str, version: str, *, timeout: float = 900
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        details = project.agents.get_version(agent_name=agent_name, agent_version=version)
        status = details.get("status")
        if status == "active":
            return
        if status == "failed":
            error = details.get("error")
            code = error.get("code", "Unknown") if isinstance(error, dict) else "Unknown"
            raise DemoError(
                f"Hosted agent version {version} failed ({code}). "
                "Inspect its provisioning error; the previous endpoint was not promoted."
            )
        if status not in ("creating", "updating"):
            raise DemoError(f"Unexpected hosted agent provisioning status: {status!r}.")
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise DemoError(
        f"Hosted agent version {version} did not become active in {timeout:g}s. "
        "Its service-side provisioning may still be running."
    )


def deploy_agent(
    settings: Settings, credential: TokenCredential, root: Path
) -> dict[str, object]:
    validate_admin_targets(settings)
    resolve_private(settings.project_endpoint)
    payload = make_archive(root, export_requirements(root))
    digest = hashlib.sha256(payload).hexdigest()
    definition = HostedAgentDefinition(
        cpu="1",
        memory="2Gi",
        code_configuration=CodeConfiguration(
            runtime="python_3_13",
            entry_point=["python", "main.py"],
            dependency_resolution="remote_build",
        ),
        protocol_versions=[ProtocolVersionRecord(protocol="responses", version="2.0.0")],
        environment_variables=settings.runtime_environment(),
    )
    with AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential, allow_preview=True
    ) as project:
        # The locked SDK requires a stream whose name ends in .zip, not bare BytesIO.
        with tempfile.TemporaryDirectory(prefix="private-cu-source-") as directory:
            archive = Path(directory) / "agent-code.zip"
            archive.write_bytes(payload)
            with archive.open("rb") as code:
                created = project.agents.create_version_from_code(
                    agent_name=settings.agent_name,
                    description="Private Blob to Content Understanding document analysis demo.",
                    definition=definition,
                    code=code,
                    code_zip_sha256=digest,
                )
        wait_for_version(project, settings.agent_name, created.version)
        agent = project.agents.get(agent_name=settings.agent_name)
        if agent.instance_identity is None:
            raise DemoError(
                "The hosted agent has no distinct runtime identity. "
                "Use a new agent name/project; do not substitute the project managed identity."
            )
        permissions = AgentPermissions(settings, credential)
        try:
            assignments = permissions.grant(agent.instance_identity.principal_id)
        finally:
            permissions.close()
        project.agents.update_details(
            agent_name=settings.agent_name,
            agent_endpoint=AgentEndpointConfig(
                version_selector=VersionSelector(
                    version_selection_rules=[
                        FixedRatioVersionSelectionRule(
                            agent_version=created.version, traffic_percentage=100
                        )
                    ]
                ),
                protocol_configuration=ProtocolConfiguration(
                    responses=ResponsesProtocolConfiguration()
                ),
            ),
        )
        published = project.agents.get(agent_name=settings.agent_name)
        endpoint = published.agent_endpoint
        if endpoint is None or endpoint.version_selector is None:
            raise DemoError("The deployed agent has no active endpoint version selector.")
        rules = endpoint.version_selector.version_selection_rules
        if (
            len(rules) != 1
            or not isinstance(rules[0], FixedRatioVersionSelectionRule)
            or rules[0].agent_version != created.version
            or rules[0].traffic_percentage != 100
        ):
            raise DemoError("The agent endpoint did not retain the requested version selection.")
    return {
        "agent": settings.agent_name,
        "version": created.version,
        "source_sha256": digest,
        "runtime": "python_3_13",
        "network_mode": settings.network_mode,
        "role_assignments": assignments,
        "note": "New Azure role assignments can take several minutes to propagate.",
    }

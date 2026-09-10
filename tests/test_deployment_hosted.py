import asyncio
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentDetails,
    AgentEndpointConfig,
    AgentIdentity,
    FixedRatioVersionSelectionRule,
    VersionSelector,
    CodeConfiguration,
    HostedAgentDefinition,
)
from azure.core.credentials import AccessToken
from urllib3.response import HTTPResponse

from private_cu_demo.deployment import (
    AgentPermissions,
    RUNTIME_FILES,
    deploy_agent,
    export_requirements,
    make_archive,
    wait_for_version,
)
from private_cu_demo.errors import DemoError
from private_cu_demo.hosted import create_agent

from tests.helpers import ACCOUNT_ID, RESULT, STORAGE_ID, SUBSCRIPTION, response, settings

PRINCIPAL_ID = "22222222-2222-4222-8222-222222222222"
ROLE_ID = f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Authorization/roleDefinitions/33333333-3333-4333-8333-333333333333"


class PackageTests(unittest.TestCase):
    def create_source(self, root):
        source = root / "src" / "private_cu_demo"
        source.mkdir(parents=True)
        for name in RUNTIME_FILES:
            (source / name).write_text("# safe source\n", encoding="utf-8")
        (root / "hosted").mkdir()
        (root / "hosted" / "main.py").write_text("# entry point\n", encoding="utf-8")
        (root / ".env").write_text("SECRET=do-not-upload", encoding="utf-8")
        (source / "deployment.py").write_text("# operator-only code", encoding="utf-8")
        (root / "uv.lock").write_text("version = 1", encoding="utf-8")

    def test_archive_is_flat_deterministic_and_excludes_sensitive_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.create_source(root)
            first = make_archive(root, "requests==2.34.2\n")
            second = make_archive(root, "requests==2.34.2\n")
            self.assertEqual(first, second)
            with zipfile.ZipFile(io.BytesIO(first)) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"main.py", "requirements.txt"}
                    | {f"private_cu_demo/{name}" for name in RUNTIME_FILES},
                )
                self.assertNotIn(b"do-not-upload", b"".join(archive.read(n) for n in archive.namelist()))

    def test_missing_source_fails_packaging(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(DemoError):
                make_archive(Path(folder), "requests==2.34.2")

    def test_export_uses_lock_and_approved_index_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.create_source(root)
            (root / "pyproject.toml").write_text(
                '[[tool.uv.index]]\ndefault=true\nurl="https://approved.example/simple/"\n',
                encoding="utf-8",
            )
            with patch("private_cu_demo.deployment.subprocess.run") as run:
                run.return_value = SimpleNamespace(stdout="requests==2.34.2\n")
                exported = export_requirements(root)
            self.assertIn("--index-url https://approved.example/simple/", exported)
            self.assertIn("--locked", run.call_args.args[0])
            self.assertIn("--no-emit-project", run.call_args.args[0])

    def test_embedded_index_credentials_are_never_packaged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.create_source(root)
            (root / "pyproject.toml").write_text(
                '[[tool.uv.index]]\ndefault=true\nurl="https://user:secret@approved.example/simple/"\n',
                encoding="utf-8",
            )
            with patch("private_cu_demo.deployment.subprocess.run") as run:
                with self.assertRaisesRegex(DemoError, "credentials"):
                    export_requirements(root)
                run.assert_not_called()


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.permissions = AgentPermissions(settings(), Mock())
        self.permissions.http.close()
        self.permissions.http = Mock()
        self.addCleanup(self.permissions.close)

    def test_role_lookup_requires_exact_builtin(self):
        self.permissions.http.get_object.return_value = {
            "value": [{"id": ROLE_ID, "properties": {"roleName": "Reader", "type": "CustomRole"}}]
        }
        with self.assertRaisesRegex(DemoError, "built-in"):
            self.permissions.role_definition("Reader")
        self.assertEqual(
            self.permissions.http.get_object.call_args.args[0],
            ACCOUNT_ID + "/providers/Microsoft.Authorization/roleDefinitions",
        )

    def test_grants_only_agent_reader_roles_and_is_deterministic(self):
        with patch.object(self.permissions, "role_definition", return_value=ROLE_ID):
            report = self.permissions.grant(PRINCIPAL_ID)
            first = [c.args[1] for c in self.permissions.http.request.call_args_list]
            self.permissions.http.request.reset_mock()
            self.permissions.grant(PRINCIPAL_ID)
            second = [c.args[1] for c in self.permissions.http.request.call_args_list]
        self.assertEqual(first, second)
        self.assertEqual(report[0]["scope"], STORAGE_ID + "/blobServices/default/containers/documents")
        self.assertEqual(report[1]["scope"], ACCOUNT_ID)
        self.assertEqual(
            [row["role"] for row in report],
            ["Storage Blob Data Reader", "Cognitive Services Content Understanding Reader"],
        )
        for call in self.permissions.http.request.call_args_list:
            self.assertEqual(call.kwargs["document"]["properties"]["principalId"], PRINCIPAL_ID)


class DeploymentTests(unittest.TestCase):
    @patch("private_cu_demo.deployment.time.sleep")
    def test_wait_polls_until_active(self, _):
        client = Mock()
        client.agents.get_version.side_effect = [{"status": "creating"}, {"status": "active"}]
        wait_for_version(client, "agent", "1")
        self.assertEqual(client.agents.get_version.call_count, 2)

    def test_wait_reports_failed_and_unexpected_states(self):
        client = Mock()
        for status in ("failed", "unknown"):
            client.agents.get_version.return_value = {"status": status}
            with self.assertRaises(DemoError):
                wait_for_version(client, "agent", "1")

    @patch("private_cu_demo.deployment.AgentPermissions")
    @patch("private_cu_demo.deployment.AIProjectClient")
    @patch("private_cu_demo.deployment.make_archive", return_value=b"safe-code-zip")
    @patch("private_cu_demo.deployment.export_requirements", return_value="locked requirements")
    @patch("private_cu_demo.deployment.resolve_private")
    def test_deploys_real_hosted_code_and_uses_instance_identity(self, _, export, archive, project_type, permissions):
        project = project_type.return_value.__enter__.return_value
        uploaded = {}

        def create_version(**kwargs):
            uploaded["bytes"] = kwargs["code"].read()
            uploaded["name"] = kwargs["code"].name
            return SimpleNamespace(version="7")

        project.agents.create_version_from_code.side_effect = create_version
        project.agents.get_version.return_value = {"status": "active"}
        identity = AgentIdentity(principal_id=PRINCIPAL_ID, client_id=PRINCIPAL_ID)
        endpoint = AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(agent_version="7", traffic_percentage=100)
                ]
            )
        )
        details = AgentDetails({"instance_identity": identity, "agent_endpoint": endpoint})
        project.agents.get.return_value = details
        permissions.return_value.grant.return_value = []
        report = deploy_agent(settings(), Mock(), Path.cwd())
        created = project.agents.create_version_from_code.call_args.kwargs
        self.assertEqual(created["definition"].kind, "hosted")
        self.assertEqual(created["definition"].code_configuration.runtime, "python_3_13")
        self.assertEqual(created["definition"].code_configuration.dependency_resolution, "remote_build")
        self.assertEqual(uploaded["bytes"], b"safe-code-zip")
        self.assertTrue(uploaded["name"].endswith(".zip"))
        self.assertTrue(project_type.call_args.kwargs["allow_preview"])
        self.assertNotIn("WINDOWS_ADMIN_PASSWORD", created["definition"].environment_variables)
        permissions.return_value.grant.assert_called_once_with(PRINCIPAL_ID)
        project.agents.update_details.assert_called_once()
        self.assertEqual(report["version"], "7")

    @patch("private_cu_demo.deployment.AgentPermissions")
    @patch("private_cu_demo.deployment.AIProjectClient")
    @patch("private_cu_demo.deployment.make_archive", return_value=b"zip")
    @patch("private_cu_demo.deployment.export_requirements", return_value="locked")
    @patch("private_cu_demo.deployment.resolve_private")
    def test_failed_version_is_never_promoted(self, _, export, archive, project_type, permissions):
        project = project_type.return_value.__enter__.return_value
        project.agents.create_version_from_code.return_value = SimpleNamespace(version="2")
        project.agents.get_version.return_value = {"status": "failed", "error": {"code": "CodeError"}}
        with self.assertRaisesRegex(DemoError, "CodeError"):
            deploy_agent(settings(), Mock(), Path.cwd())
        permissions.assert_not_called()
        project.agents.update_details.assert_not_called()


class HostedTests(unittest.TestCase):
    @patch("private_cu_demo.hosted.DocumentAnalysis")
    def test_tool_calls_blob_and_cu_in_hosted_runtime(self, analysis_type):
        analysis = analysis_type.return_value
        analysis.analyze.return_value = {
            "source": {"blob": "invoice.txt"},
            "execution": {"location": "foundry-hosted", "network_mode": "managed"},
            "analysis": RESULT,
        }
        agent = create_agent(settings(FOUNDRY_NETWORK_MODE="managed"), Mock())
        function = agent.default_options["tools"][0]
        result = asyncio.run(function.invoke(arguments={"blob_name": "invoice.txt"}))
        analysis.analyze.assert_called_once_with("invoice.txt", execution_location="foundry-hosted")
        analysis.close.assert_called_once()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].type, "text")
        parsed = json.loads(result[0].text)
        self.assertEqual(parsed["execution"]["network_mode"], "managed")
        self.assertFalse(agent.default_options["store"])
        self.assertFalse(agent.default_options["allow_multiple_tool_calls"])
        self.assertEqual(agent.client.function_invocation_configuration["max_function_calls"], 1)

    @patch("private_cu_demo.hosted.DocumentAnalysis")
    def test_tool_does_not_silently_truncate_evidence(self, analysis_type):
        analysis_type.return_value.analyze.return_value = {
            "source": {"blob": "large.txt"},
            "execution": {"location": "foundry-hosted"},
            "analysis": {"contents": [{"markdown": "x" * 61_000}]},
        }
        agent = create_agent(settings(), Mock())
        function = agent.default_options["tools"][0]
        with self.assertRaises(DemoError) as raised:
            asyncio.run(function.invoke(arguments={"blob_name": "large.txt"}))
        self.assertIn("too large", str(raised.exception))


class SdkContractTests(unittest.TestCase):
    def credential(self):
        class Credential:
            def get_token(self, *scopes, **kwargs):
                return AccessToken("offline-test-token", 9999999999)

        return Credential()

    def test_real_sdk_binds_agent_endpoint_without_management_lookup(self):
        with patch("requests.Session.request", side_effect=AssertionError("No external HTTP")):
            with AIProjectClient(
                endpoint=settings().project_endpoint,
                credential=self.credential(),
                allow_preview=True,
            ) as project:
                with project.get_openai_client(agent_name="private-cu-agent") as client:
                    self.assertEqual(
                        str(client.base_url),
                        settings().project_endpoint
                        + "/agents/private-cu-agent/endpoint/protocols/openai/",
                    )

    def test_real_sdk_serializes_named_zip_source_upload(self):
        payload = b"offline-source-archive"
        digest = hashlib.sha256(payload).hexdigest()
        observed = {}

        def send(prepared, **kwargs):
            observed["request"] = prepared
            reply = response(
                200,
                {"name": "demo-agent", "version": "1", "status": "active"},
                **{"Content-Type": "application/json"},
            )
            reply.raw = HTTPResponse(
                body=io.BytesIO(reply.content),
                headers=reply.headers,
                status=200,
                preload_content=False,
            )
            return reply

        definition = HostedAgentDefinition(
            cpu="1",
            memory="2Gi",
            code_configuration=CodeConfiguration(
                runtime="python_3_13",
                entry_point=["python", "main.py"],
                dependency_resolution="remote_build",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "agent-code.zip"
            archive.write_bytes(payload)
            with archive.open("rb") as code:
                with patch("requests.Session.send", side_effect=send):
                    with AIProjectClient(
                        endpoint=settings().project_endpoint,
                        credential=self.credential(),
                        allow_preview=True,
                        retry_total=0,
                    ) as project:
                        created = project.agents.create_version_from_code(
                            agent_name="demo-agent",
                            definition=definition,
                            code=code,
                            code_zip_sha256=digest,
                        )
                        self.assertEqual(created.version, "1")
        prepared = observed["request"]
        self.assertEqual(prepared.method, "POST")
        headers = {name.lower(): value for name, value in prepared.headers.items()}
        self.assertEqual(headers["x-ms-code-zip-sha256"], digest)
        self.assertTrue(headers["foundry-features"])
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {headers['content-type']}\r\n\r\n".encode() + prepared.body
        )
        parts = {
            part.get_param("name", header="content-disposition"): part
            for part in message.iter_parts()
        }
        self.assertEqual(set(parts), {"metadata", "code"})
        self.assertTrue(parts["code"].get_filename().endswith(".zip"))
        self.assertEqual(parts["code"].get_payload(decode=True), payload)
        metadata = json.loads(parts["metadata"].get_payload(decode=True))
        self.assertEqual(metadata["definition"]["code_configuration"]["runtime"], "python_3_13")

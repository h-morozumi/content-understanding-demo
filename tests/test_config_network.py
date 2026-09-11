import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from private_cu_demo.config import Settings, validate_agent_name, validate_blob_name
from private_cu_demo.deployment import validate_admin_targets
from private_cu_demo.errors import DemoError
from private_cu_demo.network import diagnose_endpoints, resolve_private

from tests.helpers import ENVIRONMENT, SUBSCRIPTION, dns_record, settings


class ConfigurationTests(unittest.TestCase):
    def test_loads_valid_configuration(self):
        config = settings()
        self.assertEqual(config.network_mode, "byo")
        self.assertEqual(config.analysis_timeout, 600)
        self.assertEqual(validate_admin_targets(config), SUBSCRIPTION)

    def test_requires_complete_selected_environment(self):
        with self.assertRaisesRegex(DemoError, "Missing"):
            Settings.from_mapping({})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"FOUNDRY_NETWORK_MODE":"managed"}', encoding="utf-8")
            with patch.dict("os.environ", ENVIRONMENT):
                with self.assertRaisesRegex(DemoError, "Missing"):
                    Settings.load(path)

    def test_reads_powershell_utf8_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(ENVIRONMENT), encoding="utf-8-sig")
            self.assertEqual(Settings.load(path), settings())

    def test_rejects_endpoint_credential_and_query_injection(self):
        for endpoint in (
            "http://foundrydemo.cognitiveservices.azure.com",
            "https://foundrydemo.cognitiveservices.azure.com.evil.example",
            "https://user:password@foundrydemo.cognitiveservices.azure.com",
            "https://foundrydemo.cognitiveservices.azure.com?sig=secret",
            "https://foundrydemo.cognitiveservices.azure.com:8443",
            "https://foundrydemo.cognitiveservices.azure.com/contentunderstanding",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(DemoError):
                settings(CONTENT_UNDERSTANDING_ENDPOINT=endpoint)

    def test_rejects_invalid_project_container_and_mode(self):
        for key, value in (
            ("DOCUMENT_CONTAINER_NAME", "../outside"),
            ("DOCUMENT_CONTAINER_NAME", "BadContainer"),
            ("DOCUMENT_CONTAINER_NAME", "a--b"),
            ("FOUNDRY_NETWORK_MODE", "public"),
            ("CU_ANALYZER_ID", "../../analyzers"),
            ("AZURE_AI_PROJECT_ENDPOINT", "https://demo.services.ai.azure.com/evil"),
        ):
            with self.subTest(key=key), self.assertRaises(DemoError):
                settings(**{key: value})

    def test_document_limit_boundaries(self):
        for value in ("0", "-1", "209715201", "NaN", True, 1.5):
            with self.subTest(value=value), self.assertRaises(DemoError):
                settings(MAX_DOCUMENT_BYTES=value)
        self.assertEqual(settings(MAX_DOCUMENT_BYTES="1").max_document_bytes, 1)
        self.assertEqual(settings(MAX_DOCUMENT_BYTES="209715200").max_document_bytes, 209715200)

    def test_rejects_arbitrary_blob_urls_and_traversal(self):
        for name in ("", "/invoice.pdf", "../invoice.pdf", "a/../b", "a//b", "a\\b", "a\nb", "https://evil/blob"):
            with self.subTest(name=name), self.assertRaises(DemoError):
                validate_blob_name(name)
        self.assertEqual(validate_blob_name("invoices/invoice 1.pdf"), "invoices/invoice 1.pdf")

    def test_validates_agent_name(self):
        for name in ("-agent", "agent-", "agent/name", "a" * 64):
            with self.assertRaises(DemoError):
                validate_agent_name(name)
        self.assertEqual(validate_agent_name("agent-1"), "agent-1")

    def test_runtime_environment_has_no_operator_ids_or_secrets(self):
        source = ENVIRONMENT | {
            "WINDOWS_ADMIN_PASSWORD": "do-not-export",
            "AZURE_CLIENT_SECRET": "do-not-export",
        }
        exported = Settings.from_mapping(source).runtime_environment()
        self.assertNotIn("WINDOWS_ADMIN_PASSWORD", exported)
        self.assertNotIn("AZURE_CLIENT_SECRET", exported)
        self.assertNotIn("AZURE_AI_ACCOUNT_ID", exported)
        self.assertEqual(Settings.from_mapping(exported).network_mode, "byo")

    def test_admin_ids_must_match_endpoint_and_subscription(self):
        with self.assertRaisesRegex(DemoError, "different resources"):
            validate_admin_targets(settings(DOCUMENT_BLOB_ENDPOINT="https://other.blob.core.windows.net"))
        with self.assertRaises(DemoError):
            validate_admin_targets(settings(AZURE_AI_ACCOUNT_ID="/subscriptions/invalid"))


class NetworkTests(unittest.TestCase):
    @patch("private_cu_demo.network.socket.getaddrinfo")
    def test_accepts_private_and_managed_address_spaces(self, resolve):
        for address in ("10.42.2.4", "172.16.0.4", "192.168.1.4", "100.64.1.4", "::ffff:10.42.2.4"):
            resolve.return_value = [dns_record(address)]
            self.assertEqual(resolve_private("https://demo.example"), [address])

    @patch("private_cu_demo.network.socket.getaddrinfo")
    def test_rejects_public_loopback_and_metadata_addresses(self, resolve):
        for address in ("20.1.2.3", "8.8.8.8", "127.0.0.1", "169.254.169.254", "::1"):
            resolve.return_value = [dns_record(address)]
            with self.subTest(address=address), self.assertRaisesRegex(DemoError, "non-private"):
                resolve_private("https://demo.example")

    @patch("private_cu_demo.network.socket.getaddrinfo")
    def test_rejects_mixed_private_public_answers(self, resolve):
        resolve.return_value = [dns_record("10.42.2.4"), dns_record("20.1.2.3")]
        with self.assertRaises(DemoError):
            resolve_private("https://demo.example")

    @patch("private_cu_demo.network.socket.getaddrinfo", side_effect=socket.gaierror("No DNS"))
    def test_dns_failure_is_actionable(self, _):
        with self.assertRaisesRegex(DemoError, "private DNS"):
            resolve_private("https://demo.example")

    @patch("private_cu_demo.network.socket.create_connection")
    @patch("private_cu_demo.network.resolve_private")
    def test_diagnostics_report_failure_instead_of_success(self, resolve, connect):
        resolve.side_effect = [["10.42.2.4"], DemoError("public DNS")]
        report = diagnose_endpoints({"foundry": "https://one", "blob": "https://two"})
        self.assertFalse(report["ok"])
        self.assertEqual(report["failed_endpoints"], ["blob"])
        connect.assert_called_once_with(("10.42.2.4", 443), timeout=5)

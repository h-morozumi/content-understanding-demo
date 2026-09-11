import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.core import MatchConditions
from azure.core.credentials import AccessToken

from private_cu_demo.cu import ContentUnderstanding, operation_path, poll_delay
from private_cu_demo.documents import DocumentAnalysis, agent_evidence
from private_cu_demo.errors import AzureHttpError, DemoError
from private_cu_demo.http_client import AzureHttpClient

from tests.helpers import RESULT, response, settings


class HttpTests(unittest.TestCase):
    @patch("private_cu_demo.http_client.resolve_private", return_value=["10.42.2.4"])
    def test_enforces_private_dns_bearer_auth_and_no_redirects(self, resolve):
        credential = Mock()
        credential.get_token.return_value = AccessToken("test-token", 9999999999)
        client = AzureHttpClient(settings().cu_endpoint, credential, "test-scope")
        self.addCleanup(client.close)
        with patch.object(client.session, "request", return_value=response(200, {})) as request:
            client.request("GET", "/contentunderstanding/defaults")
        resolve.assert_called_once()
        credential.get_token.assert_called_once_with("test-scope")
        self.assertFalse(client.session.trust_env)
        self.assertFalse(request.call_args.kwargs["allow_redirects"])
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")

    @patch("private_cu_demo.http_client.resolve_private", side_effect=DemoError("Public DNS"))
    def test_private_dns_fails_before_acquiring_token(self, _):
        credential = Mock()
        client = AzureHttpClient(settings().cu_endpoint, credential, "test-scope")
        self.addCleanup(client.close)
        with self.assertRaises(DemoError):
            client.request("POST", "/contentunderstanding/defaults")
        credential.get_token.assert_not_called()

    @patch("private_cu_demo.http_client.resolve_private", return_value=["10.42.2.4"])
    def test_redirect_or_http_error_is_not_followed(self, _):
        client = AzureHttpClient(settings().cu_endpoint, Mock(), "test-scope")
        self.addCleanup(client.close)
        with patch.object(client.session, "request", return_value=response(302, {"secret": "not logged"})):
            with self.assertRaisesRegex(AzureHttpError, "HTTP 302") as raised:
                client.request("POST", "/contentunderstanding/defaults")
        self.assertNotIn("not logged", str(raised.exception))


class ContentUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.config = settings()
        self.client = ContentUnderstanding(self.config, Mock())
        self.addCleanup(self.client.close)
        self.http = Mock()
        self.client.http.close()
        self.client.http = self.http
        self.location = self.config.cu_endpoint + "/contentunderstanding/analyzerResults/job-1?api-version=2025-11-01"

    def accepted(self, location=None):
        return response(202, {}, **{"Operation-Location": location or self.location, "Retry-After": "0"})

    @patch("private_cu_demo.cu.time.sleep")
    def test_uploads_bytes_not_blob_url_and_polls(self, _):
        self.http.request.side_effect = [
            self.accepted(),
            response(200, {"status": "Running"}),
            response(200, {"status": "Succeeded", "result": RESULT}),
        ]
        result = self.client.analyze(b"document bytes", "application/pdf")
        self.assertEqual(result, RESULT)
        calls = self.http.request.call_args_list
        self.assertEqual(calls[0].args[0], "POST")
        self.assertIn(":analyzeBinary", calls[0].args[1])
        self.assertEqual(calls[0].kwargs["body"], b"document bytes")
        self.assertNotIn("document", calls[0].kwargs)
        self.assertEqual([call.args[0] for call in calls], ["POST", "GET", "GET"])
        self.assertTrue(all("blob.core" not in str(call) for call in calls))

    def test_rejects_operation_url_token_exfiltration(self):
        locations = (
            "https://evil.example/contentunderstanding/analyzerResults/job-1",
            "//evil.example/contentunderstanding/analyzerResults/job-1",
            "http://foundrydemo.cognitiveservices.azure.com/contentunderstanding/analyzerResults/job-1",
            self.config.cu_endpoint + "/contentunderstanding/analyzerResults/../defaults",
            self.config.cu_endpoint + "/contentunderstanding/analyzerResults/%2e%2e",
            self.config.cu_endpoint + "/contentunderstanding/analyzerResults/a/b",
            self.location + "&sig=secret",
            self.location.replace("2025-11-01", "1999-01-01"),
        )
        for location in locations:
            with self.subTest(location=location), self.assertRaises(DemoError):
                operation_path(self.config.cu_endpoint, location)
        self.assertEqual(
            operation_path(self.config.cu_endpoint, self.location),
            "/contentunderstanding/analyzerResults/job-1",
        )

    def test_rejects_missing_operation_location(self):
        self.http.request.return_value = response(202, {})
        with self.assertRaisesRegex(DemoError, "Operation-Location"):
            self.client.analyze(b"data", "text/plain")
        self.assertEqual(self.http.request.call_count, 1)

    @patch("private_cu_demo.cu.time.sleep")
    def test_failed_and_unknown_states_do_not_return_success(self, _):
        for status in ("Failed", "Canceled", "Unexpected"):
            self.http.request.side_effect = [self.accepted(), response(200, {"status": status})]
            with self.subTest(status=status), self.assertRaises(DemoError):
                self.client.analyze(b"data", "text/plain")

    @patch("private_cu_demo.cu.time.sleep")
    def test_success_without_content_is_an_error(self, _):
        self.http.request.side_effect = [
            self.accepted(),
            response(200, {"status": "Succeeded", "result": {"contents": []}}),
        ]
        with self.assertRaisesRegex(DemoError, "no document content"):
            self.client.analyze(b"data", "text/plain")

    @patch("private_cu_demo.cu.time.monotonic", side_effect=[0, 601])
    def test_polling_deadline(self, _):
        self.http.request.return_value = self.accepted()
        with self.assertRaisesRegex(DemoError, "timed out"):
            self.client.analyze(b"data", "text/plain")
        self.assertEqual(self.http.request.call_count, 1)

    @patch("private_cu_demo.cu.time.sleep")
    def test_retries_throttled_poll_without_reposting_analysis(self, sleep):
        self.http.request.side_effect = [
            self.accepted(),
            AzureHttpError("GET", 429, "request-1", "3"),
            response(200, {"status": "Succeeded", "result": RESULT}),
        ]
        self.assertEqual(self.client.analyze(b"data", "text/plain"), RESULT)
        self.assertEqual([c.args[0] for c in self.http.request.call_args_list], ["POST", "GET", "GET"])
        self.assertIn(((3,), {}), sleep.call_args_list)

    def test_rejects_empty_or_oversized_body_before_request(self):
        small = ContentUnderstanding(settings(MAX_DOCUMENT_BYTES="3"), Mock())
        self.addCleanup(small.close)
        small.http.request = Mock()
        for content in (b"", b"1234"):
            with self.assertRaises(DemoError):
                small.analyze(content, "text/plain")
        small.http.request.assert_not_called()

    def test_retry_after_validation(self):
        self.assertEqual(poll_delay(None), 2)
        self.assertEqual(poll_delay("120"), 120)
        self.assertEqual(poll_delay("Wed, 01 Jan 2020 00:00:00 GMT"), 0)
        for value in ("NaN", "inf", "-1", "invalid"):
            with self.subTest(value=value), self.assertRaises(DemoError):
                poll_delay(value)

    def test_configure_defaults_checks_support_and_readback(self):
        expected = {
            "gpt-5.2": "gpt-5.2",
            "text-embedding-3-large": "embedding",
            "prebuilt-analyzer-completion": "gpt-5.2",
            "prebuilt-analyzer-completion-mini": "gpt-5.2",
            "prebuilt-analyzer-embedding": "embedding",
        }
        self.http.get_object.side_effect = [
            {"supportedModels": {"completion": ["gpt-5.2"], "embedding": ["text-embedding-3-large"]}},
            {"modelDeployments": expected},
        ]
        self.assertEqual(self.client.configure_defaults()["modelDeployments"], expected)
        self.http.request.assert_called_once()
        self.assertEqual(self.http.request.call_args.args[0], "PATCH")

    def test_unsupported_analyzer_model_does_not_change_defaults(self):
        self.http.get_object.return_value = {"supportedModels": {"completion": ["gpt-4o"]}}
        with self.assertRaisesRegex(DemoError, "does not advertise"):
            self.client.configure_defaults()
        self.http.request.assert_not_called()


class DocumentTests(unittest.TestCase):
    @patch("private_cu_demo.documents.resolve_private", return_value=["10.42.2.4"])
    @patch("private_cu_demo.documents.BlobClient")
    def test_version_pinned_blob_is_sent_to_cu(self, blob_type, _):
        blob = blob_type.return_value.__enter__.return_value
        blob.get_blob_properties.return_value = SimpleNamespace(size=4, etag='"version-1"')
        blob.download_blob.return_value.readall.return_value = b"data"
        service = DocumentAnalysis(settings(), Mock())
        self.addCleanup(service.close)
        service.cu.analyze = Mock(return_value=RESULT)
        report = service.analyze("invoice.txt", execution_location="foundry-hosted")
        call = blob.download_blob.call_args.kwargs
        self.assertEqual(call["etag"], '"version-1"')
        self.assertEqual(call["match_condition"], MatchConditions.IfNotModified)
        self.assertEqual(call["length"], 4)
        service.cu.analyze.assert_called_once_with(b"data", "text/plain")
        self.assertEqual(report["source"]["sha256"], hashlib.sha256(b"data").hexdigest())
        self.assertEqual(report["execution"]["location"], "foundry-hosted")
        evidence = agent_evidence(report)
        self.assertNotIn("pages", evidence["contents"][0])
        self.assertIn("fields", evidence["contents"][0])

    @patch("private_cu_demo.documents.resolve_private", return_value=["10.42.2.4"])
    @patch("private_cu_demo.documents.BlobClient")
    def test_oversized_blob_is_never_downloaded(self, blob_type, _):
        blob = blob_type.return_value.__enter__.return_value
        blob.get_blob_properties.return_value = SimpleNamespace(size=21, etag="one")
        service = DocumentAnalysis(settings(MAX_DOCUMENT_BYTES="20"), Mock())
        self.addCleanup(service.close)
        with self.assertRaises(DemoError):
            service.analyze("invoice.txt", execution_location="windows-client")
        blob.download_blob.assert_not_called()

    @patch("private_cu_demo.documents.resolve_private", return_value=["10.42.2.4"])
    @patch("private_cu_demo.documents.BlobClient")
    def test_upload_does_not_overwrite_by_default(self, blob_type, _):
        service = DocumentAnalysis(settings(), Mock())
        self.addCleanup(service.close)
        blob = blob_type.return_value.__enter__.return_value
        blob.upload_blob.return_value = {"etag": "one"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invoice.txt"
            path.write_text("demo invoice", encoding="utf-8")
            service.upload(path, "invoice.txt")
        self.assertFalse(blob.upload_blob.call_args.kwargs["overwrite"])

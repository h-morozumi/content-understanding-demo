import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from private_cu_demo import cli
from private_cu_demo.errors import DemoError

from tests.helpers import RESULT, settings


class CliTests(unittest.TestCase):
    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            path.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                cli.write_result(RESULT, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "existing")

    @patch("private_cu_demo.cli.diagnose_endpoints", return_value={"ok": False})
    @patch("private_cu_demo.cli.Settings.load", return_value=settings())
    def test_diagnostics_failure_is_a_nonzero_exit(self, _, diagnose):
        args = cli.parser().parse_args(["diagnose"])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.execute(args), 1)
        self.assertFalse(json.loads(output.getvalue())["ok"])

    @patch("private_cu_demo.cli.DocumentAnalysis")
    @patch("private_cu_demo.cli.ManagedIdentityCredential")
    @patch("private_cu_demo.cli.AzureCliCredential")
    @patch("private_cu_demo.cli.Settings.load", return_value=settings())
    def test_direct_mode_uses_vm_identity_without_user_fallback(self, _, operator, managed, analysis):
        analysis.return_value.analyze.return_value = {"analysis": RESULT}
        args = cli.parser().parse_args(["analyze", "invoice.txt"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.execute(args), 0)
        managed.assert_called_once_with()
        operator.assert_not_called()
        analysis.return_value.analyze.assert_called_once_with(
            "invoice.txt", execution_location="windows-client"
        )

    @patch("private_cu_demo.cli.DocumentAnalysis")
    @patch("private_cu_demo.cli.ManagedIdentityCredential")
    @patch("private_cu_demo.cli.AIProjectClient")
    @patch("private_cu_demo.cli.resolve_private")
    @patch("private_cu_demo.cli.Settings.load", return_value=settings())
    def test_agent_mode_calls_hosted_endpoint_not_local_cu(self, _, resolve, project_type, managed, analysis):
        project = project_type.return_value.__enter__.return_value
        client = project.get_openai_client.return_value.__enter__.return_value
        client.responses.create.return_value = Mock(output_text="Grounded answer", id="response-1")
        args = cli.parser().parse_args(["agent", "invoice.txt", "--question", "Summarize."])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.execute(args), 0)
        self.assertEqual(json.loads(output.getvalue())["answer"], "Grounded answer")
        self.assertEqual(project.get_openai_client.call_args.kwargs["agent_name"], "private-cu-agent")
        self.assertEqual(project.get_openai_client.call_args.kwargs["max_retries"], 0)
        payload = json.loads(client.responses.create.call_args.kwargs["input"])
        self.assertEqual(payload["blob_name"], "invoice.txt")
        analysis.assert_not_called()

    @patch("private_cu_demo.cli.execute", side_effect=DemoError("private DNS is missing"))
    def test_expected_error_is_reported_without_success(self, _):
        with patch("sys.argv", ["private-cu", "diagnose"]):
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.main(), 1)
        self.assertIn("private DNS is missing", error.getvalue())

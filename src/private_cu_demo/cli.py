from __future__ import annotations

import argparse
import json
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import requests
from azure.ai.projects import AIProjectClient
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.identity import AzureCliCredential, ManagedIdentityCredential
from openai import APIError

from .config import Settings, validate_blob_name
from .cu import ContentUnderstanding
from .deployment import deploy_agent, export_requirements, make_archive, validate_admin_targets
from .documents import DocumentAnalysis
from .errors import DemoError
from .network import diagnose_endpoints, resolve_private


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run private Blob/CU operations and a real Foundry hosted agent."
    )
    result.add_argument("--config", type=Path, help="Non-secret JSON exported from one azd environment.")
    commands = result.add_subparsers(dest="command", required=True)
    for name, description in (
        ("diagnose", "Check private DNS and TCP connectivity from this machine."),
        ("upload", "Upload a document into the configured private container."),
        ("analyze", "Run CU directly from this machine, without an agent."),
        ("agent", "Invoke the deployed agent; Blob and CU access execute in Foundry."),
        ("configure-cu", "Set model defaults using the signed-in Azure CLI operator."),
        ("deploy-agent", "Deploy hosted source code and assign the agent's runtime roles."),
        ("package-agent", "Build a credential-free source ZIP without contacting Azure."),
    ):
        command = commands.add_parser(name, help=description)
        if name in ("upload", "analyze", "agent"):
            command.add_argument(
                "--credential", choices=("managed-identity", "cli"), default="managed-identity"
            )
        if name == "upload":
            command.add_argument("file", type=Path)
            command.add_argument("--name", help="Destination blob name; defaults to the file name.")
            command.add_argument("--overwrite", action="store_true")
        if name in ("analyze", "agent"):
            command.add_argument("blob", help="Exact relative blob name, not a URL.")
        if name == "agent":
            command.add_argument(
                "--question",
                default="Summarize the document and its key fields. Flag missing or uncertain values.",
            )
        if name in ("deploy-agent", "package-agent"):
            command.add_argument("--source-root", type=Path, default=Path.cwd())
        if name == "package-agent":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--output", type=Path, help="Write JSON to a new local file.")
    return result


def write_result(value: object, output: Path | None) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(serialized, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as destination:
        destination.write(serialized)
    print(f"Saved {output}")


def execute(args: argparse.Namespace) -> int:
    if args.command == "package-agent":
        root = args.source_root.resolve()
        payload = make_archive(root, export_requirements(root))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as destination:
            destination.write(payload)
        print(f"Packaged hosted agent source: {args.output} ({len(payload)} bytes)")
        return 0
    settings = Settings.load(args.config)
    if args.output is not None and args.output.exists():
        raise DemoError(f"Output already exists: {args.output}. Choose a new file.")
    if args.command == "diagnose":
        report = diagnose_endpoints(
            {
                "foundry": settings.project_endpoint,
                "content_understanding": settings.cu_endpoint,
                "blob": settings.blob_endpoint,
            }
        )
        write_result(report, args.output)
        return 0 if report["ok"] else 1
    if args.command in ("configure-cu", "deploy-agent"):
        subscription = validate_admin_targets(settings)
        with AzureCliCredential(subscription=subscription) as credential:
            if args.command == "configure-cu":
                with closing(ContentUnderstanding(settings, credential)) as cu:
                    value = cu.configure_defaults()
            else:
                value = deploy_agent(settings, credential, args.source_root.resolve())
    else:
        credential = (
            AzureCliCredential()
            if args.credential == "cli"
            else ManagedIdentityCredential()
        )
        with credential:
            if args.command == "agent":
                validate_blob_name(args.blob)
                if not args.question.strip() or len(args.question) > 4000:
                    raise DemoError("The question must contain 1-4000 characters.")
                resolve_private(settings.project_endpoint)
                with AIProjectClient(
                    endpoint=settings.project_endpoint, credential=credential, allow_preview=True
                ) as project:
                    with project.get_openai_client(
                        agent_name=settings.agent_name,
                        timeout=settings.analysis_timeout + 180,
                        max_retries=0,
                    ) as client:
                        response = client.responses.create(
                            input=json.dumps(
                                {"blob_name": args.blob, "question": args.question},
                                ensure_ascii=False,
                            ),
                            stream=False,
                        )
                if not response.output_text:
                    raise DemoError("The hosted agent returned no textual answer.")
                value = {
                    "agent": settings.agent_name,
                    "response_id": response.id,
                    "answer": response.output_text,
                }
            else:
                with closing(DocumentAnalysis(settings, credential)) as analysis:
                    if args.command == "upload":
                        value = analysis.upload(
                            args.file, args.name or args.file.name, overwrite=args.overwrite
                        )
                    else:
                        value = analysis.analyze(
                            args.blob, execution_location="windows-client"
                        )
    write_result(value, args.output)
    return 0


def main() -> int:
    args = parser().parse_args()
    try:
        return execute(args)
    except (
        DemoError,
        OSError,
        json.JSONDecodeError,
        requests.RequestException,
        ClientAuthenticationError,
        HttpResponseError,
        ServiceRequestError,
        ServiceResponseError,
        APIError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Dependency export failed: {exc.stderr}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

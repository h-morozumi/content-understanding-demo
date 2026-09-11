import json

import requests

from private_cu_demo.config import Settings

SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
ACCOUNT_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-demo"
    "/providers/Microsoft.CognitiveServices/accounts/foundrydemo"
)
STORAGE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-demo"
    "/providers/Microsoft.Storage/storageAccounts/docsdemo"
)
ENVIRONMENT = {
    "AZURE_AI_PROJECT_ENDPOINT": "https://foundrydemo.services.ai.azure.com/api/projects/demo",
    "CONTENT_UNDERSTANDING_ENDPOINT": "https://foundrydemo.cognitiveservices.azure.com",
    "DOCUMENT_BLOB_ENDPOINT": "https://docsdemo.blob.core.windows.net",
    "DOCUMENT_CONTAINER_NAME": "documents",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "gpt-5.2",
    "CU_COMPLETION_DEPLOYMENT": "gpt-5.2",
    "CU_EMBEDDING_DEPLOYMENT": "embedding",
    "FOUNDRY_NETWORK_MODE": "byo",
    "AZURE_AI_ACCOUNT_ID": ACCOUNT_ID,
    "DOCUMENT_STORAGE_ACCOUNT_ID": STORAGE_ID,
    "AZURE_AI_PROJECT_ID": ACCOUNT_ID + "/projects/demo",
}
RESULT = {
    "analyzerId": "prebuilt-invoice",
    "contents": [
        {
            "path": "input1",
            "markdown": "Invoice total: USD 432.00",
            "fields": {"Total": {"type": "number", "valueNumber": 432, "confidence": 0.95}},
            "pages": [{"words": [{"content": "Invoice"}]}],
        }
    ],
    "warnings": [],
}


def settings(**overrides: object) -> Settings:
    return Settings.from_mapping(ENVIRONMENT | overrides)


def response(status: int, value: object = None, **headers: str) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.headers.update(headers)
    result._content = json.dumps(value).encode("utf-8")
    return result


def dns_record(address: str) -> tuple:
    return (2, 1, 6, "", (address, 443))

class DemoError(RuntimeError):
    """An actionable configuration, connectivity, or service failure."""


class AzureHttpError(DemoError):
    def __init__(
        self, method: str, status_code: int, request_id: str, retry_after: str | None
    ) -> None:
        super().__init__(
            f"Azure {method} failed: HTTP {status_code}; request ID: {request_id}. "
            "Check RBAC, private endpoints, and service limits."
        )
        self.status_code = status_code
        self.retry_after = retry_after

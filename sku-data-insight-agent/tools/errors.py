class ToolExecutionError(RuntimeError):
    def __init__(self, message: str, error_type: str = "INTERNAL_ERROR") -> None:
        super().__init__(message)
        self.error_type = error_type


class ToolPolicyError(ToolExecutionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "POLICY_DENIED")

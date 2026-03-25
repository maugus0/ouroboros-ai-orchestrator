"""Custom exception classes for the Orchestrator service."""


class OuroborosBaseError(Exception):
    """Base exception for all Ouroboros errors."""

    def __init__(self, message: str = "An unexpected error occurred", status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class DatabaseError(OuroborosBaseError):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(message=message, status_code=500)


class AuthenticationError(OuroborosBaseError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message=message, status_code=401)


class AuthorizationError(OuroborosBaseError):
    """Raised when a user lacks permission."""

    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message=message, status_code=403)


class NotFoundError(OuroborosBaseError):
    """Raised when a requested resource is not found."""

    def __init__(self, resource: str = "Resource"):
        super().__init__(message=f"{resource} not found", status_code=404)


class ValidationError(OuroborosBaseError):
    """Raised when request validation fails beyond Pydantic checks."""

    def __init__(self, message: str = "Validation failed"):
        super().__init__(message=message, status_code=422)


class AgentCallError(OuroborosBaseError):
    """Raised when an HTTP call to an agent microservice fails."""

    def __init__(self, agent_name: str, message: str = "Agent call failed"):
        self.agent_name = agent_name
        super().__init__(message=f"[{agent_name}] {message}", status_code=502)


class WorkflowError(OuroborosBaseError):
    """Raised when a workflow state transition is invalid."""

    def __init__(self, message: str = "Invalid workflow transition"):
        super().__init__(message=message, status_code=409)

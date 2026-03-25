"""Data-access layer for the agent_call_logs audit table."""

from app.core.database import get_pool
from app.core.logging import get_logger

logger = get_logger(__name__)


class AgentCallLogRepository:
    """Insert and query audit records for agent HTTP calls."""

    # Implementation will be added when we build the workflow feature.
    pass

"""Data-access layer for workflow_runs and workflow_results tables."""

from app.core.database import get_pool
from app.core.logging import get_logger

logger = get_logger(__name__)


class WorkflowRepository:
    """CRUD operations on ``workflow_runs`` and ``workflow_results`` tables."""

    # Implementation will be added when we build the workflow feature.
    pass

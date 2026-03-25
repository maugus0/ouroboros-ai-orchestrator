"""Workflow state-machine logic — sequential agent orchestration."""

from app.core.logging import get_logger

logger = get_logger(__name__)


class WorkflowService:
    """
    Drives the sequential workflow:
    Profile → Programs → Scholarships → Eligibility → Application Support

    Stores the current state, enables retry from the last successful step,
    and aggregates results into the orchestrator DB.
    """

    # Implementation will be added when we build the workflow feature.
    pass

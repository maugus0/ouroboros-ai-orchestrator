"""Workflow state-machine logic — sequential agent orchestration."""


class WorkflowService:
    """
    Drives the sequential workflow:
    Profile → Programs → Scholarships → Eligibility → Application Support

    Stores the current state, enables retry from the last successful step,
    and aggregates results into the orchestrator DB.
    """

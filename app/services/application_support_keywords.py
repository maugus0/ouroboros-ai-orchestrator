"""Shared application-support keyword helpers."""

SOP_KEYWORDS: frozenset[str] = frozenset({"sop", "statement of purpose", "personal statement"})
COVER_LETTER_KEYWORDS: frozenset[str] = frozenset({"cover letter"})
DEADLINE_KEYWORDS: frozenset[str] = frozenset({"deadline", "deadlines", "timeline", "application timeline"})
CHECKLIST_KEYWORDS: frozenset[str] = frozenset({"checklist", "document list", "application steps", "application plan"})

APPLICATION_SUPPORT_KEYWORDS: frozenset[str] = frozenset(
    SOP_KEYWORDS | COVER_LETTER_KEYWORDS | DEADLINE_KEYWORDS | CHECKLIST_KEYWORDS
)


def detect_application_support_action(user_message: str) -> str:
    """Map an application-support request to the downstream operation group."""
    lowered = (user_message or "").lower()
    if any(token in lowered for token in SOP_KEYWORDS):
        return "sop"
    if any(token in lowered for token in COVER_LETTER_KEYWORDS):
        return "cover_letter"
    if any(token in lowered for token in DEADLINE_KEYWORDS):
        return "deadlines"
    if any(token in lowered for token in CHECKLIST_KEYWORDS):
        return "checklist"
    return "checklist"

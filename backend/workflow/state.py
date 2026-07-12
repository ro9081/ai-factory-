"""
state.py — LangGraph GraphState TypedDict.
Matches the database entities so the graph can be driven by
persisted story data and write back cleanly.
"""
from typing import TypedDict


class GraphState(TypedDict):
    story_id: str          # UUID string matching stories.id
    latest_comment: str    # Full conversation context (description + Q&A thread)
    needs_clarification: bool  # PM agent decision flag
    prd_content: str       # Generated PRD (filled by PRD writer)
    status: str            # Current story status string
    clarification_rounds: int  # Number of PM answers submitted so far (max 3)

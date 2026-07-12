"""
graph.py — LangGraph 3-agent state machine powered by Groq LLM.

Agents:
  1. pm_agent         — Evaluates if the story (including PM answers so far)
                        still needs more clarification. Enforces a 3-round maximum.
  2. clarifier_agent  — Asks targeted follow-up questions, aware of prior rounds.
                        Status → "Clarifying".
  3. prd_writer_agent — Writes a full, structured PRD using the full Q&A thread.
                        Status → "Green_Light".

Multi-round clarification:
  - Each time the PM submits answers, clarification_rounds increments.
  - PM Agent re-evaluates after each round.
  - If still unclear AND rounds < 3  → Clarifier asks follow-up questions.
  - If satisfied OR rounds >= 3      → PRD Writer generates the document.

LLM is initialised lazily from backend.config.settings.
"""
from __future__ import annotations

import json
import logging
import re

from langgraph.graph import StateGraph, END

from backend.workflow.state import GraphState

logger = logging.getLogger(__name__)

MAX_CLARIFICATION_ROUNDS = 3

# ---------------------------------------------------------------------------
# LLM factory — lazy singleton
# ---------------------------------------------------------------------------

_llm = None


def get_llm():
    """Return a shared ChatGroq instance, initialised on first call."""
    global _llm
    if _llm is None:
        from backend.config import settings
        from langchain_groq import ChatGroq

        if not settings.llm_ready:
            raise EnvironmentError(
                "GROQ_API_KEY is missing or invalid. "
                "Please set a valid Groq key (starts with gsk_) in .env and restart the server."
            )

        _llm = ChatGroq(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            api_key=settings.groq_api_key,
        )
        logger.info("LLM initialised: provider=Groq  model=%s", settings.llm_model)
    return _llm


# ---------------------------------------------------------------------------
# Agent node functions
# ---------------------------------------------------------------------------

def pm_agent(state: GraphState) -> GraphState:
    """
    PM Agent — decides whether the story needs more clarification.

    Logic:
    1. If clarification_rounds >= MAX_CLARIFICATION_ROUNDS → force PRD (no more asking).
    2. If status is "Clarifying" (PM already answered at least once) → ask LLM to
       re-evaluate whether the answers cover enough to write a good PRD.
    3. If status is "Draft" (first evaluation) → ask LLM for initial assessment.
    """
    rounds  = state.get("clarification_rounds", 0)
    status  = state.get("status", "Draft")
    context = state.get("latest_comment", "")

    # Hard ceiling — after 3 rounds of Q&A, write the PRD with whatever we have
    if rounds >= MAX_CLARIFICATION_ROUNDS:
        logger.info(
            "[PM Agent] Max clarification rounds (%d) reached → routing to PRD writer",
            MAX_CLARIFICATION_ROUNDS,
        )
        return {**state, "needs_clarification": False}

    from langchain_core.messages import SystemMessage, HumanMessage

    if status == "Clarifying":
        # Re-evaluate: do the PM's answers resolve the remaining unknowns?
        system_prompt = (
            "You are a senior Product Manager reviewing a clarification thread. "
            "The agent previously asked questions, and the PM has now responded.\n\n"
            f"This is round {rounds} of {MAX_CLARIFICATION_ROUNDS} maximum clarification rounds.\n\n"
            "Evaluate whether the PM's answers, combined with the original story, "
            "provide SUFFICIENT information to write a comprehensive PRD. "
            "Consider: user persona, success metrics, key constraints, acceptance criteria.\n\n"
            "If you still have specific, unanswered gaps, set needs_clarification=true. "
            "If the story is clear enough to write a PRD (even if imperfect), set needs_clarification=false.\n\n"
            "Respond ONLY with valid JSON — no markdown, no extra text:\n"
            '{"needs_clarification": true|false, "reason": "<one sentence>"}'
        )
        user_prompt = (
            f"Full conversation thread:\n\"\"\"\n{context}\n\"\"\"\n\n"
            "Are there still critical gaps that must be resolved before writing the PRD?"
        )
    else:
        # First-time evaluation of a Draft story
        system_prompt = (
            "You are a senior Product Manager reviewing a new user story. "
            "Decide whether it has enough information to write a comprehensive PRD, "
            "or whether clarifying questions are needed first.\n\n"
            "A story needs clarification if it is vague about: who the user is, "
            "what success looks like, what the feature does, or key constraints.\n\n"
            "Respond ONLY with valid JSON — no markdown, no extra text:\n"
            '{"needs_clarification": true|false, "reason": "<one sentence>"}'
        )
        user_prompt = (
            f"Story description:\n\"\"\"\n{context}\n\"\"\"\n\n"
            "Does this story need clarification before writing a PRD?"
        )

    llm = get_llm()
    response = llm.invoke([SystemMessage(content=system_prompt),
                           HumanMessage(content=user_prompt)])

    raw = response.content.strip()
    logger.info("[PM Agent] Round=%d  Raw response: %s", rounds, raw)

    json_str = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        decision = json.loads(json_str)
        needs_clarification = bool(decision.get("needs_clarification", True))
        reason = decision.get("reason", "")
    except (json.JSONDecodeError, ValueError):
        logger.warning("[PM Agent] JSON parse failed — defaulting to needs_clarification=True")
        needs_clarification = True
        reason = "Could not parse LLM response; requesting clarification as a safe default."

    logger.info(
        "[PM Agent] Round=%d  Decision: needs_clarification=%s | %s",
        rounds, needs_clarification, reason,
    )
    return {**state, "needs_clarification": needs_clarification}


def clarifier_agent(state: GraphState) -> GraphState:
    """
    Clarifier Agent — generates targeted follow-up questions.

    Is aware of the current round number so it can ask different/deeper questions
    each time rather than repeating the same set.
    Status → "Clarifying".
    """
    context  = state.get("latest_comment", "")
    story_id = state.get("story_id", "unknown")
    rounds   = state.get("clarification_rounds", 0)

    from langchain_core.messages import SystemMessage, HumanMessage

    if rounds == 0:
        # First round — initial clarifying questions
        round_instruction = (
            "This is the FIRST clarification round. "
            "Ask 3–5 foundational questions covering: user persona, success metrics, "
            "key constraints, and primary use cases."
        )
    else:
        # Follow-up rounds — dig into remaining gaps
        round_instruction = (
            f"This is clarification round {rounds + 1} of {MAX_CLARIFICATION_ROUNDS}. "
            "The PM has already answered some questions. Review what has been answered "
            "and ask only about the REMAINING gaps or aspects that need deeper detail. "
            "Do NOT repeat questions that were already answered. "
            "Focus on the most critical unresolved information needed to write the PRD."
        )

    system_prompt = (
        "You are an expert Product Manager skilled at refining user stories through dialogue. "
        f"{round_instruction}\n\n"
        "Rules:\n"
        "- Be specific — reference details from the conversation where possible.\n"
        "- Number your questions clearly (1., 2., etc.).\n"
        "- Ask at most 4 questions per round.\n"
        "- Do NOT answer the questions yourself.\n"
        "- Format: numbered list only, no preamble or closing remarks."
    )

    user_prompt = (
        f"Full story context and conversation so far:\n\"\"\"\n{context}\n\"\"\"\n\n"
        "What clarifying questions do you still need answered?"
    )

    llm = get_llm()
    response = llm.invoke([SystemMessage(content=system_prompt),
                           HumanMessage(content=user_prompt)])

    questions = response.content.strip()
    logger.info(
        "[Clarifier Agent] Round=%d  Generated questions for story %s",
        rounds + 1, story_id,
    )

    rounds_remaining = MAX_CLARIFICATION_ROUNDS - (rounds + 1)
    rounds_note = (
        f"\n\n*({rounds_remaining} clarification round(s) remaining before PRD is auto-generated.)*"
        if rounds_remaining > 0 else
        "\n\n*This is the final clarification round. Your next response will trigger PRD generation.*"
    )

    agent_message = (
        f"**[Clarifier Agent — Round {rounds + 1}/{MAX_CLARIFICATION_ROUNDS}]** "
        f"Before writing the PRD, I need answers to the following:\n\n"
        + questions
        + rounds_note
    )

    return {
        **state,
        "latest_comment": agent_message,
        "status": "Clarifying",
        "prd_content": "",
    }


def prd_writer_agent(state: GraphState) -> GraphState:
    """
    PRD Writer Agent — generates a full, structured PRD in Markdown.
    Uses the complete Q&A conversation thread as context.
    Status → "Green_Light".
    """
    context  = state.get("latest_comment", "")
    story_id = state.get("story_id", "unknown")
    rounds   = state.get("clarification_rounds", 0)

    from langchain_core.messages import SystemMessage, HumanMessage

    rounds_note = (
        f" ({rounds} round(s) of clarification completed)" if rounds > 0 else " (no clarification needed)"
    )

    system_prompt = (
        "You are a world-class Product Manager. Write a clear, structured PRD "
        "in Markdown for the feature described below.\n\n"
        "Required sections (use ## headings):\n"
        "1. Overview — one-paragraph summary of the feature and its purpose.\n"
        "2. Problem Statement — what pain or gap this solves.\n"
        "3. Goals — 3-5 bullet-point measurable goals.\n"
        "4. Non-Goals — what is explicitly out of scope.\n"
        "5. User Personas — who will use this feature and why.\n"
        "6. User Stories — 2-4 'As a ... I want ... so that ...' stories.\n"
        "7. Acceptance Criteria — checkboxes (- [ ] ...) for each story.\n"
        "8. Technical Considerations — constraints, APIs, data models, or risks.\n"
        "9. Open Questions — remaining unknowns (can be empty if none).\n\n"
        "IMPORTANT: Incorporate ALL information from the clarification thread below. "
        "The PM's answers should be directly reflected in the PRD content. "
        "Be specific, concise, and actionable. Avoid generic filler."
    )

    user_prompt = (
        f"Story ID: {story_id}{rounds_note}\n\n"
        f"Full context (original story + clarification Q&A):\n\"\"\"\n{context}\n\"\"\"\n\n"
        "Write the complete PRD now."
    )

    llm = get_llm()
    response = llm.invoke([SystemMessage(content=system_prompt),
                           HumanMessage(content=user_prompt)])

    prd_content = response.content.strip()
    logger.info(
        "[PRD Writer Agent] PRD written for story %s (%d chars, %d clarification rounds)",
        story_id, len(prd_content), rounds,
    )

    agent_message = (
        "**[PRD Writer Agent]** PRD has been generated and is ready for review. "
        f"Generated after {rounds} clarification round(s)."
    )

    return {
        **state,
        "latest_comment": agent_message,
        "prd_content": prd_content,
        "status": "Green_Light",
    }


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------

def route_after_pm(state: GraphState) -> str:
    """Return the next node name based on PM agent's decision."""
    return "clarifier_agent" if state["needs_clarification"] else "prd_writer_agent"


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    builder = StateGraph(GraphState)

    builder.add_node("pm_agent",         pm_agent)
    builder.add_node("clarifier_agent",  clarifier_agent)
    builder.add_node("prd_writer_agent", prd_writer_agent)

    builder.set_entry_point("pm_agent")

    builder.add_conditional_edges(
        "pm_agent",
        route_after_pm,
        {
            "clarifier_agent":  "clarifier_agent",
            "prd_writer_agent": "prd_writer_agent",
        },
    )

    builder.add_edge("clarifier_agent",  END)
    builder.add_edge("prd_writer_agent", END)

    return builder.compile()


# Module-level compiled graph — import this from resolvers
workflow_graph = build_graph()

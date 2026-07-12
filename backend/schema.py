"""
schema.py — Strawberry GraphQL types, queries, and mutations.

Types:     CommentType, StoryType
Queries:   stories(), story(id)
Mutations: createStory(title, description)
           submitClarification(story_id, text)  ← PM posts answers
           runWorkflow(story_id)                ← triggers LangGraph
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

import strawberry
from strawberry.fastapi import GraphQLRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import AsyncSessionLocal
from backend.models import Story, Comment
from backend.workflow.graph import workflow_graph
from backend.workflow.state import GraphState


# ---------------------------------------------------------------------------
# Strawberry output types
# ---------------------------------------------------------------------------

@strawberry.type
class CommentType:
    id: str
    story_id: str
    author: str
    text: str
    created_at: datetime


@strawberry.type
class StoryType:
    id: str
    title: str
    description: str
    status: str
    comments: List[CommentType]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _story_to_type(story: Story) -> StoryType:
    return StoryType(
        id=story.id,
        title=story.title,
        description=story.description,
        status=story.status,
        comments=[
            CommentType(
                id=c.id,
                story_id=c.story_id,
                author=c.author,
                text=c.text,
                created_at=c.created_at,
            )
            for c in (story.comments or [])
        ],
    )


async def _get_story_with_comments(session, story_id: str) -> Optional[Story]:
    result = await session.execute(
        select(Story)
        .options(selectinload(Story.comments))
        .where(Story.id == story_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@strawberry.type
class Query:
    @strawberry.field
    async def stories(self) -> List[StoryType]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Story).options(selectinload(Story.comments))
            )
            stories = result.scalars().all()
            return [_story_to_type(s) for s in stories]

    @strawberry.field
    async def story(self, id: str) -> Optional[StoryType]:
        async with AsyncSessionLocal() as session:
            s = await _get_story_with_comments(session, id)
            return _story_to_type(s) if s else None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_story(self, title: str, description: str) -> StoryType:
        """Insert a new Story with Draft status."""
        async with AsyncSessionLocal() as session:
            story = Story(
                id=str(uuid.uuid4()),
                title=title,
                description=description,
                status="Draft",
            )
            session.add(story)
            await session.commit()
            await session.refresh(story)
            # Reload with comments relationship (empty at this point)
            s = await _get_story_with_comments(session, story.id)
            return _story_to_type(s)

    @strawberry.mutation
    async def run_workflow(self, story_id: str) -> StoryType:
        """
        Execute the LangGraph 3-agent pipeline for a story.
        Persists the state changes (new comment + status update) to the DB.
        Returns the updated StoryType with the new comment thread.
        """
        async with AsyncSessionLocal() as session:
            story = await _get_story_with_comments(session, story_id)
            if story is None:
                raise ValueError(f"Story {story_id} not found.")

            # Count how many times the PM has already answered
            # (each PM comment = one completed clarification round)
            clarification_rounds = sum(1 for c in story.comments if c.author == "PM")

            # Build the initial GraphState from DB state.
            # When Clarifying: compile the FULL Q&A thread so the PRD Writer
            # has both the agent's questions and the PM's answers as context.
            if story.status == "Clarifying" and story.comments:
                # Reconstruct the conversation thread for rich context
                lines = [f"Original story description:\n{story.description}\n"]
                for c in story.comments:
                    label = "Agent questions" if c.author == "Agent" else "PM clarification"
                    lines.append(f"{label}:\n{c.text}")
                latest_comment = "\n\n".join(lines)
            else:
                latest_comment = (
                    story.comments[-1].text if story.comments else story.description
                )

            initial_state: GraphState = {
                "story_id": story.id,
                "latest_comment": latest_comment,
                "needs_clarification": False,
                "prd_content": "",
                "status": story.status,
                "clarification_rounds": clarification_rounds,
            }

            # Invoke the compiled LangGraph (synchronous invoke — safe in async context
            # because the graph nodes are pure Python, no async I/O)
            final_state: GraphState = workflow_graph.invoke(initial_state)

            # Persist: update story status
            story.status = final_state["status"]

            # Persist: add the agent comment
            agent_comment = Comment(
                id=str(uuid.uuid4()),
                story_id=story.id,
                author="Agent",
                text=final_state["latest_comment"],
            )
            session.add(agent_comment)

            # If a PRD was produced, store it as a second comment block
            if final_state.get("prd_content"):
                prd_comment = Comment(
                    id=str(uuid.uuid4()),
                    story_id=story.id,
                    author="Agent",
                    text=final_state["prd_content"],
                )
                session.add(prd_comment)

            await session.commit()

            # Reload fresh story + comments
            updated = await _get_story_with_comments(session, story.id)
            return _story_to_type(updated)

    @strawberry.mutation
    async def submit_clarification(self, story_id: str, text: str) -> StoryType:
        """
        Post a PM clarification answer as a comment on a Clarifying story.
        This does NOT run the workflow — the PM submits answers first,
        then clicks Run Workflow to generate the PRD with full context.
        """
        async with AsyncSessionLocal() as session:
            story = await _get_story_with_comments(session, story_id)
            if story is None:
                raise ValueError(f"Story {story_id} not found.")
            if story.status != "Clarifying":
                raise ValueError(
                    f"Story is in status '{story.status}'. "
                    "Only Clarifying stories can receive clarification answers."
                )

            pm_comment = Comment(
                id=str(uuid.uuid4()),
                story_id=story_id,
                author="PM",
                text=text.strip(),
            )
            session.add(pm_comment)
            await session.commit()

            updated = await _get_story_with_comments(session, story_id)
            return _story_to_type(updated)


# ---------------------------------------------------------------------------
# GraphQL router (mounted in main.py)
# ---------------------------------------------------------------------------

schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_router = GraphQLRouter(schema, graphql_ide="graphiql")

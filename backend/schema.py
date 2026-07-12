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
from typing import List, Optional, Any

import strawberry
from strawberry.types import Info
from strawberry.fastapi import GraphQLRouter
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import AsyncSessionLocal
from backend.models import Story, Comment, User
from backend.workflow.graph import workflow_graph
from backend.workflow.state import GraphState
from backend.auth import decode_access_token


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

async def get_context(request: Request):
    user = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        payload = decode_access_token(token)
        if payload and "sub" in payload:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.id == payload["sub"])
                )
                user = result.scalar_one_or_none()
    return {"user": user}


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
class IsAuthenticated(strawberry.BasePermission):
    message = "User is not authenticated"
    async def has_permission(self, source: Any, info: Info, **kwargs) -> bool:
        return info.context.get("user") is not None

class IsPM(strawberry.BasePermission):
    message = "Only Product Managers can perform this action"
    async def has_permission(self, source: Any, info: Info, **kwargs) -> bool:
        user = info.context.get("user")
        return user is not None and user.role == "PM"

class IsAdminOrPM(strawberry.BasePermission):
    message = "Only Admins or PMs can perform this action"
    async def has_permission(self, source: Any, info: Info, **kwargs) -> bool:
        user = info.context.get("user")
        return user is not None and user.role in ("Admin", "PM")

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


@strawberry.type
class UserType:
    id: str
    username: str
    role: str


@strawberry.type
class AuthResponse:
    token: str
    user: UserType


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
from backend.auth import get_password_hash, verify_password, create_access_token

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def register(self, username: str, password: str, role: str) -> AuthResponse:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            if result.scalars().first():
                raise ValueError("Username already taken")
            user = User(
                username=username,
                password_hash=get_password_hash(password),
                role=role
            )
            session.add(user)
            await session.commit()
            token = create_access_token({"sub": user.id, "role": user.role})
            return AuthResponse(token=token, user=UserType(id=user.id, username=user.username, role=user.role))

    @strawberry.mutation
    async def login(self, username: str, password: str) -> AuthResponse:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalars().first()
            if not user or not verify_password(password, user.password_hash):
                raise ValueError("Invalid credentials")
            token = create_access_token({"sub": user.id, "role": user.role})
            return AuthResponse(token=token, user=UserType(id=user.id, username=user.username, role=user.role))

    @strawberry.mutation(permission_classes=[IsPM])
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
            # When Clarifying or Green_Light (revision mode): compile the FULL Q&A 
            # thread so the PRD Writer has both the questions and answers as context.
            if story.status in ("Clarifying", "Green_Light") and story.comments:
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

            # Determine which agent spoke based on the final status
            main_agent_name = "Clarifier" if final_state["status"] == "Clarifying" else "PRD Writer"
            
            # Persist: add the agent comment
            agent_comment = Comment(
                id=str(uuid.uuid4()),
                story_id=story.id,
                author=main_agent_name,
                text=final_state["latest_comment"],
            )
            session.add(agent_comment)

            # If a PRD was produced, store it as a second comment block
            if final_state.get("prd_content"):
                prd_comment = Comment(
                    id=str(uuid.uuid4()),
                    story_id=story.id,
                    author="PRD Writer",
                    text=final_state["prd_content"],
                )
                session.add(prd_comment)

            await session.commit()

            # Reload fresh story + comments
            updated = await _get_story_with_comments(session, story.id)
            return _story_to_type(updated)

    @strawberry.mutation(permission_classes=[IsPM])
    async def submit_clarification(self, story_id: str, text: str) -> StoryType:
        """
        Post a PM clarification answer or PRD revision as a comment.
        If the story is in Green_Light, this suggests changes and resets it to Clarifying.
        """
        async with AsyncSessionLocal() as session:
            story = await _get_story_with_comments(session, story_id)
            if story is None:
                raise ValueError(f"Story {story_id} not found.")
            if story.status not in ("Clarifying", "Green_Light"):
                raise ValueError(
                    f"Story is in status '{story.status}'. "
                    "Comments can only be submitted during Clarifying or Green_Light."
                )

            # If it's a revision on a generated PRD, revert status to trigger regeneration
            if story.status == "Green_Light":
                story.status = "Clarifying"


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

    @strawberry.mutation(permission_classes=[IsAdminOrPM])
    async def accept_story(self, story_id: str) -> StoryType:
        """Manually transition a story from Green_Light to Accepted."""
        async with AsyncSessionLocal() as session:
            story = await _get_story_with_comments(session, story_id)
            if story is None:
                raise ValueError(f"Story {story_id} not found.")
            if story.status != "Green_Light":
                raise ValueError("Only stories in Green_Light state can be accepted.")
            
            story.status = "Accepted"
            await session.commit()
            updated = await _get_story_with_comments(session, story_id)
            return _story_to_type(updated)

    @strawberry.mutation(permission_classes=[IsAdminOrPM])
    async def delete_story(self, story_id: str) -> bool:
        """Delete a story and all its associated comments."""
        async with AsyncSessionLocal() as session:
            story = await session.get(Story, story_id)
            if not story:
                return False
            
            await session.delete(story)
            await session.commit()
            return True


# ---------------------------------------------------------------------------

# GraphQL router (mounted in main.py)
# ---------------------------------------------------------------------------

schema = strawberry.Schema(query=Query, mutation=Mutation)
graphql_router = GraphQLRouter(schema, context_getter=get_context, graphql_ide="graphiql")

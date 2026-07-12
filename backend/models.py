"""
models.py — SQLAlchemy ORM models for Story and Comment.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, ForeignKey, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from backend.database import Base


class StoryStatus(str, enum.Enum):
    Draft = "Draft"
    Clarifying = "Clarifying"
    Green_Light = "Green_Light"
    Accepted = "Accepted"


class CommentAuthor(str, enum.Enum):
    PM = "PM"
    Agent = "Agent"


class UserRole(str, enum.Enum):
    PM = "PM"
    Engineer = "Engineer"
    Admin = "Admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.PM.value)


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StoryStatus.Draft.value
    )

    comments: Mapped[list["Comment"]] = relationship(
        "Comment", back_populates="story", cascade="all, delete-orphan",
        order_by="Comment.created_at"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Story id={self.id} title={self.title!r} status={self.status}>"


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    story_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stories.id"), nullable=False, index=True
    )
    author: Mapped[str] = mapped_column(String(10), nullable=False)  # "PM" | "Agent"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    story: Mapped["Story"] = relationship("Story", back_populates="comments")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Comment id={self.id} author={self.author} story_id={self.story_id}>"

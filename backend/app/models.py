from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column, Session
from datetime import datetime, date
from typing import List

from .database import Base


class ParentUser(Base):
    __tablename__ = "parent_users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    children: Mapped[List["Child"]] = relationship(
        "Child", back_populates="parent_user"
    )
    auth_sessions: Mapped[List["AuthSession"]] = relationship(
        "AuthSession", back_populates="user"
    )


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    parent_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("parent_users.id"), nullable=False
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    pin_hash: Mapped[str] = mapped_column(String, nullable=False)

    # Bakalá®®í®® API data
    bakalari_student_id: Mapped[str] = mapped_column(String, nullable=True)
    bakalari_class_id: Mapped[str] = mapped_column(String, nullable=True)

    # Nastavení®® odměn
    reward_per_grade: Mapped[float] = mapped_column(Float, default=0.0)

    # Synchronizační®® stav
    sync_state: Mapped["SyncState"] = relationship(
        "SyncState", back_populates="child", uselist=False, cascade="all, delete-orphan"
    )

    # Relationships
    parent_user: Mapped["ParentUser"] = relationship(
        "ParentUser", back_populates="children"
    )
    grades: Mapped[List["Grade"]] = relationship(
        "Grade", back_populates="child", cascade="all, delete-orphan"
    )
    rewards: Mapped[List["Reward"]] = relationship(
        "Reward", back_populates="child", cascade="all, delete-orphan"
    )
    payouts: Mapped[List["Payout"]] = relationship(
        "Payout", back_populates="child", cascade="all, delete-orphan"
    )
    timetable_entries: Mapped[List["TimetableEntry"]] = relationship(
        "TimetableEntry", back_populates="child", cascade="all, delete-orphan"
    )


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("children.id"), nullable=False, index=True
    )

    # Identifikace známky
    bakalari_grade_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Data známky
    subject: Mapped[str] = mapped_column(String, nullable=False, index=True)
    grade: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # Vypočtená®® odměna
    reward_amount: Mapped[float] = mapped_column(Float, default=0.0)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    child: Mapped["Child"] = relationship("Child", back_populates="grades")


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("children.id"), nullable=False, index=True
    )

    # Data odměny
    grade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grades.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    paid: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    child: Mapped["Child"] = relationship("Child", back_populates="rewards")


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("children.id"), nullable=False, index=True
    )

    # Data výplaty
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    lnbits_payment_hash: Mapped[str] = mapped_column(String, nullable=True)
    lnbits_payment_request: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    child: Mapped["Child"] = relationship("Child", back_populates="payouts")


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("children.id"), nullable=False, index=True
    )

    # Stav synchronizace
    last_sync_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    next_sync_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    sync_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_sync_error: Mapped[str] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationship
    child: Mapped["Child"] = relationship("Child", back_populates="sync_state")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("parent_users.id"), nullable=False, index=True
    )

    token: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationship
    user: Mapped["ParentUser"] = relationship("ParentUser", back_populates="auth_sessions")


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("children.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Identifikace hodiny
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 1=pondělí®® .. 7=neděle
    lesson_number: Mapped[int] = mapped_column(Integer, nullable=False)  # pořadí®® hodiny v dni
    subject: Mapped[str] = mapped_column(String, nullable=False)  # název předmětu
    room: Mapped[str] = mapped_column(String, nullable=True)  # učebna
    teacher: Mapped[str] = mapped_column(String, nullable=True)  # učitel
    note: Mapped[str] = mapped_column(String, nullable=True)  # pozná®®mka

    # Časová®® platnost
    valid_from: Mapped[date] = mapped_column(Date, nullable=True)  # od kdy platí®®
    valid_to: Mapped[date] = mapped_column(Date, nullable=True)  # do kdy platí®®

    # Relationship
    child: Mapped["Child"] = relationship("Child", back_populates="timetable_entries")

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class AppSetting(Base):
    __tablename__ = 'app_settings'

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=True)


class SyncState(Base):
    __tablename__ = 'sync_states'

    id = Column(Integer, primary_key=True)
    sync_status = Column(String, nullable=False, default='never')
    last_sync_at = Column(DateTime, nullable=True)
    next_sync_at = Column(DateTime, nullable=True)
    sync_started_at = Column(DateTime, nullable=True)
    sync_from_date = Column(Date, nullable=True)
    last_sync_error = Column(String, nullable=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    running_balance_czk = Column(Integer, default=0, nullable=False)


class SyncRun(Base):
    __tablename__ = 'sync_runs'

    id = Column(Integer, primary_key=True)
    mode = Column(String, nullable=False)
    from_date = Column(Date, nullable=False)
    status = Column(String, nullable=False)
    grades_found = Column(Integer, default=0, nullable=False)
    grades_new = Column(Integer, default=0, nullable=False)
    error_message = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Grade(Base):
    __tablename__ = 'grades'

    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, nullable=False)
    subject = Column(String, nullable=False)
    grade_value = Column(String, nullable=False)
    grade_date = Column(Date, nullable=False)
    description = Column(String, nullable=True)
    school_year = Column(String, nullable=True)
    source = Column(String, default='bakalari', nullable=False)
    active_in_sync = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    rewards = relationship(
        'Reward',
        back_populates='grade',
        cascade='all, delete-orphan',
    )


class RewardRule(Base):
    __tablename__ = 'reward_rules'

    id = Column(Integer, primary_key=True)
    grade_value = Column(String, unique=True, nullable=False)
    reward_czk = Column(Integer, nullable=False)
    active = Column(Boolean, default=True, nullable=False)


class Reward(Base):
    __tablename__ = 'rewards'

    id = Column(Integer, primary_key=True)
    grade_id = Column(
        Integer,
        ForeignKey('grades.id', ondelete='CASCADE'),
        nullable=False,
    )
    amount_czk = Column(Integer, nullable=False)
    status = Column(String, default='pending', nullable=False)
    calculation_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    grade = relationship('Grade', back_populates='rewards')


class Payout(Base):
    __tablename__ = 'payouts'

    id = Column(Integer, primary_key=True)
    ln_address = Column(String, nullable=False)
    amount_czk = Column(Integer, nullable=False)
    amount_sats = Column(Integer, nullable=False)
    status = Column(String, default='pending', nullable=False)
    idempotency_key = Column(String, unique=True, nullable=False)
    invoice = Column(String, nullable=True)
    payment_hash = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    audit_events = relationship(
        'PayoutAudit',
        back_populates='payout',
        cascade='all, delete-orphan',
    )


class PayoutAudit(Base):
    __tablename__ = 'payout_audits'

    id = Column(Integer, primary_key=True)
    payout_id = Column(
        Integer,
        ForeignKey('payouts.id', ondelete='CASCADE'),
        nullable=False,
    )
    event = Column(String, nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    payout = relationship('Payout', back_populates='audit_events')


class TimetableEntry(Base):
    __tablename__ = 'timetable_entries'

    id = Column(Integer, primary_key=True)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 4=Friday
    hour = Column(Integer, nullable=False)  # 1-10
    subject = Column(String, nullable=False)
    room = Column(String, nullable=True)
    teacher = Column(String, nullable=True)
    group = Column(String, nullable=True)
    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)
    source = Column(String, default='bakalari', nullable=False)
    external_id = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

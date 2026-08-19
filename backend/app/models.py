from datetime import datetime, date
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class AppSetting(Base):
    __tablename__ = 'settings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AuthUser(Base):
    __tablename__ = 'auth_users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Session(Base):
    __tablename__ = 'sessions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

class Grade(Base):
    __tablename__ = 'grades'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(120), index=True)
    grade_value: Mapped[str] = mapped_column(String(20))
    grade_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default='manual')
    active_in_sync: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RewardRule(Base):
    __tablename__ = 'reward_rules'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grade_value: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    reward_czk: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Reward(Base):
    __tablename__ = 'rewards'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey('grades.id'), unique=True)
    amount_czk: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default='pending', index=True)
    calculation_type: Mapped[str] = mapped_column(String(30), default='normal')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SyncRun(Base):
    __tablename__ = 'sync_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(30))
    from_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    grades_found: Mapped[int] = mapped_column(Integer, default=0)
    grades_new: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default='running')
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class SyncState(Base):
    __tablename__ = 'sync_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_from_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(30), default='never')
    running_balance_czk: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SchedulerState(Base):
    __tablename__ = 'scheduler_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(30), default='off', index=True)
    frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_check_status: Mapped[str] = mapped_column(String(40), default='never')
    current_balance_czk: Mapped[int] = mapped_column(Integer, default=0)
    last_payout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_payout_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_payout_amount_czk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_payout_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ExchangeRate(Base):
    __tablename__ = 'exchange_rates'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(30), default='coingecko')
    czk_per_btc: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Payout(Base):
    __tablename__ = 'payouts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ln_address: Mapped[str] = mapped_column(String(255))
    amount_czk: Mapped[int] = mapped_column(Integer)
    amount_sats: Mapped[int] = mapped_column(Integer)
    exchange_rate_id: Mapped[int | None] = mapped_column(ForeignKey('exchange_rates.id'), nullable=True)
    invoice: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), default='pending', index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class PayoutAudit(Base):
    __tablename__ = 'payout_audit'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payout_id: Mapped[int] = mapped_column(ForeignKey('payouts.id'), index=True)
    event: Mapped[str] = mapped_column(String(40), index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

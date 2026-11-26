"""SQLite schema via SQLAlchemy. One file holds all relational demo data."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.settings import SETTINGS


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40))
    loyalty_key: Mapped[str] = mapped_column(String(80))  # linked-bank token (canary for customer 2)
    # KavachPay account
    upi_id: Mapped[str] = mapped_column(String(80), default="")
    bank_name: Mapped[str] = mapped_column(String(60), default="")
    bank_masked: Mapped[str] = mapped_column(String(20), default="")
    wallet_balance_inr: Mapped[float] = mapped_column(Float, default=0.0)
    kyc_level: Mapped[str] = mapped_column(String(20), default="full")  # minimum|full|expired
    upi_status: Mapped[str] = mapped_column(String(20), default="active")  # active|blocked


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    price_usd: Mapped[float] = mapped_column(Float)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    status: Mapped[str] = mapped_column(String(20))  # processing|shipped|delivered|refunded
    amount_usd: Mapped[float] = mapped_column(Float)
    ordered_at: Mapped[datetime] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    address: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # e.g. PN7K2Q9XA1
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    direction: Mapped[str] = mapped_column(String(8))  # debit|credit
    kind: Mapped[str] = mapped_column(String(20))  # p2p|merchant|recharge|bill|wallet
    counterparty: Mapped[str] = mapped_column(String(120))
    amount_inr: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))  # success|failed|pending|reversed
    debited: Mapped[int] = mapped_column(Integer, default=1)  # money left the bank?
    utr: Mapped[str] = mapped_column(String(20), default="")
    failure_reason: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    notes: Mapped[str] = mapped_column(Text, default="")
    dispute_ticket: Mapped[str] = mapped_column(String(20), default="")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(40))  # customer id or "public"
    filename: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))  # processing|ready|partial|quarantined
    visibility: Mapped[str] = mapped_column(String(20), default="private")
    parsed_by: Mapped[str] = mapped_column(String(20), default="")
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    chunks_indexed: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Section(Base):
    __tablename__ = "sections"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(32))
    heading_path: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer, default=0)


class Quarantine(Base):
    __tablename__ = "quarantine"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(32))
    chunk_id: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    layer: Mapped[str] = mapped_column(String(20))
    owasp: Mapped[str] = mapped_column(String(10), default="NONE")
    reason: Mapped[str] = mapped_column(String(400), default="")
    hidden_text: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(12))
    verdict: Mapped[str] = mapped_column(String(8))
    layer: Mapped[str] = mapped_column(String(12))
    owasp: Mapped[str] = mapped_column(String(10))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String(400), default="")
    judge_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    judge_model: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    preview: Mapped[str] = mapped_column(String(240), default="")


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[float] = mapped_column(Float)
    session_id: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[str] = mapped_column(String(20))
    tool: Mapped[str] = mapped_column(String(60))
    args_json: Mapped[str] = mapped_column(Text, default="{}")
    allowed: Mapped[int] = mapped_column(Integer, default=1)
    result: Mapped[str] = mapped_column(String(400), default="")


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


_engine = None
_Session = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(f"sqlite:///{SETTINGS.db_path}", future=True)
    return _engine


def Session():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=engine(), expire_on_commit=False, future=True)
    return _Session()


def init_db() -> None:
    Base.metadata.create_all(engine())

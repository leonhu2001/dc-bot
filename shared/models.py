from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db import Base


class OrderStatus(str, Enum):
    ACTIVE = "active"
    STORED = "stored"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class PayoutStatus(str, Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    VOID = "void"


class SyncEventStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class SyncEventType(str, Enum):
    ORDER_CREATED = "order_created"
    ORDER_CLAIMED = "order_claimed"
    ORDER_UNCLAIMED = "order_unclaimed"
    ORDER_UPDATED = "order_updated"
    ORDER_CLOSED = "order_closed"
    ORDER_CANCELLED = "order_cancelled"


class WebUser(Base):
    __tablename__ = "web_users"

    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    global_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roles_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_worker: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WebOrder(Base):
    __tablename__ = "web_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    bot_order_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticket_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dispatch_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dispatch_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    customer_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    category: Mapped[str] = mapped_column(String(80))
    item: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[str | None] = mapped_column(String(40), nullable=True)

    status: Mapped[str] = mapped_column(String(30), default=OrderStatus.ACTIVE.value)

    customer_service_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_service_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    assignments: Mapped[list["OrderAssignment"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )

    payouts: Mapped[list["WorkerPayout"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderAssignment(Base):
    __tablename__ = "order_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    order_id: Mapped[int] = mapped_column(ForeignKey("web_orders.id"), index=True)
    worker_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    worker_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    role_type: Mapped[str] = mapped_column(String(40), default="booster")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    has_named_bonus: Mapped[bool] = mapped_column(Boolean, default=False)

    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    order: Mapped["WebOrder"] = relationship(back_populates="assignments")


class WorkerPayout(Base):
    __tablename__ = "worker_payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    order_id: Mapped[int] = mapped_column(ForeignKey("web_orders.id"), index=True)
    worker_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    worker_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    gross_share: Mapped[int] = mapped_column(Integer, default=0)

    base_rate: Mapped[float] = mapped_column(Float, default=0.80)
    base_payout: Mapped[int] = mapped_column(Integer, default=0)

    named_bonus_rate: Mapped[float] = mapped_column(Float, default=0.05)
    named_bonus_amount: Mapped[int] = mapped_column(Integer, default=0)
    has_named_bonus: Mapped[bool] = mapped_column(Boolean, default=False)

    final_payout: Mapped[int] = mapped_column(Integer, default=0)

    payout_status: Mapped[str] = mapped_column(String(30), default=PayoutStatus.UNPAID.value)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    order: Mapped["WebOrder"] = relationship(back_populates="payouts")


class WorkerPayoutOverride(Base):
    __tablename__ = "worker_payout_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    order_id: Mapped[int] = mapped_column(Integer, index=True)
    worker_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    worker_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    manual_final_payout: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_discord_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class CustomerServicePayout(Base):
    __tablename__ = "customer_service_payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    order_id: Mapped[int] = mapped_column(ForeignKey("web_orders.id"), index=True)
    customer_service_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    customer_service_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    rate: Mapped[float] = mapped_column(Float, default=0.05)
    payout_amount: Mapped[int] = mapped_column(Integer, default=0)

    payout_status: Mapped[str] = mapped_column(String(30), default=PayoutStatus.UNPAID.value)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class PayoutRule(Base):
    __tablename__ = "payout_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(120))
    worker_base_rate: Mapped[float] = mapped_column(Float, default=0.80)
    customer_service_rate: Mapped[float] = mapped_column(Float, default=0.05)
    named_bonus_rate: Mapped[float] = mapped_column(Float, default=0.05)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SyncEvent(Base):
    __tablename__ = "sync_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    event_type: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(30), default=SyncEventStatus.PENDING.value)

    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    admin_discord_id: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

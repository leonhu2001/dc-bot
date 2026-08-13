import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


class WebStaffMember(Base):
    __tablename__ = "web_staff_members"

    discord_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    global_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roles_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_customer_service: Mapped[bool] = mapped_column(Boolean, default=False)
    is_worker: Mapped[bool] = mapped_column(Boolean, default=False)
    is_companion: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

# === receiver role display helpers start ===
RECEIVER_ROLE_LABELS = {
    "1500234130871550004": "魔丸♛頂護",
    "1500234170943934544": "魔丸♝女護",
    "1500751039060643990": "魔丸♜男護",
    "1500751059239440575": "魔丸♞男陪",
    "1482080315798192210": "魔丸♟女陪",
}

RECEIVER_ROLE_ORDER = [
    "1500234130871550004",
    "1500234170943934544",
    "1500751039060643990",
    "1500751059239440575",
    "1482080315798192210",
]


def _web_staff_receiver_role_labels(self):
    try:
        role_ids = {str(role_id) for role_id in json.loads(self.roles_json or "[]")}
    except Exception:
        role_ids = set()

    return [
        RECEIVER_ROLE_LABELS[role_id]
        for role_id in RECEIVER_ROLE_ORDER
        if role_id in role_ids
    ]


WebStaffMember.receiver_role_labels = property(_web_staff_receiver_role_labels)
# === receiver role display helpers end ===

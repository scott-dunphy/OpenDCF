import json
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class DecimalList(TypeDecorator):
    """A list of Decimals stored as a JSON array of strings (exact round trip)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:
            return None
        return json.dumps([str(v) for v in value])

    def process_result_value(self, value, dialect):
        if not value:
            return []
        return [Decimal(v) for v in json.loads(value)]


class RentStepList(TypeDecorator):
    """A list of (lease month, rent increase) pairs stored as JSON (exact round trip)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not value:
            return None
        return json.dumps([[int(m), str(p)] for m, p in value])

    def process_result_value(self, value, dialect):
        if not value:
            return []
        return [(int(m), Decimal(p)) for m, p in json.loads(value)]


def json_safe_loans(value) -> list[dict]:
    """Additional loans as plain JSON: models to dicts, Decimal amounts and rates to strings."""
    loans = [v if isinstance(v, dict) else v.model_dump() for v in value or ()]
    return [{k: (str(x) if isinstance(x, Decimal) else x) for k, x in loan.items()} for loan in loans]


class LoanList(TypeDecorator):
    """Additional loans stored as a JSON list of objects; amounts and rates as strings, also when read back
    (snapshots, audit entries and package exports then serialize them as stored)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return json.dumps(json_safe_loans(value)) if value else None

    def process_result_value(self, value, dialect):
        return json.loads(value) if value else []


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UUIDPrimaryKey:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

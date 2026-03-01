from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class RecoveryStructure(Base, UUIDPrimaryKey, TimestampMixin):
    """Reusable recovery template assigned to leases."""
    __tablename__ = "recovery_structures"

    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    default_recovery_type: Mapped[str] = mapped_column(String(30), default="nnn")

    property: Mapped["Property"] = relationship(back_populates="recovery_structures")  # type: ignore[name-defined]
    items: Mapped[list["RecoveryStructureItem"]] = relationship(
        back_populates="recovery_structure", cascade="all, delete-orphan"
    )


class RecoveryStructureItem(Base, UUIDPrimaryKey):
    """Per-category recovery rule within a template."""
    __tablename__ = "recovery_structure_items"

    recovery_structure_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recovery_structures.id")
    )
    expense_category: Mapped[str] = mapped_column(String(50))
    recovery_type: Mapped[str] = mapped_column(String(30))
    base_year_stop_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    cap_per_sf_annual: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    floor_per_sf_annual: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    admin_fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    comment: Mapped[str | None] = mapped_column(Text)

    recovery_structure: Mapped["RecoveryStructure"] = relationship(back_populates="items")

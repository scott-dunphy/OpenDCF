from datetime import date

from sqlalchemy import Column, Date, ForeignKey, Integer, Numeric, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey

portfolio_properties = Table(
    "portfolio_properties",
    Base.metadata,
    Column(
        "portfolio_id",
        String(36),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "property_id", String(36), ForeignKey("properties.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("ownership_pct", Numeric(8, 6), nullable=False, server_default="1"),
    Column("effective_from", Date, nullable=True),
    Column("effective_to", Date, nullable=True),
    Column("acquisition_cost", Numeric(18, 2), nullable=True),
    Column("commitment", Numeric(18, 2), nullable=True),
    Column("currency", String(3), nullable=False, server_default="USD"),
)


class Portfolio(Base, UUIDPrimaryKey, TimestampMixin):
    """A named group of properties valued and reported together."""

    __tablename__ = "portfolios"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    properties: Mapped[list["Property"]] = relationship(  # type: ignore[name-defined]
        secondary=portfolio_properties
    )
    scenarios: Mapped[list["PortfolioScenario"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    runs: Mapped[list["PortfolioRun"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class AssumptionProfile(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Assumptions scoped by portfolio (or house-wide when portfolio_id is null),
    property type and market. Null scope fields match everything; the most
    specific matching profile wins field by field.
    """

    __tablename__ = "assumption_profiles"

    name: Mapped[str] = mapped_column(String(255))
    portfolio_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True
    )
    property_type: Mapped[str | None] = mapped_column(String(50))
    market: Mapped[str | None] = mapped_column(String(100))
    values_json: Mapped[str] = mapped_column(Text, default="{}")
    comment: Mapped[str | None] = mapped_column(Text)
    # Library scope and provenance (docs/market-assumptions-plan.md)
    cbsa_code: Mapped[str | None] = mapped_column(String(5))
    state: Mapped[str | None] = mapped_column(String(2))
    quality_score: Mapped[int | None] = mapped_column(Integer)
    as_of: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(Text)
    # field -> {"low", "high"}; the base is the field's value in values_json
    ranges_json: Mapped[str] = mapped_column(Text, default="{}")


class AssumptionSettings(Base, TimestampMixin):
    """House-wide library settings (one row, id 1)."""

    __tablename__ = "assumption_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # field -> "higher" | "lower" | "none": the end of its range a quality-5 property takes
    directions_json: Mapped[str] = mapped_column(Text, default="{}")


class PortfolioScenario(Base, UUIDPrimaryKey, TimestampMixin):
    """A named set of assumption overrides applied across a whole portfolio."""

    __tablename__ = "portfolio_scenarios"

    portfolio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("portfolios.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    probability_pct: Mapped[float | None] = mapped_column()
    # JSON list of {property_type, market, mode ("set" | "shift"), values}
    overrides_json: Mapped[str] = mapped_column(Text, default="[]")

    portfolio: Mapped["Portfolio"] = relationship(back_populates="scenarios")


class PortfolioRun(Base, UUIDPrimaryKey, TimestampMixin):
    """Results of running a portfolio under the base case and selected scenarios."""

    __tablename__ = "portfolio_runs"

    portfolio_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("portfolios.id", ondelete="CASCADE")
    )
    name: Mapped[str | None] = mapped_column(String(255))
    # Set: each property valued from its latest valuation approved with a date of value on or
    # before this date. None: latest valuations on the live model.
    as_of: Mapped[date | None] = mapped_column(Date)
    results_json: Mapped[str] = mapped_column(Text, default="{}")

    portfolio: Mapped["Portfolio"] = relationship(back_populates="runs")


class ImportJob(Base, UUIDPrimaryKey, TimestampMixin):
    """A parsed bulk-import workbook awaiting (or after) commit."""

    __tablename__ = "import_jobs"

    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), default="previewed"
    )  # previewed | committed | failed
    report_json: Mapped[str] = mapped_column(
        Text, default="{}"
    )  # sheets, previews, warnings, errors
    payload_json: Mapped[str] = mapped_column(Text, default="{}")  # ImportPayload
    created_property_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    portfolio_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

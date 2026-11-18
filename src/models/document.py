from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPrimaryKey


class SourceDocument(Base, UUIDPrimaryKey, TimestampMixin):
    """Content-addressed source evidence. A hash is stored only once across valuations."""

    __tablename__ = "source_documents"

    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(128))
    byte_size: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    document_type: Mapped[str | None] = mapped_column(String(64))
    relevant: Mapped[bool | None] = mapped_column()
    confidence: Mapped[float | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text)
    family_key: Mapped[str | None] = mapped_column(String(255), index=True)
    amendment_number: Mapped[int | None] = mapped_column(Integer)
    document_date: Mapped[date | None] = mapped_column(Date)
    as_of_date: Mapped[date | None] = mapped_column(Date)
    extraction_model: Mapped[str | None] = mapped_column(String(128))
    extraction_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class ValuationDocument(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "valuation_documents"
    __table_args__ = (UniqueConstraint("valuation_id", "document_id"),)

    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    # This valuation's choice to use or skip the file; None follows the file's classification
    relevant_override: Mapped[bool | None] = mapped_column()


class ExtractedFact(Base, UUIDPrimaryKey, TimestampMixin):
    """A proposed or accepted model value with document/page provenance."""

    __tablename__ = "extracted_facts"

    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    field_path: Mapped[str] = mapped_column(String(255), index=True)
    value_json: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column()
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="proposed")
    # Ties repeated facts (e.g. the leases[] fields of one tenant) into one row.
    record_key: Mapped[str | None] = mapped_column(String(255))


class AiModelAction(Base, UUIDPrimaryKey, TimestampMixin):
    """A copilot message and its proposed/applied model changes."""

    __tablename__ = "ai_model_actions"

    valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    user_message: Mapped[str] = mapped_column(Text)
    assistant_message: Mapped[str] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(String(24))
    proposal_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="answered")
    model_name: Mapped[str] = mapped_column(String(128))


class AppraisalReconstruction(Base, UUIDPrimaryKey, TimestampMixin):
    """Editable staged model reconstructed from an appraisal."""

    __tablename__ = "appraisal_reconstructions"

    source_valuation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="CASCADE"), index=True
    )
    source_document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="staged")
    plan_json: Mapped[str] = mapped_column(Text)
    unresolved_json: Mapped[str] = mapped_column(Text, default="[]")
    rebuilt_property_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("properties.id", ondelete="SET NULL")
    )
    rebuilt_valuation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("valuations.id", ondelete="SET NULL")
    )

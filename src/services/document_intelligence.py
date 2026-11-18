import base64
import hashlib
import io
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from src.config import settings

DOCUMENT_TYPES = [
    "lease",
    "lease_amendment",
    "rent_roll",
    "operating_statement",
    "budget",
    "appraisal",
    "property_tax",
    "insurance",
    "title",
    "environmental",
    "survey",
    "capital_plan",
    "offering_memorandum",
    "sale_comparable",
    "other",
]

EXTRACTION_TOOL = {
    "name": "record_valuation_document",
    "description": "Classify a CRE valuation document and record only facts supported by it.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["document_type", "relevant", "confidence", "reason", "facts"],
        "properties": {
            "document_type": {"type": "string", "enum": DOCUMENT_TYPES},
            "relevant": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
            "family_key": {
                "type": ["string", "null"],
                "description": "Stable tenant/lease or statement-series identifier",
            },
            "amendment_number": {"type": ["integer", "null"], "minimum": 1},
            "document_date": {"type": ["string", "null"], "format": "date"},
            "as_of_date": {"type": ["string", "null"], "format": "date"},
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field_path", "value", "confidence"],
                    "properties": {
                        "field_path": {
                            "type": "string",
                            "description": "OpenDCF semantic path, e.g. leases[].lease_end_date",
                        },
                        "value": {},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "page_number": {"type": ["integer", "null"]},
                        "source_quote": {"type": ["string", "null"], "maxLength": 500},
                        "record_key": {
                            "type": ["string", "null"],
                            "description": "For repeated facts such as leases[] fields: the same "
                            "key (e.g. tenant name and suite) on every fact of one row",
                        },
                    },
                },
            },
        },
    },
}


def store_content(content: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    root = Path(settings.document_store_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / digest[:2] / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(content)
    return digest, str(target.relative_to(root))


def read_content(storage_key: str) -> bytes:
    root = Path(settings.document_store_path).resolve()
    target = (root / storage_key).resolve()
    if root not in target.parents:
        raise ValueError("Invalid document storage key")
    return target.read_bytes()


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _pdf_chunks(content: bytes, target_bytes: int = 20 * 1024 * 1024) -> list[tuple[bytes, int]]:
    """Return API-safe PDF chunks paired with their zero-based source page offset."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(content))
    page_count = len(reader.pages)
    if not page_count:
        raise ValueError("PDF has no pages")
    pages_per_chunk = max(1, int(page_count * target_bytes / max(len(content), 1)))
    output: list[tuple[bytes, int]] = []
    start = 0
    while start < page_count:
        end = min(page_count, start + pages_per_chunk)
        while True:
            writer = PdfWriter()
            for page in reader.pages[start:end]:
                writer.add_page(page)
            stream = io.BytesIO()
            writer.write(stream)
            chunk = stream.getvalue()
            if len(chunk) <= 22 * 1024 * 1024 or end - start == 1:
                break
            end = start + max(1, (end - start) // 2)
        if len(chunk) > 22 * 1024 * 1024:
            raise ValueError(f"PDF page {start + 1} alone exceeds Anthropic's 32 MB limit")
        output.append((chunk, start))
        start = end
    return output


def call_tool(client: Any, tool: dict, content: Any, max_tokens: int = 64000) -> dict[str, Any]:
    """Ask the extraction model to call `tool` once and return its input. Streams, since a long
    rent roll can need tens of thousands of output tokens; raises instead of returning a partial
    result when the output was cut off or declined."""
    with client.messages.stream(
        model=settings.anthropic_extraction_model,
        max_tokens=max_tokens,
        output_config={"effort": "high"},
        tools=[tool],
        tool_choice={"type": "auto"},  # Opus 5.5 does not accept a forced tool choice
        messages=[{"role": "user", "content": content}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "max_tokens":
        raise RuntimeError("The document had more to record than fits in one reading; split it and try again")
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined to read this document")
    for item in response.content:
        if getattr(item, "type", None) == "tool_use" and item.name == tool["name"]:
            return dict(item.input)
    raise RuntimeError("Anthropic returned no structured extraction")


def _extract_block(client: Any, block: dict, filename: str, page_offset: int = 0) -> dict[str, Any]:
    prompt = (
        f"Analyze {filename!r} for a commercial real estate valuation. Classify relevance; "
        "identify lease/amendment family and amendment number; extract dates, parties, premises, "
        "area, rent, steps, options, reimbursements, financial periods, income, expenses, and other "
        "valuation facts. Never infer a fact not supported by the document. Include page evidence. "
        "For tables such as rent rolls, give every fact of one tenant or lease row the same "
        "record_key (tenant name and suite). "
        "For leases and amendments, record facts under leases[]. paths with record_key set to the "
        "tenant name and suite, and also extract: the escalation (fixed steps, percent per year, or "
        "CPI with floor and cap); the tenant's pro-rata share; how each expense is recovered (real "
        "estate taxes, insurance, CAM, utilities, management and any other) and any exclusions; the "
        "base year or expense stop; caps on recoveries (amount per SF, annual growth, whether "
        "cumulative or compounding, whether limited to controllable expenses); administrative or "
        "management fees charged on recoveries; gross-up; renewal options (term and rent); tenant "
        "improvement allowances and leasing commissions still owed; and free rent. In an amendment, "
        "record only the terms it changes and its effective date. "
        + ("Report page numbers relative to the supplied PDF chunk. " if page_offset else "")
        + "Call record_valuation_document exactly once."
    )
    result = call_tool(client, EXTRACTION_TOOL, [block, {"type": "text", "text": prompt}])
    result["document_date"] = _date(result.get("document_date"))
    result["as_of_date"] = _date(result.get("as_of_date"))
    if page_offset:
        for fact in result.get("facts", []):
            if fact.get("page_number") is not None:
                fact["page_number"] += page_offset
    return result


SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")


def spreadsheet_text(content: bytes) -> str:
    """Render every sheet of an Excel workbook as CSV text for extraction."""
    import csv
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    parts = []
    for sheet in workbook.worksheets:
        out = io.StringIO()
        writer = csv.writer(out)
        for row in sheet.iter_rows(values_only=True):
            if any(cell is not None for cell in row):
                writer.writerow(["" if cell is None else cell for cell in row])
        parts.append(f"## Sheet: {sheet.title}\n{out.getvalue()}")
    workbook.close()
    return "\n".join(parts)


def extract_with_anthropic(content: bytes, media_type: str, filename: str) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("Install the anthropic package to process documents") from exc

    client = Anthropic(api_key=settings.anthropic_api_key)
    # Anthropic measures the base64 payload against its 32 MB document limit;
    # base64 adds roughly one third, so split raw PDFs above 22 MiB.
    if media_type == "application/pdf" and len(content) > 22 * 1024 * 1024:
        results = []
        for chunk, page_offset in _pdf_chunks(content):
            block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(chunk).decode(),
                },
            }
            results.append(_extract_block(client, block, filename, page_offset))
        primary = max(results, key=lambda item: float(item.get("confidence", 0)))
        merged = dict(primary)
        merged["relevant"] = any(item.get("relevant", False) for item in results)
        merged["confidence"] = sum(float(item.get("confidence", 0)) for item in results) / len(results)
        merged["reason"] = " ".join(dict.fromkeys(str(item.get("reason", "")) for item in results))
        merged["facts"] = [fact for item in results for fact in item.get("facts", [])]
        for key in ("family_key", "amendment_number", "document_date", "as_of_date"):
            merged[key] = next((item.get(key) for item in results if item.get(key) is not None), None)
        return merged
    if media_type == "application/pdf":
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(content).decode(),
            },
        }
    elif media_type.startswith("image/"):
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(content).decode(),
            },
        }
    elif media_type.startswith("text/") or filename.lower().endswith((".txt", ".csv")):
        block = {"type": "text", "text": content.decode("utf-8", errors="replace")}
    elif filename.lower().endswith(SPREADSHEET_SUFFIXES):
        block = {"type": "text", "text": spreadsheet_text(content)}
    else:
        raise ValueError("AI extraction supports PDF, Excel (.xlsx), CSV, text, and images")

    return _extract_block(client, block, filename)


def completeness_issues(
    documents: list[Any], relevance: dict[str, bool | None] | None = None
) -> list[dict[str, Any]]:
    """relevance: this valuation's per-document use/skip choices, by document id."""
    relevance = relevance or {}
    issues: list[dict[str, Any]] = []
    families: dict[str, list[Any]] = {}
    for doc in documents:
        if doc.family_key and doc.document_type in {"lease", "lease_amendment"}:
            families.setdefault(doc.family_key, []).append(doc)
    for family, docs in families.items():
        has_base = any(d.document_type == "lease" for d in docs)
        if not has_base:
            issues.append(
                {
                    "severity": "critical",
                    "code": "missing_base_lease",
                    "family_key": family,
                    "message": f"Lease family {family} has amendments but no base lease.",
                }
            )
        numbers = sorted({d.amendment_number for d in docs if d.amendment_number})
        if numbers:
            missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
            for number in missing:
                issues.append(
                    {
                        "severity": "critical",
                        "code": "missing_lease_amendment",
                        "family_key": family,
                        "missing_number": number,
                        "message": f"Lease family {family} is missing amendment {number}.",
                    }
                )
    present = {
        d.document_type for d in documents
        if d.document_type and relevance.get(d.id, d.relevant) is not False
    }
    if not present:
        return issues
    # Each check names what the model loses without that kind of source.
    for sources, severity, code, message in (
        (
            {"rent_roll", "lease", "lease_amendment", "appraisal", "offering_memorandum"},
            "warning",
            "missing_tenant_source",
            "No rent roll or leases: the model will have no tenants.",
        ),
        (
            {"operating_statement", "budget", "appraisal", "offering_memorandum"},
            "warning",
            "missing_expense_source",
            "No operating statement or budget: the model will have no operating expenses.",
        ),
        (
            {"appraisal", "offering_memorandum"},
            "info",
            "missing_assumption_source",
            "No appraisal or offering memorandum: set the discount rate, exit cap rate and "
            "market leasing yourself before creating the valuation.",
        ),
    ):
        if not sources & present:
            issues.append({"severity": severity, "code": code, "message": message})
    return issues


def staleness_issues(
    documents: list[Any], effective_date: date, leases: list[Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for lease in leases:
        if lease.lease_end_date < effective_date:
            issues.append(
                {
                    "severity": "critical",
                    "code": "expired_lease_in_model",
                    "entity_id": lease.id,
                    "message": (
                        f"Modeled lease expired {lease.lease_end_date} before valuation "
                        f"date {effective_date}."
                    ),
                }
            )
    limits = {"rent_roll": 90, "operating_statement": 455, "property_tax": 455, "insurance": 455}
    for doc in documents:
        as_of = doc.as_of_date or doc.document_date
        if as_of and doc.document_type in limits:
            age = (effective_date - as_of).days
            if age > limits[doc.document_type]:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "stale_document",
                        "document_id": doc.id,
                        "age_days": age,
                        "message": f"{doc.document_type} is {age} days old at the valuation date.",
                    }
                )
    return issues


def portable_manifest(
    property_data: dict,
    valuation_data: dict,
    documents: list[dict],
    facts: list[dict],
    issues: list[dict],
) -> dict:
    return {
        "$schema": "https://opendcf.org/schemas/valuation-package/1.1.json",
        "format": "OpenDCF Valuation Package",
        # 1.1: documents carry this valuation's relevant_override; the valuation leaves out the
        # per-tenant result blobs
        "schema_version": "1.1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "property": property_data,
        "valuation": valuation_data,
        "evidence": {"documents": documents, "facts": facts},
        "validation_issues": issues,
    }

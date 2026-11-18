# OpenDCF valuation evidence, reconstruction, and copilot

OpenDCF uses one browser UI and one FastAPI service. The same application can run on localhost on
Windows, macOS, or Linux, or be hosted centrally. Native desktop shells are optional launchers, not a
second UI implementation.

## Evidence workflow

1. Upload arbitrary valuation evidence to a valuation.
2. Store each unique file once by SHA-256 and link it to any number of valuations.
3. Ask Anthropic to classify relevance and extract structured, page-supported proposed facts.
4. Detect incomplete document families, including missing base leases and gaps in numbered amendments.
5. Review proposed facts before they become authoritative model inputs.
6. Flag documents that are old at the valuation effective date and modeled leases already expired.
7. Export a versioned OpenDCF Valuation Package (`.odcf.json`) containing model data, hashes,
   provenance, review status, and validation findings.

Raw source documents are excluded from the JSON package. This makes the model portable without
silently redistributing confidential leases or tenant information.

## Appraisal reconstruction

An appraisal is both evidence and a potential model blueprint. Its extracted facts should be presented
as a staged reconstruction with source value, proposed OpenDCF field, confidence, and page evidence.
The user reviews the staged model, creates a separate valuation, runs it, and compares OpenDCF results
with the appraisal's concluded value, NOI, cap rate, and cash-flow assumptions. Unmapped and missing
inputs remain explicit exceptions; they must not be guessed.

## Copilot safety model

Read questions do not require confirmation. Changes are converted to allowlisted, entity-scoped
before/after proposals. The default `confirm` policy requires Apply or Reject. A valuation-specific
`always_allow` policy may auto-apply supported changes after an explicit warning. Database changes use
the normal OpenDCF audit trail.

## Optional Git repository adapter

GitHub can store `.odcf.json` packages for diffs, pull-request review, tags, rollback, and branches.
It is not the primary database. Raw confidential documents should remain in an access-controlled
document store; package hashes link the model to those files. Private repositories, protected branches,
and encryption or Git LFS may be added by organizations with suitable governance.

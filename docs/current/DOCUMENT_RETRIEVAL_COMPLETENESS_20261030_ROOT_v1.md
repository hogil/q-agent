# Document Retrieval Completeness and Evidence Boundaries

Date: 2026-10-30 (KST)

## Scope and evidence level

This note documents the local response-validation and evidence-review contract in `app/document_evidence_contract.py`, `app/evidence_review.py`, and `app/agent.py`, the incident-document Schema Skill and ReAct reference, plus the two new synthetic tests `tests/test_document_retrieval_completeness.py` and `tests/test_document_retrieval_completeness_e2e.py`. It records code and synthetic-fixture behavior only. No actual company documents, retrieval service, production database, ACL, OCR, vision model, or image store was accessed or validated.

The parent run reports 184 synthetic tests passed and the release freeze check passed. This is a parent-provided execution report, not a test or freeze run performed for this note. It does not establish real-source retrieval correctness or site deployment readiness.

## Completeness metadata semantics

- The adapter contract accepts raw `truncated` and `candidate_count`, normalizes them to `source_reported_truncated` and `source_reported_candidate_count`, and records `candidate_count_basis: source_reported_unverified`.
- `truncated=true` means the source reports truncation. `false` means only that the source reports no truncation. It does not prove that the corpus was exhaustively searched. Missing or null truncation metadata yields `retrieval_completeness: unknown`.
- A `candidate_count` is retained as a source-reported number only. Its actual meaning at a site (including whether it means candidates immediately before return) is unverified. The contract does not treat it as a verified corpus total.
- Conflicting raw and normalized values or unsupported completeness/count-basis claims fail validation. Revalidating normalized output is idempotent, and validation does not mutate the original callback payload. Legacy raw metadata remains supported.
- `evidence_review.py` accepts legacy validated document evidence with no retrieval metadata and records completeness as `unknown`; if any normalized metadata field is present, the full metadata tuple must be present and consistent. The Agent attaches system caveats only for cited document evidence, including for a cited `NO_MATCH` result. A no-match or non-truncated result is not a claim of corpus-wide absence or exhaustive search.

The tests exercise true/false/unknown, zero and invalid counts, top-k and no-match cases, raw/normalized conflicts, idempotent revalidation, and the scoped callback → review → Judge → Answer path for both document source kinds. These are synthetic contract checks, not measurements of a live retrieval engine.

## Scope, citation, and limitations

Document retrieval is gated to a validated incident scope in the current Agent path. The callback receives actor, selected incident IDs, historical incident IDs, cutoff, query, and top-k; direct evidence must intersect the selected incident scope, while historical candidates must intersect caller-registered historical IDs. The result retains source and chunk identifiers, version, locator, availability time, relation, and applicability metadata for review and citation. These checks establish contract correspondence and bounded scope, not semantic truth, source authorization, ACL enforcement, or causal validity.

The Agent's cited-evidence system limitations distinguish source-reported truncation, unknown completeness, source-reported non-truncation, and unverified user access control. The ACL caveat is explicit: Q-Agent does not separately verify user-specific document access. `available_at` is checked against the requested cutoff by the document contract; missing availability is not converted into a known time. Historical candidate evidence is marked as such and is not current-scope evidence.

The incident-document Skill says the configured internal documents and Eng’r Inform Note are intended to use the existing BM25 + vector Hybrid RAG and existing chunks. It explicitly calls actual site source/API/data unverified and the metadata handling a design draft. The tests' callback reads synthetic SQLite fixtures and does not execute BM25 or vector retrieval. No evidence here confirms the deployed Hybrid RAG, chunk provenance, reranker, source-side truncation meaning, ACL, or production schema.

## User-requested image and map direction

The newly requested direction has two distinct parts: extract/search text from images, and separately embed/map image content for image similarity or map-based retrieval, with a design link between the two evidence paths. This document records that request as future design scope only. The present document-chunk contract handles text chunks; it does not implement OCR, image-text extraction, image embeddings, vector-map storage, or cross-modal linking. Existing image comparison Tools and image metadata Skills do not establish those capabilities. Any future design should preserve separate provenance, source identity, version/as-of and scope for extracted text and image/map embeddings, and define an explicit link between them before claiming integrated evidence. That design has not been validated with actual images or an image store.

## Compatibility and release boundary

Raw callback fields remain accepted for backward compatibility; normalized fields are additive output metadata. Evidence review tolerates metadata-free legacy results by assigning unknown completeness, while malformed partial or conflicting normalized metadata is rejected. No callback, Tool schema, Skill, config, lock, or release artifact was changed for this report. The reported freeze check is not a new freeze or authorization to publish updated Router/Judge/Answer behavior. Any behavior or Skill change must first update the relevant Skill/shared reference, then be explicitly reviewed and frozen under the project release process.

"""Synthetic, fail-closed temporal eligibility policy for OCR retrieval lineage.

Caller-supplied provenance is asserted and unverified; this module does not
verify hashes, ACLs, index contents, or actual model availability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Mapping


MODES = {"historical_realized", "retrospective_reprocessing"}
RETRIEVAL_KINDS = {"lexical", "hybrid"}
_OUTPUT_TIMES = {"ocr_output", "embedding_output", "index_snapshot"}


def _aware(value: Any) -> bool:
    try:
        return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    except Exception:
        return False


def _same_ref(reference: Any, artifact: Mapping[str, Any]) -> bool:
    return isinstance(reference, Mapping) and reference.get("id") == artifact.get("id") and reference.get("version") == artifact.get("version")


def evaluate_temporal_lineage(
    *,
    mode: str,
    historical_cutoff_exclusive: datetime,
    analysis_at: datetime,
    retrieval_kind: str,
    artifacts: Mapping[str, Mapping[str, Any]],
    caller_verifier: Callable[[Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Return eligibility without exposing artifact metadata unless eligible.

    Required artifact keys are source_version, ocr_model, ocr_output,
    index_snapshot, and (for hybrid) embedding_model and embedding_output.
    Each record has nonempty id/version and aware available_at; generated
    outputs also have aware generated_at.
    """
    reasons: list[str] = []
    if mode not in MODES:
        reasons.append("unknown_mode")
    if retrieval_kind not in RETRIEVAL_KINDS:
        reasons.append("unknown_retrieval_kind")
    if not _aware(historical_cutoff_exclusive):
        reasons.append("invalid_historical_cutoff_exclusive")
    if not _aware(analysis_at):
        reasons.append("invalid_analysis_at")
    if not isinstance(artifacts, Mapping):
        reasons.append("invalid_artifacts_mapping")
    if reasons:
        return _result(False, reasons, mode, historical_cutoff_exclusive, analysis_at, {})

    required = ["source_version", "ocr_model", "ocr_output", "index_snapshot"]
    if retrieval_kind == "hybrid":
        required += ["embedding_model", "embedding_output"]
    parsed: dict[str, Mapping[str, Any]] = {}
    for name in required:
        item = artifacts.get(name)
        if not isinstance(item, Mapping):
            reasons.append(f"missing_{name}")
            continue
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ("id", "version")):
            reasons.append(f"invalid_{name}_identity")
        if not _aware(item.get("available_at")):
            reasons.append(f"invalid_{name}_available_at")
        if name in _OUTPUT_TIMES and not _aware(item.get("generated_at")):
            reasons.append(f"invalid_{name}_generated_at")
        parsed[name] = item
    if reasons:
        return _result(False, reasons, mode, historical_cutoff_exclusive, analysis_at, {})

    # Type narrowing after fail-closed validation.
    cutoff, at = historical_cutoff_exclusive, analysis_at
    for name, item in parsed.items():
        available = item["available_at"]
        if available > at:
            reasons.append(f"{name}_unavailable_at_analysis")
        if mode == "historical_realized" and not available < cutoff:
            reasons.append(f"{name}_not_available_before_historical_cutoff")
        if name == "source_version" and not available < cutoff:
            reasons.append("source_version_not_available_before_historical_cutoff")
        if name in _OUTPUT_TIMES and item["generated_at"] > available:
            reasons.append(f"{name}_generated_after_available")

    source, model, ocr, index = (parsed[k] for k in ("source_version", "ocr_model", "ocr_output", "index_snapshot"))
    ocr_deps = ocr.get("dependencies")
    if not isinstance(ocr_deps, Mapping):
        reasons.append("invalid_ocr_output_dependencies")
    else:
        if not _same_ref(ocr_deps.get("source_version"), source):
            reasons.append("ocr_output_source_version_mismatch")
        if not _same_ref(ocr_deps.get("ocr_model"), model):
            reasons.append("ocr_output_model_mismatch")
    index_deps = index.get("dependencies")
    if not isinstance(index_deps, Mapping) or not _same_ref(index_deps.get("ocr_output"), ocr):
        reasons.append("index_ocr_output_mismatch")
    if source["available_at"] > ocr["generated_at"]:
        reasons.append("source_version_unavailable_at_ocr_generation")
    if model["available_at"] > ocr["generated_at"]:
        reasons.append("ocr_model_unavailable_at_ocr_generation")
    required_outputs = [ocr]
    if retrieval_kind == "hybrid":
        emb_model, embedding = parsed["embedding_model"], parsed["embedding_output"]
        emb_deps = embedding.get("dependencies")
        if not isinstance(emb_deps, Mapping):
            reasons.append("invalid_embedding_output_dependencies")
        else:
            if not _same_ref(emb_deps.get("ocr_output"), ocr):
                reasons.append("embedding_ocr_output_mismatch")
            if not _same_ref(emb_deps.get("embedding_model"), emb_model):
                reasons.append("embedding_model_mismatch")
        if not isinstance(index_deps, Mapping) or not _same_ref(index_deps.get("embedding_output"), embedding):
            reasons.append("index_embedding_output_mismatch")
        if emb_model["available_at"] > embedding["generated_at"]:
            reasons.append("embedding_model_unavailable_at_embedding_generation")
        if ocr["available_at"] > embedding["generated_at"]:
            reasons.append("ocr_output_unavailable_at_embedding_generation")
        required_outputs.append(embedding)
    if any(item["available_at"] > index["generated_at"] for item in required_outputs):
        reasons.append("required_output_unavailable_at_index_generation")

    verified = False
    if caller_verifier is not None:
        try:
            # This is only the caller's assertion, never independent verification.
            verified = caller_verifier(artifacts) is True
            if not verified:
                reasons.append("caller_verifier_not_exact_true")
        except Exception:
            reasons.append("caller_verifier_error")
    if reasons:
        return _result(False, reasons, mode, cutoff, at, {})

    visible = {
        name: {k: v for k, v in item.items() if k in {"id", "version", "available_at", "generated_at"}}
        for name, item in parsed.items()
    }
    return {
        "evaluation_status": "eligible_unverified",
        "allowed": True,
        "reasons": (
            ["retrospective_mode_not_historical_replay"]
            + (["postcutoff_artifact_present"] if any(x["available_at"] >= cutoff for x in parsed.values()) else [])
            if mode == "retrospective_reprocessing" else []
        ),
        "mode": mode,
        "historical_cutoff_exclusive": cutoff,
        "analysis_at": at,
        "input_provenance": "caller_asserted_unverified",
        "caller_verifier_assertion": verified if caller_verifier is not None else None,
        "artifact_metadata": visible,
        "limitations": ["content_effective_or_observed_times_not_checked", "model_training_data_cutoff_not_verified", "actor_acl_not_checked", "actual_model_availability_not_checked", "hash_acl_and_index_proofs_not_verified"],
    }


def _result(allowed: bool, reasons: list[str], mode: str, cutoff: Any, at: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluation_status": "eligible_unverified" if allowed else "ineligible_unverified",
        "allowed": allowed,
        "reasons": reasons,
        "mode": mode,
        "historical_cutoff_exclusive": cutoff if _aware(cutoff) else None,
        "analysis_at": at if _aware(at) else None,
        "input_provenance": "caller_asserted_unverified",
        "caller_verifier_assertion": None,
        "artifact_metadata": metadata,
        "limitations": ["content_effective_or_observed_times_not_checked", "model_training_data_cutoff_not_verified", "actor_acl_not_checked", "actual_model_availability_not_checked", "hash_acl_and_index_proofs_not_verified"],
    }

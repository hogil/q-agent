"""Post hoc rank and score fusion for the fixed synthetic FBM retrieval probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "var/fbm-research/retrieval-1793319023158761200-181608/retrieval_results.json"
RRF_K = 60


def _validate(data: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    results = data.get("results")
    if not isinstance(results, dict) or set(results) != {"raw_fbm", "object_id_yield"}:
        raise ValueError("expected exactly raw_fbm and object_id_yield representations")
    normalized: dict[str, dict[str, Any]] = {}
    for rep in ("raw_fbm", "object_id_yield"):
        queries = results[rep].get("queries")
        if not isinstance(queries, list) or len(queries) != 8:
            raise ValueError(f"{rep}: expected exactly 8 queries")
        by_query: dict[str, dict[str, Any]] = {}
        for query in queries:
            qid = query.get("query_asset_id")
            if not isinstance(qid, str) or not qid or qid in by_query:
                raise ValueError(f"{rep}: missing or duplicate query ID {qid!r}")
            label = query.get("query_label")
            if not isinstance(label, str) or not label:
                raise ValueError(f"{rep}/{qid}: missing query label")
            ranking = query.get("ranking")
            if not isinstance(ranking, list) or len(ranking) != 8:
                raise ValueError(f"{rep}/{qid}: expected 8 gallery rankings")
            gallery: dict[str, dict[str, Any]] = {}
            ranks: set[int] = set()
            for row in ranking:
                aid, rank, score, glabel = row.get("asset_id"), row.get("rank"), row.get("similarity"), row.get("label")
                if not isinstance(aid, str) or not aid or aid in gallery:
                    raise ValueError(f"{rep}/{qid}: missing or duplicate gallery ID {aid!r}")
                if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1 or rank > 8 or rank in ranks:
                    raise ValueError(f"{rep}/{qid}/{aid}: invalid or duplicate rank {rank!r}")
                if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
                    raise ValueError(f"{rep}/{qid}/{aid}: invalid score {score!r}")
                if not isinstance(glabel, str) or not glabel:
                    raise ValueError(f"{rep}/{qid}/{aid}: missing gallery label")
                gallery[aid] = {"rank": rank, "score": float(score), "label": glabel}
                ranks.add(rank)
            if ranks != set(range(1, 9)):
                raise ValueError(f"{rep}/{qid}: ranks must be exactly 1..8")
            ranked_scores = [row["similarity"] for row in sorted(ranking, key=lambda row: row["rank"])]
            if any(left < right for left, right in zip(ranked_scores, ranked_scores[1:])):
                raise ValueError(f"{rep}/{qid}: rank and similarity ordering disagree")
            by_query[qid] = {"label": label, "gallery": gallery}
        normalized[rep] = by_query

    raw, obj = normalized["raw_fbm"], normalized["object_id_yield"]
    if set(raw) != set(obj):
        raise ValueError("query ID sets differ between representations")
    for qid in raw:
        if raw[qid]["label"] != obj[qid]["label"]:
            raise ValueError(f"{qid}: query label mismatch")
        rg, og = raw[qid]["gallery"], obj[qid]["gallery"]
        if set(rg) != set(og):
            raise ValueError(f"{qid}: gallery ID sets differ between representations")
        for aid in rg:
            if rg[aid]["label"] != og[aid]["label"]:
                raise ValueError(f"{qid}/{aid}: gallery label mismatch")
    for rep in normalized:
        expected_gallery = set(next(iter(normalized[rep].values()))["gallery"])
        for qid in normalized[rep]:
            if set(normalized[rep][qid]["gallery"]) != expected_gallery:
                raise ValueError(f"{rep}/{qid}: gallery ID set differs across queries")
            for other_qid in normalized[rep]:
                for aid, row in normalized[rep][qid]["gallery"].items():
                    if row["label"] != normalized[rep][other_qid]["gallery"][aid]["label"]:
                        raise ValueError(f"{rep}/{aid}: gallery label mismatch across queries")
    labels = {qid: raw[qid]["label"] for qid in raw}
    return normalized, labels


def _order(rows: list[dict[str, Any]], score_key: str) -> list[dict[str, Any]]:
    # Ties are broken by SHA256(asset_id UTF-8), then asset_id; labels never enter ranking.
    return sorted(rows, key=lambda row: (-row[score_key], hashlib.sha256(row["asset_id"].encode("utf-8")).hexdigest(), row["asset_id"]))


def _metrics(queries: list[dict[str, Any]]) -> dict[str, Any]:
    classes = sorted({q["query_label"] for q in queries})
    def calc(group: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(group)
        top1 = sum(q["ranking"][0]["label"] == q["query_label"] for q in group)
        top3 = sum(any(x["label"] == q["query_label"] for x in q["ranking"][:3]) for q in group)
        return {"queries": n, "top1_correct": top1, "top3_correct": top3,
                "top1_accuracy": top1 / n if n else 0.0, "top3_accuracy": top3 / n if n else 0.0}
    return {"by_query_class": {c: calc([q for q in queries if q["query_label"] == c]) for c in classes}, "overall": calc(queries)}


def _paired_change(fused: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    f, b = {q["query_asset_id"]: q for q in fused}, {q["query_asset_id"]: q for q in baseline}
    result = {}
    for metric, depth in (("top1", 1), ("top3", 3)):
        wins = losses = ties = 0
        for qid, fq in f.items():
            fl = any(x["label"] == fq["query_label"] for x in fq["ranking"][:depth])
            bq = b[qid]
            bl = any(x["label"] == bq["query_label"] for x in bq["ranking"][:depth])
            wins += fl and not bl
            losses += bl and not fl
            ties += fl == bl
        result[metric] = {"improved_queries": wins, "worsened_queries": losses, "unchanged_queries": ties}
    return result


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    reps, query_labels = _validate(data)
    raw, obj = reps["raw_fbm"], reps["object_id_yield"]
    fused_runs: dict[str, list[dict[str, Any]]] = {"rrf": [], "mean_cosine": []}
    for qid in sorted(raw):
        r, o = raw[qid]["gallery"], obj[qid]["gallery"]
        rr, mr = [], []
        for aid in sorted(r):
            # RRF scores use only the prevalidated rank positions; cosine mean uses only scores.
            rr.append({"asset_id": aid, "label": r[aid]["label"], "fusion_score": 1 / (RRF_K + r[aid]["rank"]) + 1 / (RRF_K + o[aid]["rank"])})
            mr.append({"asset_id": aid, "label": r[aid]["label"], "fusion_score": (r[aid]["score"] + o[aid]["score"]) / 2})
        for name, rows in (("rrf", rr), ("mean_cosine", mr)):
            ordered = _order(rows, "fusion_score")
            for i, row in enumerate(ordered, 1):
                row["rank"] = i
            fused_runs[name].append({"query_asset_id": qid, "query_label": query_labels[qid], "ranking": ordered})
    baselines = {}
    for rep, source in (("raw_fbm", raw), ("object_id_yield", obj)):
        baselines[rep] = []
        for qid in sorted(source):
            ordered = sorted(source[qid]["gallery"].items(), key=lambda pair: pair[1]["rank"])
            baselines[rep].append({"query_asset_id": qid, "query_label": query_labels[qid], "ranking": [{"asset_id": aid, "label": row["label"], "rank": row["rank"], "fusion_score": row["score"]} for aid, row in ordered]})
    metrics = {name: _metrics(rows) for name, rows in {**baselines, **fused_runs}.items()}
    comparisons = {fusion: {base: _paired_change(frows, baselines[base]) for base in baselines} for fusion, frows in fused_runs.items()}
    return {
        "status": "synthetic_posthoc_analysis_complete",
        "input_scope": data.get("experiment_scope"),
        "input_representation_count": 2,
        "query_count": 8,
        "gallery_count_per_query": 8,
        "fusion": {"selection_timing": "Exploratory settings selected after inspecting representation baseline results and fixed before computing fusion results; not independently preregistered.", "rrf": {"formula": "1/(60+raw_rank) + 1/(60+object_rank)", "k": RRF_K}, "mean_cosine": {"formula": "(raw_cosine + object_cosine) / 2", "weights": [0.5, 0.5]},
                   "tie_break": "Descending fusion score; ties sorted by SHA256(asset_id UTF-8) ascending, then asset_id ascending; labels are not consulted."},
        "metrics": metrics,
        "paired_changes_vs_baselines": comparisons,
        "fused_queries": fused_runs,
        "random_rank_reference": {"top1_accuracy": 1 / 4, "top3_accuracy": 9 / 14, "interpretation": "reference under arbitrary ranking for 4 equally represented classes and 8 gallery items; not an inferential test"},
        "limitations": ["Synthetic, post hoc exploratory analysis; not independently validated.", "No performance superiority or novelty claim is supported.", "Fusion settings were selected after inspecting baseline results, then held fixed before computing fusion results; weights and RRF k were not tuned on fusion outcomes.", "Labels are used only for metric calculation and paired outcome comparisons, never for fusion or tie-breaking."]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, required=True, help="new JSON file under var; existing files are never overwritten")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    var_root = (project / "var").resolve()
    output = args.output.resolve()
    if not output.is_relative_to(var_root):
        raise SystemExit("output must be under the project var directory")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = analyze(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

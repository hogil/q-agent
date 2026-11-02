"""Controlled synthetic wafer multi-view study; generator recovery only.

No fab data, independent upstream classifier, or real data contract is modeled.
Run --self-check for wiring checks only; --run-study performs the synthetic study.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 20261030
STUDY_SEEDS = (20261030, 20261031, 20261032)
# Exploratory fixed descriptive configuration; set after an initial smoke run.
# These thresholds are reported but do not determine acceptance or conclusions.
MIN_OVERLAP_GAIN = 0.05
MAX_NULL_POSITION_GAIN = 0.05
N_LOTS, WAFERS_PER_LOT, CHIPS_PER_WAFER = 48, 2, 64
N_CLASS, N_MEASURE = 4, 4
ARMS = {
    "raw": ("raw",), "object_yield": ("object_yield",), "measure": ("measure",),
    "raw_object_yield": ("raw", "object_yield"), "raw_measure": ("raw", "measure"),
    "object_yield_measure": ("object_yield", "measure"),
    "all": ("raw", "object_yield", "measure"),
}

@dataclass
class Data:
    lot: np.ndarray
    wafer: np.ndarray
    x: np.ndarray
    y: np.ndarray
    radius: np.ndarray
    labels: np.ndarray
    observed: np.ndarray
    valid: np.ndarray
    raw: np.ndarray
    object_yield: np.ndarray
    measure: np.ndarray
    measure_available: np.ndarray
    wafer_pattern: np.ndarray
    spatial_kind: np.ndarray
    post_cutoff_sentinel: np.ndarray
    join_error_sentinel: np.ndarray
    object_error: float
    object_missing_rate: float
    measure_missing_rate: float
    scenario: str


def make_data(seed: int = SEED, object_error: float = .08, scenario: str = "mixed",
              measure_missing: float = .12, object_missing: float = .05) -> Data:
    """Noisy views from latent multi-hot truth; scenario is mixed or null."""
    if not 0 <= object_error <= 1 or not 0 <= object_missing <= 1 or not 0 <= measure_missing <= 1:
        raise ValueError("object_error, object_missing, and measure_missing must be in [0, 1]")
    if scenario not in {"mixed", "null"}:
        raise ValueError("scenario must be 'mixed' or 'null'")
    streams = [np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(8)]
    layout_rng, truth_rng, raw_rng, object_rng, measure_rng, missing_rng, sentinel_rng, kind_rng = streams
    nw = N_LOTS * WAFERS_PER_LOT
    lot = np.repeat(np.arange(N_LOTS), WAFERS_PER_LOT)
    wafer = np.repeat(np.arange(nw), CHIPS_PER_WAFER)
    lots = np.repeat(lot, CHIPS_PER_WAFER)
    theta = np.tile(np.arange(CHIPS_PER_WAFER) * (2*np.pi/CHIPS_PER_WAFER), nw) + layout_rng.normal(0,.025,nw*CHIPS_PER_WAFER)
    radius = np.sqrt(layout_rng.uniform(.01,.99,nw*CHIPS_PER_WAFER))
    x, y = radius*np.cos(theta), radius*np.sin(theta)
    pattern = np.zeros(nw, dtype=int)
    kind = np.zeros(nw, dtype=int) # 0 null, 1 overlap, 2 A ring, 3 B ring, 4 center
    for l in range(N_LOTS):
        ws = np.flatnonzero(lot == l)
        pattern[ws] = layout_rng.permutation([l % 4, (l+1) % 4])
        for w in ws:
            kind[w] = (0 if scenario == "null" else int(kind_rng.choice([1,2,3,4])))
    cls = np.repeat(pattern, CHIPS_PER_WAFER)
    k = np.repeat(kind, CHIPS_PER_WAFER)
    ring = (radius >= .48) & (radius <= .70)
    # The wafer target is a latent dominant defect class, reflected in chip truth.
    prob = np.tile([.07,.07,.07,.07], (len(radius),1))
    prob[np.arange(len(radius)),cls] += .34
    prob[k == 1, 0] += .18; prob[k == 1, 1] += .18
    prob[(k == 2) & ring, 0] += .28
    prob[(k == 3) & ring, 1] += .28
    prob[(k == 4) & (radius < .38), 2] += .25
    # Null scenario has no spatial modulation; wafer class composition remains.
    labels = truth_rng.random(prob.shape) < prob
    observed = missing_rng.random(len(radius)) >= .04
    valid = observed & (missing_rng.random(len(radius)) >= .03)
    templates = np.eye(4).repeat(2, axis=1)
    raw = labels.astype(float) @ templates + raw_rng.normal(0,.35,(len(radius),8))
    raw = np.clip(raw,0,None); raw[~valid] = 0
    # Object IDs are a noisy oracle sampled from latent class labels, not detector output.
    obj = np.zeros((len(radius),4), float)
    confusion = np.full((4,4), object_error/3); np.fill_diagonal(confusion, 1-object_error)
    for i in range(len(radius)):
        for c in np.flatnonzero(labels[i] & valid[i]):
            obj[i, object_rng.choice(4,p=confusion[c])] += 1
    obj_available = (missing_rng.random(len(radius)) >= object_missing) & valid
    obj[~obj_available] = 0
    yield_value = ((labels.sum(1)==0) & valid & obj_available).astype(float)[:,None]
    status = np.column_stack([observed, valid, obj_available]).astype(float)
    object_yield = np.column_stack([obj,yield_value,status])
    measure = measure_rng.normal(0,1,(len(radius),N_MEASURE))
    strengths = np.array([1.8,1.2,0.,2.1])
    for c in range(4): measure[:,c] += strengths[c]*labels[:,c]
    measure += measure_rng.normal(0,.3,(nw,N_MEASURE))[wafer]
    measure_available = missing_rng.random(len(radius)) >= measure_missing
    measure[~measure_available] = 0
    post_cutoff = sentinel_rng.normal(size=len(radius))
    join_error = sentinel_rng.normal(size=len(radius))
    return Data(lots,wafer,x,y,radius,labels,observed,valid,raw,object_yield,measure,
                measure_available,pattern,kind,post_cutoff,join_error,
                object_error,object_missing,measure_missing,scenario)


def split_lots(d: Data, seed: int = SEED):
    groups = np.random.default_rng(seed).permutation(N_LOTS)
    tr, va, te = groups[:30], groups[30:39], groups[39:]
    return tuple(np.flatnonzero(np.isin(d.lot,g)) for g in (tr,va,te)), (tr,va,te)


def wafer_features(d: Data, arm: str, position: bool, eligible: np.ndarray):
    edges = np.array([0,.38,.48,.70,.84,1.01])
    bins = np.digitize(d.radius, edges[1:-1])
    views = [getattr(d,n) for n in ARMS[arm]]
    ids = np.arange(N_LOTS*WAFERS_PER_LOT)
    out=[]; cov=[]
    for w in ids:
        rows = np.flatnonzero((d.wafer==w)&eligible)
        chunks=[]
        for v in views:
            chunks.append(v[rows].mean(0) if len(rows) else np.zeros(v.shape[1]))
        pooled = np.concatenate(chunks+[np.array([len(rows)/CHIPS_PER_WAFER])])
        if position:
            spatial=[]
            for b in range(5):
                rb=rows[bins[rows]==b]
                for v in views:
                    spatial.append(v[rb].mean(0) if len(rb) else np.zeros(v.shape[1]))
                spatial.append(np.array([len(rb)/CHIPS_PER_WAFER]))
            pooled=np.concatenate([pooled,*spatial])
        out.append(pooled); cov.append(len(rows))
    return ids,np.asarray(out),np.asarray(cov)


def fit_metrics(X, y, train, val, test, seed):
    model=make_pipeline(StandardScaler(),LogisticRegression(C=.35,max_iter=350,random_state=seed))
    model.fit(X[train],y[train]) # scaler and classifier fit on train only
    pred=model.predict(X[test])
    return {"macro_f1":float(f1_score(y[test],pred,average="macro",zero_division=0)),
            "accuracy":float(accuracy_score(y[test],pred)),"n_test":int(len(test)),
            "n_validation_reported_only":int(len(val))}


def spatial_rate_report(d: Data, eligible: np.ndarray, test_lots: np.ndarray):
    """Within-wafer ring-minus-outside rates, preserving multi-hot occurrences."""
    ring=(d.radius>=.48)&(d.radius<=.70)
    kind_names={0:"null",1:"overlap",2:"A_ring",3:"B_ring",4:"center"}
    rows_by_kind={name:[] for name in kind_names.values()}
    for w in range(len(d.wafer_pattern)):
        if d.wafer_pattern.size == 0 or w//WAFERS_PER_LOT not in set(test_lots.tolist()):
            continue
        wafer_rows=(d.wafer==w)&eligible
        row={"wafer_id":int(w),"spatial_kind":kind_names[int(d.spatial_kind[w])],"classes":[]}
        for c in range(N_CLASS):
            regions={}
            for region,region_mask in (("ring",ring),("outside_ring",~ring)):
                ix=np.flatnonzero(wafer_rows & region_mask)
                n=int(len(ix))
                truth_events=int(d.labels[ix,c].sum())
                # Noisy IDs are occurrence counts; multi-hot defects can map to
                # the same ID, so occurrences per chip may exceed one.
                object_events=float(d.object_yield[ix,c].sum())
                regions[region]={"eligible_chips":n,
                                 "truth_defect_events":truth_events,
                                 "truth_events_per_eligible_chip":truth_events/n if n else None,
                                 "object_id_occurrences":object_events,
                                 "object_occurrences_per_eligible_chip":object_events/n if n else None}
            tr,ot=regions["ring"],regions["outside_ring"]
            truth_diff=(tr["truth_events_per_eligible_chip"]-ot["truth_events_per_eligible_chip"] if tr["truth_events_per_eligible_chip"] is not None and ot["truth_events_per_eligible_chip"] is not None else None)
            object_diff=(tr["object_occurrences_per_eligible_chip"]-ot["object_occurrences_per_eligible_chip"] if tr["object_occurrences_per_eligible_chip"] is not None and ot["object_occurrences_per_eligible_chip"] is not None else None)
            row["classes"].append({"class_id":c,"regions":regions,"truth_ring_minus_outside":truth_diff,
                                   "object_ring_minus_outside":object_diff,
                                   "absolute_error_object_vs_truth":abs(object_diff-truth_diff) if object_diff is not None and truth_diff is not None else None})
        rows_by_kind[row["spatial_kind"]].append(row)
    by_kind={}
    for kind,rows in rows_by_kind.items():
        summary=[]
        for c in range(N_CLASS):
            vals=[r["classes"][c] for r in rows]
            td=[v["truth_ring_minus_outside"] for v in vals if v["truth_ring_minus_outside"] is not None]
            od=[v["object_ring_minus_outside"] for v in vals if v["object_ring_minus_outside"] is not None]
            ae=[v["absolute_error_object_vs_truth"] for v in vals if v["absolute_error_object_vs_truth"] is not None]
            n_rows=len(vals)
            truth_n=sum(v["truth_ring_minus_outside"] is not None for v in vals)
            object_n=sum(v["object_ring_minus_outside"] is not None for v in vals)
            error_n=sum(v["absolute_error_object_vs_truth"] is not None for v in vals)
            summary.append({"class_id":c,"n_wafers":n_rows,
                            "truth_valid_wafers":truth_n,"truth_excluded_wafers":n_rows-truth_n,
                            "object_valid_wafers":object_n,"object_excluded_wafers":n_rows-object_n,
                            "error_valid_wafers":error_n,"error_excluded_wafers":n_rows-error_n,
                            "mean_truth_ring_minus_outside":float(np.mean(td)) if td else None,
                            "mean_object_ring_minus_outside":float(np.mean(od)) if od else None,
                            "mean_absolute_error":float(np.mean(ae)) if ae else None})
        by_kind[kind]={"n_test_wafers":len(rows),"class_summary":summary,"per_wafer":rows}
    return {"ring_bin_interval":[.48,.70],"eligibility":"valid AND Measure available AND object map available; identical chips for truth and noisy object rates",
            "object_channel_semantics":"Noisy object-ID occurrence counts divided by eligible chips; this is not a probability and can exceed 1 with multi-hot collisions.",
            "by_spatial_kind":by_kind}


def evaluate(d: Data, seed: int):
    (tr0,va0,te0),manifest=split_lots(d,seed)
    obj_available=d.object_yield[:,-1] > 0
    common=d.valid & d.measure_available & obj_available & np.isfinite(d.raw).all(1)
    # Common eligibility is the controlled comparison; these separate scores
    # intentionally allow each arm's own missingness pattern to change coverage.
    arm_specific_coverage={}
    for arm in ARMS:
        available=d.valid.copy()
        if "object_yield" in ARMS[arm]: available &= obj_available
        if "measure" in ARMS[arm]: available &= d.measure_available
        arm_split=[a[available[a]] for a in (tr0,va0,te0)]
        arm_specific_coverage[arm]={"n_train_validation_test":[len(z) for z in arm_split],
                                    "coverage_fraction":float(available.mean())}
    wafer={}
    for arm in ARMS:
        for pos in (False,True):
            ids,X,cov=wafer_features(d,arm,pos,common)
            lots=ids//WAFERS_PER_LOT
            ti=np.flatnonzero(np.isin(lots,manifest[0])); vi=np.flatnonzero(np.isin(lots,manifest[1])); ei=np.flatnonzero(np.isin(lots,manifest[2]))
            r=fit_metrics(X,d.wafer_pattern[ids],ti,vi,ei,seed)
            r["coverage_chips_per_test_wafer"]={"min":int(cov[ei].min()),"mean":float(cov[ei].mean()),"max":int(cov[ei].max())}
            wafer[f"{arm}|position={'yes' if pos else 'no'}"]=r
    # Pooled and radial model comparison plus wafer-level spatial-rate estimand.
    ids,pooled,cov=wafer_features(d,"object_yield",False,common)
    _,radial,_=wafer_features(d,"object_yield",True,common)
    tew=np.flatnonzero(np.isin(ids//WAFERS_PER_LOT,manifest[2]))
    spatial={"scenario":"mixed includes ring/center spatial modulation" if np.any(d.spatial_kind) else "null has no spatial modulation",
             "ring_bin_interval":[.48,.70],
             "wafer_class_spatial_rates":spatial_rate_report(d,common,manifest[2]),
             "pooled_vs_radial_wafer_macro_f1":{"object_yield_no_position":wafer["object_yield|position=no"]["macro_f1"],"object_yield_radial_position":wafer["object_yield|position=yes"]["macro_f1"],"difference_radial_minus_pooled":wafer["object_yield|position=yes"]["macro_f1"]-wafer["object_yield|position=no"]["macro_f1"]},
             "scope":"Overall held-out LOT test comparison; no scenario-subset model fit or uncertainty interval."}
    obj_rows=d.valid & obj_available
    truth_count=d.labels[obj_rows].sum()
    correct_count=np.sum(d.object_yield[obj_rows,:4] * d.labels[obj_rows])
    object_agreement=float(correct_count/truth_count) if truth_count else None
    return {"seed":seed,"scenario":d.scenario,
            "parameters":{"object_error":d.object_error,"object_missing":d.object_missing_rate,"measure_missing":d.measure_missing_rate},
            "split_lots":{"train":manifest[0].tolist(),"validation":manifest[1].tolist(),"test":manifest[2].tolist()},
            "coverage":{"valid_fraction":float(d.valid.mean()),"measure_available_fraction":float(d.measure_available.mean()),"object_available_fraction":float(obj_available.mean()),"common_eligible_fraction":float(common.mean())},
            "arm_specific_missingness_coverage_only":arm_specific_coverage,
            "wafer_same_eligible_wafer_arms":wafer,"spatial_null_and_mixed":spatial,
            "matching_occurrence_to_truth_event_ratio":object_agreement,
            "matching_occurrence_to_truth_event_ratio_interpretation":"Matching class occurrences divided by truth defect events. Multi-hot truth labels can contribute repeated occurrences to the same object ID, so this ratio can exceed 1 and is not an agreement accuracy.",
            "exploratory_fixed_descriptive_config":{"seeds":list(STUDY_SEEDS),"overlap_gain_min_macro_f1":MIN_OVERLAP_GAIN,"null_position_gain_max_macro_f1":MAX_NULL_POSITION_GAIN,"threshold_use":"Reported descriptively; thresholds do not determine acceptance or study success."},
            "limitations":"Synthetic noisy views from known generator truth; object ID is not an independently trained classifier. No chip classification metric is implemented. No real fab/source-contract inference; radial-bin and pooled comparisons only test this generator."}


def self_check():
    d=make_data(SEED)
    (splits,_)=split_lots(d)
    assert all(len(s)>0 for s in splits)
    split_lots_by_partition=[set(d.lot[s]) for s in splits]
    assert all(not (split_lots_by_partition[i]&split_lots_by_partition[j])
               for i,j in ((0,1),(0,2),(1,2)))
    assert len(STUDY_SEEDS)==len(set(STUDY_SEEDS)) and all(isinstance(s,int) for s in STUDY_SEEDS)
    assert 0 <= MIN_OVERLAP_GAIN <= 1 and 0 <= MAX_NULL_POSITION_GAIN <= 1
    eligible=d.valid & d.measure_available & (d.object_yield[:,-1]>0)
    ids0,X0,c0=wafer_features(d,"all",True,eligible)
    altered=replace(d,labels=~d.labels,wafer_pattern=np.roll(d.wafer_pattern,1),spatial_kind=np.roll(d.spatial_kind,1))
    ids1,X1,c1=wafer_features(altered,"all",True,eligible)
    assert np.array_equal(ids0,ids1) and np.array_equal(X0,X1) and np.array_equal(c0,c1)
    # Paired error/missingness perturbations must preserve truth and unaffected views.
    clean=make_data(SEED,object_error=0.0); noisy=make_data(SEED,object_error=.75)
    missing=make_data(SEED,object_missing=.35)
    for q in (noisy,missing):
        assert np.array_equal(clean.labels,q.labels)
        assert np.array_equal(clean.raw,q.raw) and np.array_equal(clean.measure,q.measure)
        assert np.array_equal(clean.wafer_pattern,q.wafer_pattern)
        assert all(np.array_equal(a,b) for a,b in zip(split_lots(clean,SEED)[1],split_lots(q,SEED)[1]))
    def agreement(q):
        rows=q.valid & (q.object_yield[:,-1] > 0)
        return np.sum(q.object_yield[rows,:4]*q.labels[rows])/q.labels[rows].sum()
    assert agreement(clean) > agreement(noisy)
    masked=missing.object_yield[:,-1] == 0
    assert np.all(missing.object_yield[masked,:N_CLASS] == 0)
    assert d.measure.shape[1]==N_MEASURE and d.object_yield.shape[1]==N_CLASS+4
    assert np.any(d.labels.sum(1)==0) and np.any(d.labels.sum(1)>1)
    null=make_data(SEED,scenario="null")
    assert np.all(null.spatial_kind==0)
    # Scenario choice is on its own random stream: shared layout, wafer targets,
    # lot split, and common eligibility stay paired; spatial labels may differ.
    assert np.array_equal(d.x,null.x) and np.array_equal(d.y,null.y) and np.array_equal(d.radius,null.radius)
    assert np.array_equal(d.wafer_pattern,null.wafer_pattern)
    assert all(np.array_equal(a,b) for a,b in zip(split_lots(d,SEED)[1],split_lots(null,SEED)[1]))
    def common_eligibility(q):
        return q.valid & q.measure_available & (q.object_yield[:,-1] > 0) & np.isfinite(q.raw).all(1)
    assert np.array_equal(common_eligibility(d),common_eligibility(null))
    # Verify target signal and approximate spatial null directly from generated truth.
    target_rates=np.array([d.labels[d.wafer==w].mean(0) for w in range(len(d.wafer_pattern))])
    dominant=target_rates[np.arange(len(target_rates)),d.wafer_pattern]
    assert dominant.mean() > target_rates.mean(axis=1).mean()+.20
    null_ring=null.labels[(null.radius>=.48)&(null.radius<=.70)].mean(0)
    null_else=null.labels[~((null.radius>=.48)&(null.radius<=.70))].mean(0)
    assert np.max(np.abs(null_ring-null_else)) < .06
    positive=make_data(SEED,scenario="mixed")
    m=(positive.spatial_kind[positive.wafer]==2)
    chip_m=m & (positive.radius>=.48)&(positive.radius<=.70)
    chip_o=m & ~((positive.radius>=.48)&(positive.radius<=.70))
    assert positive.labels[chip_m,0].mean() > positive.labels[chip_o,0].mean()
    # This only checks that sentinel arrays are absent from feature construction.
    # It does not exercise or validate any join logic or temporal cutoff.
    sentinel_changed=replace(d,post_cutoff_sentinel=d.post_cutoff_sentinel+1000,join_error_sentinel=d.join_error_sentinel-1000)
    assert np.array_equal(wafer_features(d,"all",True,eligible)[1],wafer_features(sentinel_changed,"all",True,eligible)[1])
    report=spatial_rate_report(d,eligible,split_lots(d,SEED)[1][2])
    assert set(report["by_spatial_kind"]) == {"null","overlap","A_ring","B_ring","center"}
    assert report["by_spatial_kind"]["null"]["n_test_wafers"] == 0
    assert all(report["by_spatial_kind"][k]["n_test_wafers"] > 0 for k in ("overlap","A_ring","B_ring","center"))
    first=report["by_spatial_kind"]["overlap"]["per_wafer"][0]
    assert len(first["classes"])==N_CLASS
    for item in first["classes"]:
        for region in ("ring","outside_ring"):
            cell=item["regions"][region]
            assert cell["eligible_chips"] > 0
            assert cell["truth_events_per_eligible_chip"] is not None
            assert cell["object_occurrences_per_eligible_chip"] is not None
    try:
        make_data(SEED,object_error=1.1)
    except ValueError:
        pass
    else:
        raise AssertionError("out-of-range object_error must be rejected")
    return {"lot_split_all_pairs_disjoint":True,"study_seed_list_unique":True,"descriptive_threshold_bounds_valid":True,"features_independent_of_truth_mutation":True,"paired_error_missingness_preserves_truth_raw_measure_split":True,"object_error_reduces_matching_occurrence_to_truth_event_ratio":True,"missing_object_ids_masked":True,"wafer_target_has_truth_signal":True,"mixed_null_pairing_preserves_layout_target_split_and_common_eligibility":True,"spatial_treatment_may_change_labels_and_views":True,"null_and_positive_spatial_controls":True,"per_wafer_truth_and_noisy_spatial_rates_have_denominators":True,"unknown_and_multi_hot_truth_preserved":True,"sentinel_fields_absent_from_features_only_not_join_or_cutoff_validation":True,"all_views_have_fixed_shapes":True,"input_ranges_validated":True,"no_models_fitted":True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check",action="store_true")
    mode.add_argument("--run-study",action="store_true")
    p.add_argument("--seed",type=int,default=SEED)
    p.add_argument("--scenario",choices=["mixed","null"],default="mixed")
    p.add_argument("--object-error",type=float,default=.08)
    p.add_argument("--object-missing",type=float,default=.05)
    p.add_argument("--measure-missing",type=float,default=.12)
    a=p.parse_args()
    if not 0 <= a.object_error <= 1 or not 0 <= a.object_missing <= 1 or not 0 <= a.measure_missing <= 1:
        p.error("--object-error, --object-missing, and --measure-missing must be in [0, 1]")
    if a.self_check:
        result=self_check()
    else:
        seeds=STUDY_SEEDS if a.seed==SEED else (a.seed,)
        result={"seed_results":[evaluate(make_data(s,a.object_error,a.scenario,a.measure_missing,a.object_missing),s) for s in seeds]}
    print(json.dumps(result,indent=2))

if __name__=="__main__": main()

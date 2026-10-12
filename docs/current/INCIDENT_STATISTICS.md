# Incident Statistics

2026-10-12: implemented for the mapped, read-only SQLite adapter. Corporate
PostgreSQL, grade expansion, and monetary loss fields are not implemented.

## Query

```powershell
python app/query_demo.py --config config/config.yaml --overlay config/demo.yaml --department SYNTH-QA --statistics --group-by product_generations --from 2026-03-01T00:00:00+09:00 --to 2026-04-01T00:00:00+09:00 --comparison-from 2026-02-01T00:00:00+09:00 --comparison-to 2026-03-01T00:00:00+09:00
```

The basic fixture returns March 4, February 3, difference +1, and +33.33%.
March generation counts are A=4/B=2/C=2; February A=3/B=2/C=1.
An incident may belong to multiple generation groups. Do not sum those groups
to obtain the population count or divide recorded quantities among generations.

## Scope and Integrity

- `summarize_incidents` is a first-stage incident DB Tool, with `sql_aggregate`.
- SQL computes the entire filtered population within a read transaction.
- `top_k` limits displayed groups, not the aggregate population.
- `comparison_period` replaces only the time predicate. Baseline zero yields
  a null percentage rather than zero or infinity.
- `scope_complete=false` disables detail retrieval but preserves full counts.
- `find_incidents(scope_mode="cohort")` enables explicit structured population
  analysis. Incident numbers, titles, and title terms cannot auto-select cohorts.
- Quantity sums include missing counts and describe recorded, not verified,
  impact. Dataset completeness remains unknown.
- For pure statistics, after Judge and Answer, code renders the final answer
  and claims from SQL outputs. The unverified model draft remains in the trace.
  This guarantee does not extend to mixed-source causal analysis answers.

Statistics instructions and argument schemas load with the `statistics` topic.
Changes require explicit release freeze before runtime use.

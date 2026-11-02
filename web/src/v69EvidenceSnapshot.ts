export type ResearchMilestoneV69 = {
  schema_id: string;
  status: string;
  synthetic: boolean;
  production: boolean;
  promotion: boolean;
  general_LLM_quality_established: boolean;
  proof_count: number;
  proofs: { id: string; path: string; sha256: string; status: string }[];
  native_fixed_four: {
    status: string; input: string; fits: number; fresh_conf: number; supported: number;
    supported_positive: number; supported_normal: number; promotion: boolean;
    families: Record<string, {
      average_precision: number; auc: number; selective_recall: number;
      unconditional_recall: number; false_positives: number; normal_supported: number;
      one_sided95_cp_upper_selective_fpr: number;
    }>;
    limits: string[];
  };
  native_metric_audit: { status: string; recomputed_exact: boolean };
  native_observability: { status: string; posthoc_descriptive_only: boolean; limits: string[] };
  evidence_v16: {
    status: string; wall_limit_seconds: number; actual_elapsed_seconds: number; llm_returns: number;
    answer_generation_called: boolean; answer_raw_returned: boolean; question_quality_pass: boolean;
    semantic_improvement_established: boolean; limits: string[];
  };
  weighted_v3: { status: string; trained: boolean };
  limits: string[];
};

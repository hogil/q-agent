export type ResearchMilestoneV68 = {
  schema_id: string;
  status: string;
  synthetic: boolean;
  production: boolean;
  general_LLM_quality_established: boolean;
  proof_count: number;
  proofs: { id: string; path: string; sha256: string; status: string }[];
  native_phase_a: {
    status: string; samples: number; contexts: number; point_records: number;
    sql_references_passed: number; model_training: boolean; limits: string[];
  };
  mht_standalone: {
    status: string; default_cases_exact: number; default_matches_compared: number;
    mht_queries: number; source_read_calls: number; distinct_mht_documents: number;
    standalone_only: boolean; e5_federation_connected: boolean; limits: string[];
  };
  evidence_v15_1: {
    status: string; llm_returns: number; tool_calls: number; evidence_facts: number;
    approved_facts: number; answer_last: boolean; new_actions: number; forecast_included: boolean;
    hangul_characters: number; whole_question_satisfied: boolean; limits: string[];
  };
  metrology_policy_v5: {
    status: string; llm_returns: number; approved_fact_count: number; judge_decision: string;
    finding: string; new_request_cells: number; new_request_wafers: number; new_actions: number;
    whole_task_satisfied: boolean; limits: string[];
  };
  limits: string[];
};

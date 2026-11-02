import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { AlertTriangle, ChevronDown, Database, Loader2, Search } from 'lucide-react';
import { api, type Incident } from './api';
import './platform.css';

type Row = Record<string, unknown>;
type Catalog = { default_as_of?: string; status: string; synthetic: true; counts: Record<string, number>; incidents: Incident[]; next_offset: number | null; notice?: string };
type CaseData = { status: string; synthetic: true; incident: Incident; scope: Row; sections: Record<string, { rows: Row[]; assets?: Row[]; count: number; truncated: boolean; status: string }>; trend_series?: { item: string; unit: string; points: { timestamp: string; value: number }[] }[]; tabular_analysis?: Row; map_analysis?: { cases?: Row[]; incident_count?: number; truncated?: boolean; [key: string]: unknown }; cross_modal_alignment?: Row; model_observations?: { modality: string; label: string; score: number; [key: string]: unknown }[]; findings: { source: string; observation: string; limitation: string }[]; history: { incident_id: string; incident_number: string; title: string; occurred_at: string; similarity: number; modalities: string[] }[]; coverage: { source: string; count: number; returned_count: number; status: string }[]; model_status?: Row; limitations: string[] };
type Candidate = { field: string; value: string; mention: string; match: string; description?: string; ambiguous: boolean; score?: number; requires_confirmation?: boolean };
type Models = { status: string; synthetic: true; models: { modality: string; status?: string; method?: string; train_groups?: number; holdout_groups?: number; accuracy?: number }[]; notice?: string };
type Profile = { synthetic: true; tables: { entity: string; rows: number; columns: { field: string; description: string; distinct_count: number; null_count: number; top_values?: unknown[] }[] }[] };
type Analysis = { status: string; answer: string; answer_generation_mode?: string; limitations?: string[]; tool_calls?: Row[]; evidence?: Row[]; claims?: Row[]; llm_called: boolean; tabular_analysis?: unknown; map_analysis?: unknown; llm_metrics?: Row; };
const sources = ['mes', 'test', 'measure', 'failbit', 'sem', 'trend', 'inform'];
const labels: Record<string, string> = { incident: '사고', lot_list: 'Lot', wafer_list: 'Wafer', mes: 'MES / Fab', test: 'EDS / FAB_OUT', measure: 'Measure 원자료 행', failbit: 'Failbit bit 관측', sem: 'SEM 이미지', trend: 'Trend', inform: 'Inform / 회의' };
const text = (value: unknown) => value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const rows = (value: unknown) => Array.isArray(value) ? value.filter((row): row is Row => !!row && typeof row === 'object') : [];
const first = (row: Row, keys: string[]) => keys.map((key) => row[key]).find((value) => value !== undefined && value !== null);

export default function PlatformView() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [query, setQuery] = useState('');
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [appliedFilter, setAppliedFilter] = useState<{ field: string; value: string } | null>(null);
  const [selected, setSelected] = useState('');
  const [asOf, setAsOf] = useState('');
  const [trendItem, setTrendItem] = useState('');
  const [data, setData] = useState<CaseData | null>(null);
  const [models, setModels] = useState<Models | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [analysisQuestion, setAnalysisQuestion] = useState('');
  const [analysis, setAnalysis] = useState<{ result: Analysis; incident: string; asOf: string } | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const sequence = useRef(0);
  const catalogSequence = useRef(0);
  const analysisSequence = useRef(0);

  async function loadCatalog(q: string, next = 0, append = false, filter?: { field: string; value: string } | null) {
    const request = ++catalogSequence.current;
    const activeFilter = filter === undefined ? appliedFilter : filter;
    setBusy(true); setError('');
    try {
      const params = new URLSearchParams({ q: activeFilter ? '' : q, offset: String(next), limit: '40' });
      if (activeFilter) { params.set('field', activeFilter.field); params.set('value', activeFilter.value); }
      const result = await api<Catalog>(`/platform/catalog?${params.toString()}`);
      if (request !== catalogSequence.current) return;
      setCatalog(result); setAsOf((current) => current || result.default_as_of || ''); setIncidents((current) => append ? [...current, ...result.incidents] : result.incidents);
      setNextOffset(result.next_offset);
      if (!append && result.incidents.length === 0) {
        ++sequence.current; setSelected(''); setData(null); setTrendItem('');
      } else if (result.incidents[0] && !result.incidents.some((row) => row.incident_number === selected)) {
        ++sequence.current; setData(null); setSelected(result.incidents[0].incident_number);
      }
    } catch (e) { if (request === catalogSequence.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (request === catalogSequence.current) setBusy(false); }
  }
  async function loadCase(number = selected, date = asOf) {
    if (!number) return;
    const request = ++sequence.current; setData(null); setTrendItem(''); setBusy(true); setError('');
    try {
      const result = await api<CaseData>(`/platform/case?incident=${encodeURIComponent(number)}&as_of=${encodeURIComponent(date)}`);
      if (request === sequence.current) { setData(result); setTrendItem(result.trend_series?.[0]?.item || ''); }
    } catch (e) { if (request === sequence.current) { setData(null); setError(e instanceof Error ? e.message : String(e)); } }
    finally { if (request === sequence.current) setBusy(false); }
  }
  useEffect(() => {
    let active = true;
    const catalogRequest = ++catalogSequence.current;
    api<Catalog>('/platform/catalog?q=&offset=0&limit=40').then((result) => {
      if (!active || catalogRequest !== catalogSequence.current) return; setCatalog(result); setAsOf((current) => current || result.default_as_of || ''); setIncidents(result.incidents); setNextOffset(result.next_offset);
      if (result.incidents[0]) setSelected(result.incidents[0].incident_number);
    }).catch((e) => { if (active && catalogRequest === catalogSequence.current) setError(e instanceof Error ? e.message : String(e)); });
    api<Models>('/platform/models').then((result) => { if (active) setModels(result); }).catch(() => undefined);
    api<Profile>('/platform/profile').then((result) => { if (active) setProfile(result); }).catch(() => undefined);
    return () => { active = false; ++sequence.current; ++catalogSequence.current; };
  }, []);
  useEffect(() => {
    if (!selected) return;
    void loadCase(selected, asOf);
    return () => { ++sequence.current; };
  }, [selected]);
  useEffect(() => {
    ++analysisSequence.current; setAnalysis(null); setAnalysisError(''); setAnalysisBusy(false);
  }, [selected, asOf]);

  async function runAnalysis() {
    const incidentNumber = selected;
    const scopeDate = visibleData?.scope?.as_of;
    if (!incidentNumber || typeof scopeDate !== 'string' || scopeDate !== asOf) return;
    const request = ++analysisSequence.current;
    const frozen = { incident: incidentNumber, asOf: scopeDate };
    setAnalysis(null); setAnalysisError(''); setAnalysisBusy(true);
    try {
      const result = await api<Analysis>('/platform/analyze', 'POST', {
        incident_number: frozen.incident, as_of: frozen.asOf,
        ...(analysisQuestion.trim() ? { question: analysisQuestion.trim() } : {}),
      });
      if (request === analysisSequence.current) setAnalysis({ result, ...frozen });
    } catch (e) {
      if (request === analysisSequence.current) setAnalysisError(e instanceof Error ? e.message : String(e));
    } finally {
      if (request === analysisSequence.current) setAnalysisBusy(false);
    }
  }

  async function submitSearch(event: FormEvent) {
    event.preventDefault(); const q = query.trim(); setAppliedFilter(null); await loadCatalog(q, 0, false, null);
    if (q) {
      try { const result = await api<{ candidates: Candidate[] }>(`/platform/match?q=${encodeURIComponent(q)}`); setCandidates(result.candidates || []); }
      catch { setCandidates([]); }
    } else setCandidates([]);
  }
  function applyCandidate(candidate: Candidate) {
    const filter = { field: candidate.field, value: candidate.value };
    setAppliedFilter(filter);
    void loadCatalog('', 0, false, filter);
  }
  const visibleData = data?.incident.incident_number === selected ? data : null;
  const selectedIncident = incidents.find((row) => row.incident_number === selected) || visibleData?.incident;
  const caseRows = visibleData?.sections || {};
  const series = visibleData?.trend_series || [];
  const selectedSeries = series.find((row) => row.item === trendItem) || series[0];
  const fallbackTrend = rows(caseRows.trend?.rows);
  const trend = useMemo(() => selectedSeries?.points?.map((point) => ({ t: point.timestamp, v: Number(point.value) })).filter((point) => Number.isFinite(point.v)) || (() => {
    const firstRow = fallbackTrend[0];
    const item = first(firstRow || {}, ['item']); const unit = first(firstRow || {}, ['unit']);
    return fallbackTrend.filter((row) => first(row, ['item']) === item && first(row, ['unit']) === unit)
      .map((row) => ({ t: text(first(row, ['timestamp', 'time', 'date'])), v: Number(first(row, ['value'])) }))
      .filter((point) => Number.isFinite(point.v));
  })(), [selectedSeries, fallbackTrend]);
  const trendPath = useMemo(() => {
    if (trend.length < 2) return '';
    const min = Math.min(...trend.map((point) => point.v)); const max = Math.max(...trend.map((point) => point.v));
    return trend.map((point, index) => `${index ? 'L' : 'M'} ${(index * 600) / (trend.length - 1)} ${90 - ((point.v - min) / (max - min || 1)) * 75}`).join(' ');
  }, [trend]);

  return <main className="platform-view">
    <header className="platform-head"><div><span className="platform-kicker">Q-AGENT · SYNTHETIC DATA</span><h1>통합 불량 분석</h1><p>선택한 합성 사고의 조회 근거를 확인하고, 요청 시 local LLM 복합 분석을 실행합니다.</p></div><span className="platform-badge"><Database size={14}/> 합성 데이터 · 읽기 전용</span></header>
    <section className="platform-counts" aria-label="데이터 건수">{Object.entries(catalog?.counts || {}).map(([key, count]) => <div key={key}><span>{labels[key] || key}</span><strong>{count.toLocaleString()}</strong></div>)}{!catalog && <span>데이터 현황 불러오는 중</span>}</section>
    {catalog?.notice && <p className="platform-catalog-notice">{catalog.notice}</p>}
    <section className="platform-controls">
      <form onSubmit={submitSearch} className="platform-search"><label htmlFor="platform-query">사고 / 질문 검색</label><div><Search size={16}/><input id="platform-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="사고번호 또는 자연어 질의"/><button className="primary-button" disabled={busy}>검색</button></div></form>
      <div className="platform-case-picker"><label htmlFor="platform-case">사고 선택</label><select id="platform-case" value={selected} onChange={(e) => setSelected(e.target.value)}><option value="">사고 선택</option>{incidents.map((item) => <option key={item.incident_number} value={item.incident_number}>{item.incident_number} · {item.title}</option>)}</select>{appliedFilter && <small>적용 조건: {appliedFilter.field} = {appliedFilter.value}</small>}{nextOffset !== null && <button className="text-button" onClick={() => void loadCatalog('', nextOffset, true)}>다음 사고 불러오기</button>}</div>
      <div className="platform-date"><label htmlFor="platform-asof">기준 시점</label><input id="platform-asof" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)}/><button className="outline-button" disabled={!selected || busy} onClick={() => void loadCase()}>범위 조회</button></div>
    </section>
    {error && <div className="error-banner" role="alert"><AlertTriangle size={16}/>{error}<button className="text-button" onClick={() => void loadCatalog(query)}>다시 시도</button></div>}
    {candidates.length > 0 && <section className="platform-candidates"><h2>질의에서 찾은 후보 <small>버튼을 눌러야 해당 값으로 사고를 조회합니다</small></h2><div>{candidates.map((candidate, index) => <article key={`${candidate.field}-${candidate.value}-${index}`}><strong>{candidate.mention}</strong><span>{candidate.field}: {candidate.value}</span>{candidate.description && <small>{candidate.description}</small>}<em>{candidate.ambiguous || candidate.requires_confirmation ? '사용자 확인 필요' : '선택 가능한 후보'}</em><button className="outline-button" disabled={busy} onClick={() => applyCandidate(candidate)}>이 값으로 조회</button></article>)}</div></section>}
    {busy && !data ? <div className="platform-state"><Loader2 className="spin"/> 사고 범위 조회 중</div> : !selectedIncident ? <div className="platform-state">검색 결과가 없거나 조회 가능한 사고가 없습니다.</div> : <>
      <section className="platform-scope"><div><small>선택 사고</small><h2>{selectedIncident.incident_number} · {selectedIncident.title}</h2><p>{selectedIncident.occurred_at} · {selectedIncident.department} · 결과 기준 {text(visibleData?.scope?.as_of)}{asOf !== text(visibleData?.scope?.as_of) && ` · 입력 기준 ${asOf} (재조회 전)`}</p></div><dl><div><dt>조회 상태</dt><dd>{visibleData?.status || (busy ? '조회 중' : '조회 대기')}</dd></div><div><dt>사고 범위</dt><dd>{text(visibleData?.scope?.incident_ids || [selectedIncident.incident_number])}</dd></div><div><dt>합성</dt><dd>예 · 실제 원인 판정 아님</dd></div></dl></section>
      <section className="platform-coverage"><h2>데이터 소스 범위</h2><div className="platform-coverage-grid">{sources.map((source) => { const item = data?.coverage?.find((entry) => entry.source === source); const section = caseRows[source]; const count = item?.count ?? section?.count ?? 0; const status = item?.status || section?.status || '조회 대기'; return <div key={source}><span>{labels[source]}</span><strong>{count.toLocaleString()}</strong><small>{status}{item && item.returned_count !== item.count ? ` · ${item.returned_count}건 반환` : ''}</small></div>; })}</div></section>
      <section className="platform-findings"><h2>관측 요약 <small>확인된 데이터와 제한</small></h2><div className="platform-finding-grid">{(data?.findings || []).map((finding, index) => <article key={`${finding.source}-${index}`}><strong>{labels[finding.source] || finding.source}</strong><p>{finding.observation}</p><small>{finding.limitation}</small></article>)}</div></section>
      {visibleData?.tabular_analysis && <section className="platform-grain-analysis"><h2>Tabular feature 분석 <small>합성 관측 · 실제 공정 검증 안 됨</small></h2><p className="platform-grain-note">기존 Measure item 수와 확장 dummy feature 수는 다른 단위입니다. 모델 입력은 composite chip 단위 row이며, 추가 dummy feature는 합성 변수입니다.</p><div className="platform-grain-metrics"><Metric label="상태" value={visibleData.tabular_analysis.status}/><Metric label="원본 Measure item" value={visibleData.tabular_analysis.source_feature_count ?? visibleData.tabular_analysis.measure_item_count}/><Metric label="합성 dummy feature" value={visibleData.tabular_analysis.dummy_feature_count}/><Metric label="전체 feature" value={visibleData.tabular_analysis.feature_count}/><Metric label="고유 chip row" value={visibleData.tabular_analysis.chip_count}/><Metric label="표시 이상 chip" value={visibleData.tabular_analysis.flagged_chip_count}/><Metric label="선택 feature" value={visibleData.tabular_analysis.selected_feature_count}/></div>{Array.isArray(visibleData.tabular_analysis.selected_features) && <p className="platform-grain-note">선택 feature: {text(visibleData.tabular_analysis.selected_features)}</p>}{rows(visibleData.tabular_analysis.chips).length > 0 && <><p className="platform-grain-note">표본 chip 행 · {rows(visibleData.tabular_analysis.chips).length}건 표시 · 이상 점수는 합성 feature 기준입니다.</p><MiniTable data={rows(visibleData.tabular_analysis.chips).slice(0, 10)} fields={['lot_id', 'wafer_id', 'chip_id', 'stage', 'flagged', 'anomaly_score', 'top_feature_deviations']}/></>}<details><summary>Tabular 분석 세부 정보</summary><pre>{text(JSON.stringify(visibleData.tabular_analysis).slice(0, 10000))}</pre></details></section>}
      {visibleData?.map_analysis && <section className="platform-grain-analysis"><h2>Map feature 분석 <small>합성 관측 · 실제 공정 검증 안 됨</small></h2><p className="platform-grain-note">Wafer 국소 비반복 이상 · Chip 내부 motif · Wafer 내 chip 반복 motif는 별도 가설입니다. Die, chip pixel, bit 좌표는 서로 다른 범위입니다.</p><div className="platform-grain-metrics"><Metric label="사고 수" value={visibleData.map_analysis.incident_count}/><Metric label="일부 생략" value={visibleData.map_analysis.truncated ? '예' : '아니오'}/></div><div className="platform-map-cases">{(visibleData.map_analysis.cases || []).slice(0, 8).map((item, index) => { const analysisDetail = item.analysis && typeof item.analysis === 'object' ? item.analysis as Row : {}; const analyses = analysisDetail.analyses && typeof analysisDetail.analyses === 'object' ? analysisDetail.analyses as Row : analysisDetail.grains && typeof analysisDetail.grains === 'object' ? analysisDetail.grains as Row : {}; const assets = rows(item.assets); const mapImages = [...assets.filter((asset) => asset.kind === 'wafer').slice(0, 1), ...assets.filter((asset) => asset.kind === 'chip').slice(0, 3)]; const scopeAsset = assets[0]; return <article key={`${text(item.incident_id)}-${index}`}><header><strong>{text(item.incident_id)}</strong><span>{text(item.status)} · Lot {text(scopeAsset?.lot_id)} · Wafer {text(scopeAsset?.wafer_id)} · 기준 {text(item.as_of)}</span></header>{[['wafer_local_anomaly', 'Wafer 국소 비반복 이상'], ['chip_internal_motif', 'Chip 내부 motif'], ['cross_chip_repeated_motif', 'Wafer 내 chip 반복 motif']].map(([key, title]) => <details key={key}><summary>{title} · {text((analyses[key] as Row | undefined)?.status ?? (analyses[key] as Row | undefined)?.count ?? '결과 확인')}</summary><pre>{text(JSON.stringify(analyses[key] ?? null).slice(0, 6000))}</pre></details>)}{Boolean(analysisDetail.coordinate_semantics) && <details><summary>좌표 범위 정의</summary><pre>{text(JSON.stringify(analysisDetail.coordinate_semantics).slice(0, 2500))}</pre></details>}{!!mapImages.length && <div className="platform-map-previews"><strong>합성 map 자산 · Wafer 1장 + Chip 최대 3장</strong><div>{mapImages.map((asset, assetIndex) => { const id = text(asset.asset_id); return <figure key={`${id}-${assetIndex}`}><img src={`/api/platform/map-asset?asset_id=${encodeURIComponent(id)}`} alt={`합성 ${text(asset.kind)} map 미리보기`} loading="lazy"/><figcaption>{asset.kind === 'wafer' ? 'Wafer map' : 'Chip crop'} · Lot {text(asset.lot_id)} · Wafer {text(asset.wafer_id)}{asset.chip_id != null ? ` · Chip ${text(asset.chip_id)}` : ''}<small>SHA {text(asset.sha256).slice(0, 12)}…</small></figcaption></figure>; })}</div></div>}</article>; })}</div><details><summary>Map 분석 전체 메타데이터</summary><pre>{text(JSON.stringify(visibleData.map_analysis).slice(0, 10000))}</pre></details></section>}
      {visibleData?.cross_modal_alignment && <section className="platform-grain-analysis"><h2>Cross-modal 정렬 <small>동일 composite chip key 기준</small></h2><div className="platform-grain-metrics"><Metric label="기준 grain" value={visibleData.cross_modal_alignment.grain}/><Metric label="source별 고유 chip 수" value={visibleData.cross_modal_alignment.chip_counts}/><Metric label="source별 교집합 chip 수" value={visibleData.cross_modal_alignment.overlap_chip_counts}/></div>{Array.isArray(visibleData.cross_modal_alignment.keys) && <p className="platform-grain-note">정렬 key: {text(visibleData.cross_modal_alignment.keys)}</p>}{Array.isArray(visibleData.cross_modal_alignment.limitations) && <ul>{(visibleData.cross_modal_alignment.limitations as unknown[]).map((item, index) => <li key={`align-${index}`}>{text(item)}</li>)}</ul>}</section>}
      <section className="platform-analysis">
        <h2>LLM 복합 분석 <small>선택 사고와 조회 기준 시점에 고정 · 합성 데이터</small></h2>
        <label htmlFor="platform-analysis-question">분석 질문 <span>선택 입력</span></label>
        <textarea id="platform-analysis-question" value={analysisQuestion} onChange={(event) => setAnalysisQuestion(event.target.value)} placeholder="예: 측정값과 MES·Failbit·SEM 관측이 서로 일치하는 점과 확인이 필요한 점을 정리해줘" rows={3}/>
        <div className="platform-analysis-actions"><button className="primary-button" disabled={analysisBusy || !selected || !visibleData || visibleData.scope.as_of !== asOf} onClick={() => void runAnalysis()}>{analysisBusy ? <><Loader2 className="spin" size={14}/> 분석 중</> : 'LLM 복합 분석 실행'}</button>{visibleData && visibleData.scope.as_of !== asOf && <small>기준 시점을 바꿨습니다. 먼저 “범위 조회”로 해당 시점의 근거를 불러오세요.</small>}{analysisError && <span role="alert">{analysisError}<button className="text-button" onClick={() => void runAnalysis()}>다시 시도</button></span>}</div>
        {analysis && analysis.incident === selected && analysis.asOf === visibleData?.scope.as_of && <article className="platform-analysis-result">
          <header><strong>{analysis.result.answer_generation_mode === 'llm_ranking_with_tool_facts_and_frozen_skill_recipes' ? '근거 기반 검토 보고서' : analysis.result.llm_called ? 'LLM 응답' : 'LLM 미호출'}</strong><span>{analysis.result.status} · 사고 {analysis.incident} · 기준 {analysis.asOf} · 합성</span></header>
          {analysis.result.answer_generation_mode === 'llm_ranking_with_tool_facts_and_frozen_skill_recipes' && <small className="platform-analysis-mode-note">수량은 DB 집계이며, 검토 순서는 LLM이 선택했습니다.</small>}
          <p className="platform-analysis-answer">{analysis.result.answer || '표시할 답변이 없습니다.'}</p>
          {!!analysis.result.evidence?.length && <div className="platform-analysis-refs"><strong>근거 참조</strong>{analysis.result.evidence.slice(0, 16).map((item, index) => <span key={`ev-${index}`}>{text(first(item, ['source', 'source_ref']) ?? '근거')} · {text(first(item, ['evidence_id', 'id', 'record_id', 'asset_id']) ?? first(item, ['status', 'count']))}</span>)}</div>}
          {!!analysis.result.claims?.length && <div className="platform-analysis-claims"><strong>답변 주장과 연결된 근거</strong>{analysis.result.claims.slice(0, 12).map((claim, index) => <article key={`claim-${index}`}><p>{text(first(claim, ['statement', 'text', 'claim']))}</p><small>근거 ID: {text(claim.evidence_ids || claim.evidence_id || '연결된 근거 없음')}</small></article>)}</div>}
          {!!analysis.result.tool_calls?.length && <div className="platform-analysis-refs"><strong>Tool 조회 상태</strong>{analysis.result.tool_calls.slice(0, 12).map((item, index) => <span key={`tool-${index}`}>{text(first(item, ['tool', 'name', 'source']))} · {text(first(item, ['status', 'result', 'count']))}</span>)}</div>}
          {analysis.result.tabular_analysis != null && <details><summary>Tabular 분석</summary><pre>{text(JSON.stringify(analysis.result.tabular_analysis).slice(0, 12000))}</pre></details>}
          {analysis.result.map_analysis != null && <details><summary>Map 분석</summary><pre>{text(JSON.stringify(analysis.result.map_analysis).slice(0, 12000))}</pre></details>}
          {!!analysis.result.limitations?.length && <ul>{analysis.result.limitations.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}
          {analysis.result.llm_metrics && <small>LLM 처리 정보 · 호출 {text(analysis.result.llm_metrics.calls ?? '—')} · Tool {text(analysis.result.llm_metrics.tools ?? '—')} · 입력 토큰 {metricTokenTotal(analysis.result.llm_metrics, 'input_tokens') ?? '미제공'} · 출력 토큰 {metricTokenTotal(analysis.result.llm_metrics, 'output_tokens') ?? '미제공'}</small>}
        </article>}
      </section>
      <section className="platform-evidence"><h2>조회 근거 <small>소스별 원자료는 요청 시 펼쳐집니다</small></h2><div className="platform-evidence-grid">{sources.map((source) => { const section = caseRows[source]; const sourceRows = rows(section?.rows); const failbitScope = chipScope(sourceRows); return <article className="platform-evidence-card" key={source}><header><div><strong>{labels[source]}</strong><small>{section?.count ?? 0}건 · {section?.status || '미조회'}</small></div><button className="icon-button" aria-expanded={!!expanded[source]} aria-label={`${labels[source]} 원자료 ${expanded[source] ? '접기' : '보기'}`} onClick={() => setExpanded((state) => ({ ...state, [source]: !state[source] }))}><ChevronDown size={16}/></button></header>{source === 'trend' && <>{series.length > 1 && <label className="platform-trend-select">Trend item <select value={selectedSeries?.item || ''} onChange={(event) => setTrendItem(event.target.value)}>{series.map((item) => <option key={item.item} value={item.item}>{item.item} · {item.unit}</option>)}</select></label>}{trendPath && <><small className="platform-trend-label">{selectedSeries?.item || text(first(fallbackTrend[0] || {}, ['item']))} · {selectedSeries?.unit || text(first(fallbackTrend[0] || {}, ['unit']))} · {trend[0]?.t} – {trend.at(-1)?.t}</small><svg className="platform-sparkline" viewBox="0 0 600 100" role="img" aria-label="합성 Trend 미리보기"><path d={trendPath}/></svg></>}</>}{source === 'sem' && sourceRows.slice(0, 3).map((row, index) => { const id = text(first(row, ['asset_id', 'id'])); return <div className="platform-sem" key={`${id}-${index}`}><img src={`/api/platform/asset?asset_id=${encodeURIComponent(id)}`} alt="합성 SEM 미리보기" loading="lazy"/><span>{text(first(row, ['label', 'wafer_id', 'description']))}</span></div>; })}{source === 'test' && <p className="platform-note">EDS Electrical Die Sorting · FAB_OUT failure code는 별도 항목으로 표시</p>}{source === 'measure' && sourceRows.length > 0 && <><p className="platform-note">die_x / die_y는 chip 위치 좌표이며 bit 좌표와 구분됩니다.</p><MiniTable data={sourceRows.slice(0, 8)} fields={['chip_id', 'item', 'value', 'unit', 'lower_limit', 'upper_limit']}/></>}{source === 'failbit' && <Failbit rows={failbitScope.rows} chip={failbitScope.chip} assets={rows(section?.assets)}/>}{expanded[source] && <MiniTable data={sourceRows.slice(0, 12)} fields={sourceRows[0] ? Object.keys(sourceRows[0]).slice(0, 7) : []}/>}{section?.truncated && <small className="platform-truncated">표시 건수가 제한되었습니다.</small>}</article>; })}</div></section>
      <section className="platform-history"><h2>유사 과거 사례 <small>cosine ranking · 원인 확정 근거 아님</small></h2>{visibleData?.history?.length ? <div>{visibleData.history.slice(0, 6).map((item) => <article key={item.incident_id}><strong>{item.incident_number}</strong><span>{item.title}</span><small>{item.occurred_at} · cosine {item.similarity.toFixed(6)} · 공통 modality: {item.modalities.join(', ') || '없음'}</small></article>)}</div> : <p>비교 가능한 과거 사례가 없습니다.</p>}</section>
      <section className="platform-models"><h2>모델 상태</h2><strong>{models?.status || '상태 확인 불가'}</strong>{models?.models?.map((model) => <span key={model.modality}>{model.modality} · {model.method || model.status || 'NOT_TRAINED'}{model.train_groups !== undefined ? ` · train ${model.train_groups} / holdout ${model.holdout_groups}` : ''}{model.accuracy !== undefined ? ` · ${(model.accuracy * 100).toFixed(1)}%` : ''}</span>)}<small>{models?.notice || '모델 출력은 참고 상태이며 생산 판정에 사용하지 않습니다.'}</small></section>
      {visibleData?.model_observations?.length ? <section className="platform-models"><h2>합성 모델 관측 <small>학습 분포 score · 불량 판정 아님</small></h2>{visibleData.model_observations.map((item, index) => <span key={`${item.modality}-${index}`}>{item.modality} · {item.label} · score {item.score.toFixed(3)}</span>)}</section> : null}
      {profile?.tables?.length ? <details className="platform-profile"><summary>합성 DB 구조 프로파일 · metadata only</summary><div className="platform-table-wrap"><table><thead><tr><th>Entity</th><th>행 수</th><th>컬럼</th><th>설명</th><th>Distinct / Null</th></tr></thead><tbody>{profile.tables.flatMap((table) => table.columns.map((column) => <tr key={`${table.entity}-${column.field}`}><td>{table.entity}</td><td>{table.rows}</td><td>{column.field}</td><td className="platform-profile-description">{column.description}</td><td>{column.distinct_count} / {column.null_count}</td></tr>))}</tbody></table></div></details> : null}
      <ul className="platform-limitations">{(data?.limitations || []).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
    </>}
  </main>;
}

function MiniTable({ data, fields }: { data: Row[]; fields: string[] }) {
  const columns = fields.length ? fields : data[0] ? Object.keys(data[0]).slice(0, 6) : [];
  if (!data.length) return <p className="platform-note">표시할 행이 없습니다.</p>;
  return <div className="platform-table-wrap"><table><thead><tr>{columns.map((field) => <th key={field}>{field}</th>)}</tr></thead><tbody>{data.map((row, index) => <tr key={String(row.record_id ?? row.id ?? `${row.chip_id ?? 'row'}-${index}`)}>{columns.map((field) => <td key={field}>{text(row[field])}</td>)}</tr>)}</tbody></table></div>;
}
function Metric({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === null) return null;
  return <div><span>{label}</span><strong>{text(value)}</strong></div>;
}
function metricTokenTotal(metrics: Row, field: 'input_tokens' | 'output_tokens') {
  const roleMetrics = rows(metrics.by_role);
  const seen = new Set<string>();
  const values = roleMetrics.filter((entry) => {
    const signature = JSON.stringify(entry);
    if (seen.has(signature)) return false;
    seen.add(signature); return true;
  }).map((entry) => {
    const nested = entry.metrics && typeof entry.metrics === 'object' ? entry.metrics as Row : {};
    return entry[field] ?? nested[field];
  }).filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  const direct = metrics[field];
  if (!values.length && typeof direct === 'number' && Number.isFinite(direct)) values.push(direct);
  return values.length ? values.reduce((sum, value) => sum + value, 0) : undefined;
}
function chipScope(data: Row[]) {
  const firstRow = data[0];
  if (!firstRow || !['lot_id', 'wafer_id', 'chip_id'].every((key) => firstRow[key] !== undefined)) return { rows: [] as Row[], chip: null as Row | null };
  const key = (row: Row) => ['lot_id', 'wafer_id', 'chip_id'].map((field) => row[field]).join('\u0000');
  return { rows: data.filter((row) => key(row) === key(firstRow)), chip: firstRow };
}
function Failbit({ rows: data, chip, assets }: { rows: Row[]; chip: Row | null; assets: Row[] }) {
  if (!data.length) return <p className="platform-note">Failbit 원자료가 없습니다.</p>;
  return <><p className="platform-note">Failbit bitmap 범위: Lot {text(chip?.lot_id)} · Wafer {text(chip?.wafer_id)} · Chip {text(chip?.chip_id)} · bit_x / bit_y는 chip 내부 bit 좌표입니다.</p><div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}><div style={{ flex: '1 1 220px' }} className="platform-failbits">{data.map((row, index) => { const x = Number(row.bit_x); const y = Number(row.bit_y); const left = Number.isFinite(x) ? Math.max(0, Math.min(90, x)) : 0; const top = Number.isFinite(y) ? Math.max(0, Math.min(90, y)) : 0; return <span key={`${row.record_id ?? row.chip_id}-${index}`} title={`Chip ${text(row.chip_id)} · bit (${text(row.bit_x)}, ${text(row.bit_y)}) · ${text(row.bin_code)}`} style={{ left: `${left}%`, top: `${top}%` }}/>; })}<small>선택 Chip의 Failbit 위치 샘플 · 칩별 수율 지도 아님</small></div><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', flex: '1 1 190px' }}>{assets.slice(0, 4).map((asset, index) => { const id = text(asset.asset_id); return <div className="platform-sem" key={`${id}-${index}`}><img src={`/api/platform/asset?asset_id=${encodeURIComponent(id)}`} alt="합성 Failbit composite chip 이미지" loading="lazy"/><span>Composite {text(asset.stage)} · {text(asset.lot_id)}/{text(asset.wafer_id)}/{text(asset.chip_id)}</span><small>SHA {text(asset.sha256).slice(0, 12)}… · 좌표 {text(asset.coordinate_system)}</small></div>; })}</div></div></>;
}

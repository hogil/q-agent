import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  ArrowUpRight,
  Check,
  ArrowLeft,
  FileText,
  Focus,
  RotateCcw,
  Search,
  ShieldAlert,
  X,
} from 'lucide-react';
import { type Attachment, type Incident } from './api';
import { Chart } from './charts';
import { Empty, type Tab, type ViewProps } from './Views';
import { OperationsView } from './OperationsView';
import InvestigationBoard from './InvestigationBoard';
import HistoricalCorrelation from './HistoricalCorrelation';
import { historicalData, selectHistoricalData } from './historicalData';
import { anomalyTrendOption, trendSelectionFromTime } from './anomalyTrend';
import {
  makeEngineeringData,
  type EngineeringData,
  type Signal,
} from './engineeringData';
import {
  correlationSummary,
  defaultSelection,
  selectFabRows,
  parseEngineeringReference,
  parseSelection,
  parsePairKey,
  pairKey,
  type InvestigationSelection,
} from './engineeringAnalysis';
import './engineering.css';

const time = (value: string) => value.slice(5, 16).replace('T', ' ');
type SelectionChange = (patch: Partial<InvestigationSelection>) => void;

function EngineeringTrend({
  data,
  selection,
  change,
  compact = false,
  comparisonEquipment = '',
}: {
  data: EngineeringData;
  selection: InvestigationSelection;
  change: SelectionChange;
  compact?: boolean;
  comparisonEquipment?: string;
}) {
  const signal = data.signals.find((s) => s.id === selection.signalId)!;
  const option = useMemo(
    () => anomalyTrendOption(data, selection, compact, comparisonEquipment),
    [data, selection, compact, comparisonEquipment],
  );
  return (
    <Chart
      option={option}
      label={`합성 ${signal.title} 구간 Trend`}
      className={compact ? 'eng-preview-chart' : 'eng-trend-chart'}
      onRange={
        compact
          ? undefined
          : (range) => change(trendSelectionFromTime(data, range))
      }
    />
  );
}

function SignalList({
  data,
  selection,
  choose,
}: {
  data: EngineeringData;
  selection: InvestigationSelection;
  choose: (signal: Signal) => void;
}) {
  const [search, setSearch] = useState('');
  const [severity, setSeverity] = useState('all');
  const rows = data.signals
    .filter(
      (s) =>
        (severity === 'all' || s.severity === severity) &&
        `${s.item} ${s.title} ${s.equipment} ${s.step} ${s.recipe}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    )
    .sort(
      (a, b) =>
        Number(b.severity === 'high') - Number(a.severity === 'high') ||
        b.detectedAt.localeCompare(a.detectedAt),
    );
  return (
    <section className="detail-view signal-view">
      <div className="section-title">
        <div>
          <h2>이상 감지 목록</h2>
          <span>선택 사고 범위 · Synthetic detection feed</span>
        </div>
        <span className="status-tag amber">감지 모델 미연결</span>
      </div>
      <div className="eng-summary-band">
        <div>
          <span>감지 항목</span>
          <strong>
            {data.signals.length}
            <small> signals</small>
          </strong>
        </div>
        <div>
          <span>우선 확인</span>
          <strong className="eng-warn">
            {data.signals.filter((s) => s.severity === 'high').length}
            <small> high</small>
          </strong>
        </div>
        <div>
          <span>등록 Wafer 매칭 후보</span>
          <strong>
            {data.fab.length}
            <small> wafers</small>
          </strong>
        </div>
      </div>
      <div className="view-toolbar">
        <label className="inline-search eng-search">
          <Search size={15} />
          <input
            aria-label="이상 감지 검색"
            placeholder="설비 / 공정 / 감지 항목"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className="select-field">
          우선순위
          <select
            aria-label="감지 우선순위"
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            <option value="all">전체</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
          </select>
        </label>
      </div>
      <div className="eng-table-wrap">
        <table className="eng-table">
          <thead>
            <tr>
              <th>우선순위</th>
              <th>Item / Step</th>
              <th>설비</th>
              <th>감지 시각 · UTC</th>
              <th>조회</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((signal) => (
              <tr
                key={signal.id}
                className={signal.id === selection.signalId ? 'selected' : ''}
              >
                <td>
                  <span className={`eng-severity ${signal.severity}`}>
                    {signal.severity.toUpperCase()}
                  </span>
                </td>
                <td>
                  <button
                    className="eng-record-button"
                    onClick={() => choose(signal)}
                  >
                    <strong>
                      {signal.item} · {signal.title}
                    </strong>
                    <small>
                      {signal.step} · {signal.recipe}
                    </small>
                  </button>
                </td>
                <td>{signal.equipment}</td>
                <td>{time(signal.detectedAt)}</td>
                <td>
                  <button
                    className="icon-button"
                    title={`${signal.title} Trend 열기`}
                    onClick={() => choose(signal)}
                  >
                    <ArrowUpRight size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <Empty title="일치하는 감지 항목 없음" detail="현재 필터 결과 0건" />
      )}
      <div className="eng-preview-heading">
        <h3>{data.signals.find((s) => s.id === selection.signalId)?.title}</h3>
        <span className="synthetic-label">합성 Trace</span>
      </div>
      <EngineeringTrend
        data={data}
        selection={selection}
        change={() => {}}
        compact
      />
    </section>
  );
}

export default function EngineeringWorkspace({
  roomId,
  tab,
  reference,
  children,
  prepare,
  attachments,
  notes,
  onNotes,
  onRemoveAttachment,
  onOpenAttachment,
  storageError,
  incidents,
  onConversationChange,
  ...props
}: ViewProps & {
  roomId: string;
  onConversationChange: () => void;
  tab: Tab;
  reference: string;
  prepare: (question: string) => void;
  attachments: Attachment[];
  notes: string;
  onNotes: (value: string) => void;
  onRemoveAttachment: (item: Attachment) => void;
  onOpenAttachment: (item: Attachment) => void;
  storageError: boolean;
  incidents: Incident[];
  children: (context: {
    initialWafer?: { lotId: string; waferId: string };
  }) => ReactNode;
}) {
  const data = useMemo(
    () => makeEngineeringData(props.workspace),
    [props.workspace],
  );
  const key = `engineering-context:v1:${encodeURIComponent(roomId)}:${encodeURIComponent(props.workspace.incident.incident_number)}`;
  const [selection, setSelection] = useState<InvestigationSelection>(() => {
    try {
      return (
        parseSelection(JSON.parse(localStorage.getItem(key) || 'null'), data) ||
        defaultSelection(data)
      );
    } catch {
      return defaultSelection(data);
    }
  });
  const [selectedPairKey, setSelectedPairKey] = useState(() => {
    try {
      return parsePairKey(
        JSON.parse(localStorage.getItem(key) || 'null')?.selectedPairKey,
        data,
      );
    } catch {
      return '';
    }
  });
  const [saved, setSaved] = useState(true);
  useEffect(() => {
    try {
      localStorage.setItem(
        key,
        JSON.stringify({ ...selection, selectedPairKey }),
      );
      setSaved(true);
    } catch {
      setSaved(false);
    }
  }, [key, selection, selectedPairKey]);
  useEffect(() => {
    const restored = parseEngineeringReference(reference, data);
    if (restored) {
      setSelection(restored);
      setSelectedPairKey('');
    } else {
      const down = data.downtime.find(
        (row) => reference === `engineering:down:${row.id}`,
      );
      const wip = data.wip.find(
        (row) => reference === `engineering:wip:${row.lotId}`,
      );
      if (down) {
        const end = data.trend.findIndex(
          (point) => point.timestamp >= down.end,
        );
        setSelection((current) => ({
          ...current,
          equipment: down.equipment,
          start: Math.max(
            0,
            data.trend.filter((point) => point.timestamp <= down.start).length -
              1,
          ),
          end: end < 0 ? data.trend.length - 1 : end,
        }));
      } else if (wip) {
        setSelection((current) => ({
          ...current,
          equipment: wip.equipment,
          recipe: wip.recipe,
        }));
      }
    }
  }, [reference, data]);
  const signal =
    data.signals.find((s) => s.id === selection.signalId) || data.signals[0];
  const change: SelectionChange = (patch) => {
    setSelection(
      (current) => parseSelection({ ...current, ...patch }, data) || current,
    );
    setSelectedPairKey('');
  };
  const history = useMemo(
    () =>
      selectHistoricalData(
        historicalData(props.workspace, data),
        data,
        selection,
      ),
    [props.workspace, data, selection],
  );
  const selectedPair =
    selectFabRows(data, selection).find(
      (row) => pairKey(row) === selectedPairKey,
    ) || null;
  const summary = correlationSummary(
    history.map((row) => ({ value: row.temperature, yieldPct: row.yieldPct })),
  );
  const choose = (s: Signal) => {
    setSelection({
      ...defaultSelection(data),
      signalId: s.id,
      start: s.startIndex,
      end: s.endIndex,
      equipment: s.equipment,
    });
    setSelectedPairKey('');
    props.navigate('trend');
  };
  const windowLabel = `${time(data.trend[selection.start]?.timestamp || '')} – ${time(data.trend[selection.end]?.timestamp || '')} UTC`;
  const scopedWip = data.wip.filter(
    (row) =>
      (!selection.equipment || row.equipment === selection.equipment) &&
      (!selection.recipe || row.recipe === selection.recipe),
  );
  const scopedDown = data.downtime.filter(
    (row) =>
      (!selection.equipment || row.equipment === selection.equipment) &&
      row.start <= data.trend[selection.end]?.timestamp &&
      row.end >= data.trend[selection.start]?.timestamp,
  );
  if (!signal) return children({});
  return (
    <div
      className={`engineering-workspace ${tab === 'trend' ? 'board-workspace' : ''}`}
    >
      {tab !== 'signals' && tab !== 'trend' && (
        <div className="eng-context">
          <div className="eng-context-heading">
            <button
              className="eng-back"
              title="감지 목록으로 돌아가기"
              onClick={() => props.navigate('signals')}
            >
              <ArrowLeft size={15} />
              <strong>{signal.title}</strong>
            </button>
            <button
              className="eng-window-link"
              title="Trend 구간 변경"
              onClick={() => props.navigate('trend')}
            >
              {windowLabel}
            </button>
          </div>
          <div className="eng-context-filters">
            <label className="select-field">
              후속 조회 설비
              <select
                aria-label="조사 설비"
                value={selection.equipment}
                onChange={(e) => change({ equipment: e.target.value })}
              >
                <option value="">전체 설비</option>
                {[...new Set(data.signals.map((s) => s.equipment))].map(
                  (id) => (
                    <option key={id}>{id}</option>
                  ),
                )}
              </select>
            </label>
            <label className="select-field">
              Recipe
              <select
                aria-label="조사 Recipe"
                value={selection.recipe}
                onChange={(e) => change({ recipe: e.target.value })}
              >
                <option value="">전체 Recipe</option>
                {[...new Set(data.fab.map((row) => row.recipe))].map(
                  (recipe) => (
                    <option key={recipe}>{recipe}</option>
                  ),
                )}
              </select>
            </label>
            <button
              className="icon-button"
              title="감지 조건으로 초기화"
              onClick={() =>
                change({
                  ...defaultSelection(data),
                  signalId: signal.id,
                  start: signal.startIndex,
                  end: signal.endIndex,
                  equipment: signal.equipment,
                })
              }
            >
              <RotateCcw size={15} />
            </button>
          </div>
          {selectedPair && tab === 'map' && (
            <div className="eng-selected-context">
              <Focus size={14} />
              <strong>
                {selectedPair.lotId} / {selectedPair.waferId}
              </strong>
              <button
                className="text-button"
                onClick={() => props.navigate('correlation')}
              >
                상관분석으로
                <ArrowUpRight size={13} />
              </button>
              <button
                className="icon-button"
                title="Wafer 선택 해제"
                onClick={() => setSelectedPairKey('')}
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>
      )}
      {!saved && (
        <p className="save-error" role="status">
          조사 조건 저장 실패 · 브라우저 저장소 확인 필요
        </p>
      )}
      {tab === 'correlation' && reference.startsWith('engineering:corr:') && (
        <p className="data-notice">
          이전 합성 비교의 선택 조건입니다. 현재 화면은 같은 Item의 과거 완료
          이력 기준이며, 이전 계산 결과를 재현한 것이 아닙니다.
        </p>
      )}
      {tab === 'signals' ? (
        <SignalList data={data} selection={selection} choose={choose} />
      ) : tab === 'trend' ? (
        <InvestigationBoard
          {...props}
          roomId={roomId}
          onConversationChange={onConversationChange}
          attachments={attachments}
          notes={notes}
          onNotes={onNotes}
          onRemoveAttachment={onRemoveAttachment}
          onOpenAttachment={onOpenAttachment}
          storageError={storageError}
          incidents={incidents}
          data={data}
          selection={selection}
          change={change}
          choose={choose}
          focusedKey={selectedPairKey}
          onFocus={(row) => setSelectedPairKey(pairKey(row))}
          trend={(comparisonEquipment) => (
            <EngineeringTrend
              data={data}
              selection={selection}
              change={change}
              comparisonEquipment={comparisonEquipment}
            />
          )}
        />
      ) : tab === 'correlation' ? (
        <HistoricalCorrelation
          workspace={props.workspace}
          data={data}
          selection={selection}
        />
      ) : tab === 'production' ? (
        <OperationsView
          key={reference}
          {...props}
          reference={reference}
          data={data}
          window={{
            from: data.trend[selection.start].timestamp,
            to: data.trend[selection.end].timestamp,
          }}
          equipment={selection.equipment}
          recipe={selection.recipe}
          selectEquipment={(equipment) => change({ equipment })}
        />
      ) : tab === 'assessment' ? (
        <section className="detail-view assessment-view">
          <div className="section-title">
            <div>
              <h2>설명 · 판정</h2>
              <span>선택 조건 기반 근거 요약</span>
            </div>
            <span className="status-tag amber">LLM 미연결</span>
          </div>
          <div className="eng-verdict">
            <ShieldAlert size={25} />
            <div>
              <span>현재 판정 상태</span>
              <h3>원인 판정 보류</h3>
              <p>
                합성 관측의 연관성을 확인한 단계입니다. 실제 공정
                원인·출하·Hold/Release 판단은 수행하지 않았습니다.
              </p>
            </div>
          </div>
          <section className="eng-finding">
            <h3>관측과 해석</h3>
            <p>
              <strong>{signal.title}</strong>의 같은 Item 과거 완료 이력에서
              Fab·EDS {summary.n}쌍이 매칭됐습니다.{' '}
              {summary.r === null
                ? `${summary.reason || '유효한 상관계수 없음'}으로 상관계수를 보고하지 않습니다.`
                : summary.r === 0
                  ? 'Pearson r = 0.000이며, 이 합성 관측에서 선형 연관성이 나타나지 않았습니다.'
                  : `Pearson r = ${summary.r.toFixed(3)}이며, 이는 합성 Wafer 관측의 ${summary.r < 0 ? '음' : '양'}의 연관성입니다.`}
            </p>
            <p>
              선택 설비의 합성 재공 {scopedWip.length} Lot, Hold{' '}
              {scopedWip.filter((r) => r.status === 'HOLD').length} Lot, 시간
              구간과 겹치는 다운 이벤트 {scopedDown.length}건입니다. 시간상
              겹침만으로 원인 관계를 확정하지 않습니다.
            </p>
          </section>
          <div className="eng-evidence-matrix">
            <h3>근거와 확인 상태</h3>
            {[
              {
                name: '사고 DB',
                detail:
                  props.workspace.incident.confirmed_cause ||
                  '확정 원인 필드 없음',
                status: '합성 DB 조회',
                target: 'data',
              },
              {
                name: 'Fab / EDS',
                detail: `과거 완료 ${summary.n}쌍 · 현재 Fab Wafer는 EDS 대기`,
                status: '로컬 계산',
                target: 'correlation',
              },
              {
                name: '승인 회의록',
                detail: `${props.workspace.meetings.length}개 chunk · 기준 ${props.workspace.as_of}`,
                status: '합성 DB 조회',
                target: 'inform',
              },
              {
                name: 'MES / FDC',
                detail: '생산 이력·센서 원본·Recipe 변경',
                status: '원본 미연결',
                target: 'production',
              },
              {
                name: 'Eng’r Inform',
                detail: '작성자·승인자·문서 버전·공정 변경 근거',
                status: '원본 미연결',
                target: 'inform',
                mode: 'engineer',
              },
              {
                name: 'SEM / Overlay',
                detail: `선택 이미지·Map 참조 ${attachments.filter((a) => ['image', 'map'].includes(a.kind)).length}개 · 실제 측정 관계 미검증`,
                status: '합성 뷰어',
                target: 'map',
              },
            ].map((row) => (
              <button
                key={row.name}
                onClick={() =>
                  props.navigate(row.target as Tab, undefined, row.mode)
                }
              >
                <strong>{row.name}</strong>
                <span>{row.detail}</span>
                <small>{row.status}</small>
                <ArrowUpRight size={14} />
              </button>
            ))}
          </div>
          <section className="eng-finding eng-meeting-findings">
            <h3>최근 승인 회의록 기록</h3>
            {[...props.workspace.meetings]
              .sort(
                (a, b) =>
                  b.meeting_date.localeCompare(a.meeting_date) ||
                  b.version.localeCompare(a.version, undefined, {
                    numeric: true,
                  }),
              )
              .slice(0, 2)
              .map((meeting) => (
                <button
                  key={meeting.chunk_id}
                  onClick={() => props.navigate('inform', meeting.chunk_id)}
                >
                  <span>
                    {meeting.title} · {meeting.meeting_date} · {meeting.version}
                    <ArrowUpRight size={14} />
                  </span>
                  <p>{meeting.text}</p>
                  <small>{meeting.source_ref}</small>
                </button>
              ))}
            {!props.workspace.meetings.length && (
              <p>현재 범위의 승인 회의록 없음</p>
            )}
          </section>
          <section className="eng-finding">
            <h3>판정 전 추가 확인</h3>
            <ul>
              <li>
                동일 Recipe·설비·제품 조건의 정상 참조군과 Lot 내 반복 관측 구분
              </li>
              <li>
                Fab 측정부터 EDS 검사까지의 시차, 재작업·Hold와 누락 Wafer
              </li>
              <li>
                센서 Trace, 보정·Recipe 변경 시각, 다운코드 원본과 승인 Inform
              </li>
              <li>SEM 위치와 Wafer/Die 좌표 일치, Overlay 정렬 및 측정 단위</li>
            </ul>
          </section>
          <div className="eng-runtime">
            <h3>Agent 실행 연결</h3>
            {['Router', '사고 DB', '후속 Tool', 'Judge', 'Answer'].map(
              (role) => (
                <div key={role}>
                  <span>{role}</span>
                  <span>
                    {role === '사고 DB'
                      ? '합성 DB 조회 완료'
                      : role === '후속 Tool'
                        ? '로컬 합성 자료 · Agent Tool 미연결'
                        : 'LLM 미실행'}
                  </span>
                </div>
              ),
            )}
          </div>
          <div className="eng-action-row">
            <button
              className="outline-button"
              onClick={() => props.navigate('review')}
            >
              <FileText size={15} />
              검토 메모
            </button>
            <button
              className="primary-button"
              onClick={() =>
                prepare(
                  `${props.workspace.incident.incident_number}의 ${signal.title} 항목을 분석해줘. 구간 ${windowLabel}, 설비 ${selection.equipment || '전체'}, Recipe ${selection.recipe || '전체'}, EDS 시차 최대 ${selection.maxLagDays}일. 합성 과거 Fab·EDS 매칭 n=${summary.n}, r=${summary.r?.toFixed(3) ?? 'N/A'}. 회의록, 생산 재공, 설비 다운코드, SEM·Overlay 원본을 확인하고 사실·가설·판정 보류 사유를 구분해줘. 현재 UI의 계산값은 합성 예시이며 실제 원인 근거가 아니다.`,
                )
              }
            >
              <Check size={15} />
              채팅 질문 준비
            </button>
          </div>
        </section>
      ) : (
        children({
          initialWafer: selectedPair
            ? { lotId: selectedPair.lotId, waferId: selectedPair.waferId }
            : undefined,
        })
      )}
    </div>
  );
}

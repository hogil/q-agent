import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  FileText,
  Focus,
  Link2,
  RotateCcw,
  Search,
  ScatterChart,
  ShieldAlert,
  X,
} from 'lucide-react';
import { download, type Attachment } from './api';
import { Chart } from './charts';
import { Empty, type Tab, type ViewProps } from './Views';
import { OperationsView } from './OperationsView';
import {
  makeEngineeringData,
  matchFabYield,
  type EngineeringData,
  type Signal,
} from './engineeringData';
import {
  correlationSummary,
  defaultSelection,
  engineeringReference,
  parseEngineeringReference,
  parseSelection,
  parsePairKey,
  pairKey,
  type InvestigationSelection,
} from './engineeringAnalysis';
import './engineering.css';

const time = (value: string) => value.slice(5, 16).replace('T', ' ');
const metrics = {
  temperature: { name: 'Fab 공정 온도', unit: '°C', limit: 67 },
  queue: { name: 'Queue time', unit: 'h', limit: 6 },
  availability: { name: '설비 가동률', unit: '%', limit: 90 },
};
type SelectionChange = (patch: Partial<InvestigationSelection>) => void;
type Pair = ReturnType<typeof matchFabYield>['pairs'][number];

function EngineeringTrend({
  data,
  selection,
  change,
  compact = false,
}: {
  data: EngineeringData;
  selection: InvestigationSelection;
  change: SelectionChange;
  compact?: boolean;
}) {
  const signal = data.signals.find((s) => s.id === selection.signalId)!;
  const metric = metrics[signal.metric];
  const option = useMemo(
    () => ({
      animationDuration: 180,
      textStyle: {
        fontFamily: 'Segoe UI, Malgun Gothic, sans-serif',
        fontSize: 11,
      },
      grid: { left: 55, right: 24, top: 35, bottom: 42 },
      tooltip: { trigger: 'axis', renderMode: 'richText' },
      brush: compact
        ? undefined
        : {
            xAxisIndex: 0,
            brushType: 'lineX',
            brushMode: 'single',
            throttleType: 'debounce',
            throttleDelay: 200,
          },
      xAxis: {
        type: 'category',
        data: data.trend.map((p) => time(p.timestamp)),
        axisLabel: { color: '#73818a', interval: 4 },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: '#dce4e5' } },
      },
      yAxis: {
        type: 'value',
        scale: true,
        name: metric.unit,
        nameTextStyle: { color: '#62767e' },
        splitLine: { lineStyle: { color: '#e8edef', type: 'dashed' } },
      },
      series: [
        {
          type: 'line',
          name: `${metric.name} · 합성`,
          smooth: false,
          symbolSize: 5,
          data: data.trend.map((p) => p[signal.metric]),
          lineStyle: { width: 2.5, color: '#367f99' },
          itemStyle: { color: '#367f99' },
          markArea: {
            silent: true,
            itemStyle: { color: 'rgba(54,127,153,.12)' },
            data: [[{ xAxis: selection.start }, { xAxis: selection.end }]],
          },
          markLine: {
            silent: true,
            symbol: 'none',
            label: { formatter: '예시 기준', position: 'insideEndTop' },
            lineStyle: { color: '#c3874e', type: 'dashed' },
            data: [{ yAxis: metric.limit }],
          },
        },
      ],
    }),
    [data, signal, selection.start, selection.end, compact, metric],
  );
  return (
    <Chart
      option={option}
      label={`합성 ${metric.name} 구간 Trend`}
      className={compact ? 'eng-preview-chart' : 'eng-trend-chart'}
      onRange={
        compact
          ? undefined
          : ([a, b]) =>
              change({
                start: Math.max(0, Math.min(a, b)),
                end: Math.min(data.trend.length - 1, Math.max(a, b)),
              })
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
        `${s.title} ${s.equipment} ${s.step} ${s.recipe}`
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
              <th>감지 항목 / 공정</th>
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
                    <strong>{signal.title}</strong>
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

function CorrelationView({
  pairs,
  match,
  selection,
  change,
  selectedPair,
  setSelectedPair,
  attach,
  pinned,
  navigate,
}: {
  pairs: Pair[];
  match: ReturnType<typeof matchFabYield>;
  selection: InvestigationSelection;
  change: SelectionChange;
  selectedPair: Pair | null;
  setSelectedPair: (pair: Pair) => void;
  attach: ViewProps['attach'];
  pinned: boolean;
  navigate: ViewProps['navigate'];
}) {
  const summary = correlationSummary(pairs);
  const [fullYieldAxis, setFullYieldAxis] = useState(false);
  const selectedIndex = pairs.findIndex((row) => row === selectedPair);
  const option = useMemo(
    () => ({
      animationDuration: 200,
      textStyle: {
        fontFamily: 'Segoe UI, Malgun Gothic, sans-serif',
        fontSize: 11,
      },
      grid: { left: 63, right: 25, top: 28, bottom: 53 },
      tooltip: {
        trigger: 'item',
        renderMode: 'richText',
        formatter: (p: any) => {
          const row = pairs[p.dataIndex];
          return row
            ? `${row.lotId} / ${row.waferId}\nFab ${row.value.toFixed(2)} °C\nEDS ${row.yieldPct.toFixed(2)}%\n${row.equipment} · ${row.recipe}`
            : '';
        },
      },
      xAxis: {
        type: 'value',
        scale: true,
        min: ({ min }: { min: number }) => Math.floor((min - 0.1) * 10) / 10,
        max: ({ max }: { max: number }) => Math.ceil((max + 0.1) * 10) / 10,
        name: 'Fab 공정 온도 (°C)',
        nameLocation: 'middle',
        nameGap: 32,
        splitLine: { lineStyle: { color: '#edf0f2' } },
      },
      yAxis: {
        type: 'value',
        min: fullYieldAxis
          ? 0
          : Math.max(
              0,
              Math.floor(Math.min(...pairs.map((row) => row.yieldPct)) - 2),
            ),
        max: fullYieldAxis
          ? 100
          : Math.min(
              100,
              Math.ceil(Math.max(...pairs.map((row) => row.yieldPct)) + 2),
            ),
        name: 'EDS Yield (%)',
        splitLine: { lineStyle: { color: '#edf0f2' } },
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 14,
          data: pairs.map((row) => ({
            value: [row.value, row.yieldPct],
            itemStyle: {
              color: row.recipe.endsWith('A') ? '#3b8697' : '#c77a63',
              borderColor:
                selectedPair?.lotId === row.lotId &&
                selectedPair.waferId === row.waferId
                  ? '#244e44'
                  : '#fff',
              borderWidth: 2,
            },
          })),
        },
      ],
    }),
    [pairs, selectedPair, fullYieldAxis],
  );
  const groups = [...new Set(pairs.map((p) => p.recipe))].map((recipe) => ({
    recipe,
    ...correlationSummary(pairs.filter((p) => p.recipe === recipe)),
  }));
  return (
    <section className="detail-view correlation-view">
      <div className="section-title">
        <div>
          <h2>Fab × EDS Yield</h2>
          <span>Lot + Wafer 결합 · Fab 측정시각 기준 · 합성 데이터</span>
        </div>
        <div className="eng-inline-actions">
          <button
            className="outline-button"
            disabled={pinned}
            onClick={() =>
              attach({
                kind: 'trend',
                id: engineeringReference('corr', selection),
                label: `합성 Fab × EDS · n=${summary.n} · r=${summary.r?.toFixed(3) ?? 'N/A'}`,
              })
            }
          >
            {pinned ? <Check size={15} /> : <Link2 size={15} />}
            {pinned ? '근거 선택됨' : '근거 선택'}
          </button>
          <button
            className="outline-button"
            onClick={() => navigate('assessment')}
          >
            <ClipboardCheck size={15} />
            설명 · 판정
          </button>
          <button
            className="icon-button"
            title="Fab EDS 매칭 결과 JSON 다운로드"
            onClick={() =>
              download(
                'synthetic-fab-eds.json',
                JSON.stringify(
                  { synthetic: true, selection, match, summary },
                  null,
                  2,
                ),
              )
            }
          >
            <ArrowDownToLine size={17} />
          </button>
        </div>
      </div>
      <div className="eng-summary-band">
        <div>
          <span>매칭 완료</span>
          <strong>
            {pairs.length}
            <small> / {match.eligible}</small>
          </strong>
        </div>
        <div>
          <span>Pearson r</span>
          <strong>{summary.r?.toFixed(3) ?? 'N/A'}</strong>
        </div>
        <div>
          <span>평균 EDS Yield</span>
          <strong>
            {summary.meanYield?.toFixed(1) ?? 'N/A'}
            <small>{summary.meanYield === null ? '' : ' %'}</small>
          </strong>
        </div>
      </div>
      <div className="view-toolbar">
        <label className="eng-axis-toggle">
          <input
            type="checkbox"
            checked={fullYieldAxis}
            onChange={(e) => setFullYieldAxis(e.target.checked)}
          />
          Yield 축 0–100%
        </label>
        <label className="select-field">
          최대 EDS 시차
          <select
            aria-label="EDS 최대 시차"
            value={selection.maxLagDays}
            onChange={(e) => change({ maxLagDays: Number(e.target.value) })}
          >
            {[0, 3, 7, 14, 30].map((d) => (
              <option key={d} value={d}>
                {d}일
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="eng-quality-strip">
        <span>누락 {match.missing}</span>
        <span>중복·모호 {match.ambiguous}</span>
        <span>시차 제외 {match.outsideLag}</span>
        <span>상관관계 ≠ 인과관계</span>
      </div>
      <div className="eng-correlation-layout">
        <div className="eng-plot-region">
          {pairs.length ? (
            <Chart
              option={option}
              label="합성 Fab 공정 온도와 EDS Yield 산점도"
              className="eng-correlation-chart"
              onSelect={(p) =>
                pairs[p.dataIndex] && setSelectedPair(pairs[p.dataIndex])
              }
            />
          ) : (
            <Empty
              title="매칭된 Fab / EDS 쌍 없음"
              detail="현재 구간·설비·Recipe·측정 시차 조건 결과 0건"
            />
          )}
          <div className="eng-strata">
            {groups.map((g) => (
              <span key={g.recipe}>
                <i
                  style={{
                    background: g.recipe.endsWith('A') ? '#3b8697' : '#c77a63',
                  }}
                />
                {g.recipe} · n={g.n} · r={g.r?.toFixed(3) ?? 'N/A'}
              </span>
            ))}
          </div>
        </div>
        <aside className="eng-pair-inspector" aria-label="선택 Wafer 상세">
          <div className="eng-inspector-heading">
            <h3>Wafer detail</h3>
            <span>
              {selectedIndex < 0 ? '0' : selectedIndex + 1} / {pairs.length}
            </span>
            <button
              className="icon-button"
              title="이전 Wafer"
              disabled={selectedIndex <= 0}
              onClick={() => setSelectedPair(pairs[selectedIndex - 1])}
            >
              <ChevronLeft size={16} />
            </button>
            <button
              className="icon-button"
              title="다음 Wafer"
              disabled={!pairs.length || selectedIndex >= pairs.length - 1}
              onClick={() => setSelectedPair(pairs[selectedIndex + 1])}
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <select
            aria-label="상관분석 Wafer 선택"
            value={selectedIndex < 0 ? '' : selectedIndex}
            disabled={!pairs.length}
            onChange={(e) => {
              if (e.target.value !== '' && pairs[Number(e.target.value)])
                setSelectedPair(pairs[Number(e.target.value)]);
            }}
          >
            <option value="" disabled>
              선택 Wafer 없음
            </option>
            {pairs.map((row, index) => (
              <option key={pairKey(row)} value={index}>
                {row.lotId} / {row.waferId}
              </option>
            ))}
          </select>
          {selectedPair ? (
            <>
              <dl className="eng-pair-facts" aria-live="polite">
                <div>
                  <dt>Fab 온도</dt>
                  <dd>
                    {selectedPair.value.toFixed(2)} <small>°C</small>
                  </dd>
                </div>
                <div>
                  <dt>EDS Yield</dt>
                  <dd>
                    {selectedPair.yieldPct.toFixed(2)} <small>%</small>
                  </dd>
                </div>
                <div>
                  <dt>설비</dt>
                  <dd>{selectedPair.equipment}</dd>
                </div>
                <div>
                  <dt>Recipe</dt>
                  <dd>{selectedPair.recipe}</dd>
                </div>
                <div>
                  <dt>Fab · UTC</dt>
                  <dd>{time(selectedPair.timestamp)}</dd>
                </div>
                <div>
                  <dt>EDS · UTC</dt>
                  <dd>{time(selectedPair.measuredAt)}</dd>
                </div>
              </dl>
              <div className="eng-wafer-actions">
                <button
                  className="outline-button"
                  onClick={() => navigate('map', undefined, 'wafer')}
                >
                  <Focus size={14} />
                  Wafer map
                </button>
                <button
                  className="outline-button"
                  onClick={() => navigate('map', undefined, 'sem')}
                >
                  SEM
                  <ArrowUpRight size={14} />
                </button>
                <button
                  className="outline-button"
                  onClick={() => navigate('map', undefined, 'overlay')}
                >
                  Overlay
                  <ArrowUpRight size={14} />
                </button>
              </div>
              <small className="eng-inspector-source">
                합성 측정 · 실측 이미지 미연결
              </small>
            </>
          ) : (
            <div className="eng-pair-empty">
              <Focus size={26} />
              <span>선택된 관측점 없음</span>
              <small>Lot / Wafer · Fab / EDS</small>
            </div>
          )}
        </aside>
      </div>
      <div className="data-notice">
        <AlertTriangle size={15} />
        <span>
          {summary.reason ||
            '관측점은 Wafer 단위입니다. 같은 Lot의 상관과 Recipe·설비 차이를 통제한 인과 추정은 아닙니다.'}
        </span>
      </div>
      <div className="eng-table-wrap">
        <table className="eng-table">
          <thead>
            <tr>
              <th>Lot / Wafer</th>
              <th>Fab °C</th>
              <th>EDS %</th>
              <th>시차</th>
              <th>설비 / Recipe</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((row) => (
              <tr
                key={pairKey(row)}
                onClick={() => setSelectedPair(row)}
                className={
                  selectedPair?.lotId === row.lotId &&
                  selectedPair.waferId === row.waferId
                    ? 'selected'
                    : ''
                }
              >
                <td>
                  <button
                    className="eng-record-button"
                    aria-pressed={selectedPair === row}
                    onKeyDown={(event) => {
                      if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
                      event.preventDefault();
                      const index =
                        pairs.indexOf(row) +
                        (event.key === 'ArrowDown' ? 1 : -1);
                      if (!pairs[index]) return;
                      setSelectedPair(pairs[index]);
                      event.currentTarget
                        .closest('tbody')
                        ?.querySelectorAll<HTMLButtonElement>(
                          '.eng-record-button',
                        )
                        [index]?.focus();
                    }}
                  >
                    <strong>{row.lotId}</strong>
                    <small>
                      {row.waferId} · {time(row.timestamp)} UTC
                    </small>
                  </button>
                </td>
                <td>{row.value.toFixed(2)}</td>
                <td>{row.yieldPct.toFixed(2)}</td>
                <td>{row.lagDays.toFixed(1)} d</td>
                <td>
                  {row.equipment}
                  <small className="eng-cell-meta">{row.recipe}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
  ...props
}: ViewProps & {
  roomId: string;
  tab: Tab;
  reference: string;
  prepare: (question: string) => void;
  attachments: Attachment[];
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
  const match = useMemo(
    () =>
      matchFabYield(data.fab, data.yields, {
        from: data.trend[selection.start]?.timestamp || '',
        to: data.trend[selection.end]?.timestamp || '',
        equipment: selection.equipment || undefined,
        recipe: selection.recipe || undefined,
        maxLagDays: selection.maxLagDays,
      }),
    [data, selection],
  );
  const selectedPair =
    match.pairs.find((p) => pairKey(p) === selectedPairKey) || null;
  const summary = correlationSummary(match.pairs);
  const trendPinned = attachments.some(
    (item) => item.id === engineeringReference('trend', selection),
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
    <div className="engineering-workspace">
      {tab !== 'signals' && (
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
      {tab === 'signals' ? (
        <SignalList data={data} selection={selection} choose={choose} />
      ) : tab === 'trend' ? (
        <section className="detail-view trend-view">
          <div className="section-title">
            <div>
              <h2>{metrics[signal.metric].name} Trend</h2>
              <span>{signal.description}</span>
            </div>
            <div className="eng-inline-actions">
              <button
                className="outline-button"
                disabled={trendPinned}
                onClick={() =>
                  props.attach({
                    kind: 'trend',
                    id: engineeringReference('trend', selection),
                    label: `합성 ${metrics[signal.metric].name} · ${windowLabel}`,
                  })
                }
              >
                {trendPinned ? <Check size={15} /> : <Link2 size={15} />}
                {trendPinned ? '근거 선택됨' : '근거 선택'}
              </button>
              <button
                className="primary-button"
                onClick={() => props.navigate('correlation')}
              >
                <ScatterChart size={15} />
                Fab × EDS
                <ArrowRight size={14} />
              </button>
            </div>
          </div>
          <EngineeringTrend data={data} selection={selection} change={change} />
          <div className="eng-range">
            <label>
              구간 시작{' '}
              <output>{time(data.trend[selection.start].timestamp)}</output>
              <input
                aria-label="Trend 구간 시작"
                type="range"
                min={0}
                max={data.trend.length - 1}
                value={selection.start}
                onChange={(e) =>
                  change({
                    start: Math.min(Number(e.target.value), selection.end),
                  })
                }
              />
            </label>
            <label>
              구간 끝{' '}
              <output>{time(data.trend[selection.end].timestamp)}</output>
              <input
                aria-label="Trend 구간 끝"
                type="range"
                min={0}
                max={data.trend.length - 1}
                value={selection.end}
                onChange={(e) =>
                  change({
                    end: Math.max(Number(e.target.value), selection.start),
                  })
                }
              />
            </label>
            <button
              className="icon-button"
              title="감지 구간 복원"
              onClick={() =>
                change({ start: signal.startIndex, end: signal.endIndex })
              }
            >
              <RotateCcw size={17} />
            </button>
          </div>
          <div className="eng-summary-band">
            <div>
              <span>선택 관측점</span>
              <strong>{selection.end - selection.start + 1}</strong>
            </div>
            <div>
              <span>Fab 매칭 후보</span>
              <strong>
                {match.eligible}
                <small> wafers</small>
              </strong>
            </div>
            <div>
              <span>겹치는 설비 이벤트</span>
              <strong>
                {scopedDown.length}
                <small> events</small>
              </strong>
            </div>
          </div>
          <div className="eng-event-list">
            <h3>선택 구간의 설비 이벤트</h3>
            {scopedDown.map((event) => (
              <button
                key={event.id}
                onClick={() =>
                  props.navigate(
                    'production',
                    undefined,
                    `engineering:down:${event.id}`,
                  )
                }
              >
                <span className="eng-event-marker" />
                <time>{time(event.start)} UTC</time>
                <strong>{event.code}</strong>
                <span>{event.description}</span>
                <ArrowUpRight size={14} />
              </button>
            ))}
            {!scopedDown.length && (
              <p className="muted">선택 구간에 겹치는 합성 이벤트 없음</p>
            )}
          </div>
        </section>
      ) : tab === 'correlation' ? (
        <CorrelationView
          pairs={match.pairs}
          match={match}
          selection={selection}
          change={change}
          selectedPair={selectedPair}
          setSelectedPair={(pair) => setSelectedPairKey(pairKey(pair))}
          attach={props.attach}
          pinned={attachments.some(
            (item) => item.id === engineeringReference('corr', selection),
          )}
          navigate={props.navigate}
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
              <strong>{signal.title}</strong>의 선택 구간에서 Fab·EDS{' '}
              {summary.n}쌍이 매칭됐습니다.{' '}
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
                detail: `매칭 ${summary.n}/${match.eligible} · 누락 ${match.missing} · 중복 ${match.ambiguous} · 시차 제외 ${match.outsideLag}`,
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
                  `${props.workspace.incident.incident_number}의 ${signal.title} 항목을 분석해줘. 구간 ${windowLabel}, 설비 ${selection.equipment || '전체'}, Recipe ${selection.recipe || '전체'}, EDS 시차 최대 ${selection.maxLagDays}일. 합성 Fab·EDS 매칭 n=${summary.n}, r=${summary.r?.toFixed(3) ?? 'N/A'}. 회의록, 생산 재공, 설비 다운코드, SEM·Overlay 원본을 확인하고 사실·가설·판정 보류 사유를 구분해줘. 현재 UI의 계산값은 합성 예시이며 실제 원인 근거가 아니다.`,
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

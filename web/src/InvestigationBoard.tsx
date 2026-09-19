import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  RotateCcw,
  ShieldAlert,
} from 'lucide-react';
import { download, type Incident } from './api';
import { Chart } from './charts';
import type { ViewProps } from './Views';
import {
  pairKey,
  selectFabRows,
  type InvestigationSelection,
} from './engineeringAnalysis';
import type { EngineeringData, FabRow, Signal } from './engineeringData';
import { compositeWaferMaps, waferData, waferSeed } from './waferMaps';
import HistoricalCorrelation from './HistoricalCorrelation';
import './investigationBoard.css';

const gridId = 'synthetic-grid-v1';
const bins = ['#e3e8e7', '#8cbcaf', '#3c8978', '#e7af55', '#c55961'];
const frequencyColor = (percent: number) =>
  percent === 0
    ? '#e3e8e7'
    : percent < 25
      ? '#b2d9cf'
      : percent < 50
        ? '#57ac98'
        : percent < 75
          ? '#e7af55'
          : '#c55961';
const time = (value: string) => value.slice(5, 16).replace('T', ' ');

export default function InvestigationBoard({
  workspace,
  data,
  selection,
  change,
  choose,
  trend,
  focusedKey,
  onFocus,
  navigate,
  prepare,
  incidents,
}: ViewProps & {
  data: EngineeringData;
  selection: InvestigationSelection;
  change: (patch: Partial<InvestigationSelection>) => void;
  choose: (signal: Signal) => void;
  trend: ReactNode;
  focusedKey: string;
  onFocus: (row: FabRow) => void;
  prepare: (question: string) => void;
  incidents: Incident[];
}) {
  const incident = workspace.incident.incident_number;
  const signal = data.signals.find((row) => row.id === selection.signalId)!;
  const candidates = useMemo(
    () => selectFabRows(data, selection),
    [data, selection],
  );
  const from = data.trend[selection.start].timestamp;
  const to = data.trend[selection.end].timestamp;
  const events = data.changes.filter(
    (row) =>
      (!selection.equipment || row.equipment === selection.equipment) &&
      (!selection.recipe || !row.recipe || row.recipe === selection.recipe),
  );
  const wip = data.wip.filter(
    (row) =>
      (!selection.equipment || row.equipment === selection.equipment) &&
      (!selection.recipe || row.recipe === selection.recipe),
  );
  const downtime = data.downtime.filter(
    (row) =>
      (!selection.equipment || row.equipment === selection.equipment) &&
      row.start <= to &&
      row.end >= from,
  );
  const related = incidents.filter((row) => row.incident_number !== incident);
  const scope = JSON.stringify([
    selection.signalId,
    selection.start,
    selection.end,
    selection.equipment,
    selection.recipe,
  ]);
  const allKeys = useMemo(() => new Set(candidates.map(pairKey)), [candidates]);
  const [checkedState, setCheckedState] = useState(() => ({
    scope,
    keys: allKeys,
  }));
  const checked = checkedState.scope === scope ? checkedState.keys : allKeys;
  const setChecked = (
    update: Set<string> | ((previous: Set<string>) => Set<string>),
  ) =>
    setCheckedState((previous) => ({
      scope,
      keys:
        typeof update === 'function'
          ? update(previous.scope === scope ? previous.keys : allKeys)
          : update,
    }));
  const [threshold, setThreshold] = useState(0);
  const [die, setDie] = useState<[number, number] | null>(null);
  useEffect(() => {
    setCheckedState((previous) =>
      previous.scope === scope ? previous : { scope, keys: allKeys },
    );
  }, [scope, allKeys]);
  useEffect(() => setDie(null), [scope]);
  const focused =
    candidates.find((row) => pairKey(row) === focusedKey) || candidates[0];
  const maps = useMemo(
    () =>
      candidates.map((row) => ({
        lotId: row.lotId,
        waferId: row.waferId,
        gridId,
        dies: waferData(waferSeed(incident, row.lotId, row.waferId)),
      })),
    [incident, candidates],
  );
  const selectedMaps = maps.filter((row) => checked.has(pairKey(row)));
  const composite = useMemo(
    () => compositeWaferMaps(selectedMaps),
    [maps, checked],
  );
  const current = maps.find(
    (row) => focused && pairKey(row) === pairKey(focused),
  );
  const overlayB = maps.find(
    (row) => current && pairKey(row) !== pairKey(current),
  );
  const selectedDie =
    die && composite.dies.find((row) => row.x === die[0] && row.y === die[1]);
  const mapOption = (combined: boolean) => ({
    animation: false,
    grid: { left: '5%', right: '5%', top: '5%', bottom: '5%' },
    xAxis: { type: 'value', min: -18, max: 18, show: false },
    yAxis: { type: 'value', min: -18, max: 18, show: false },
    tooltip: {
      renderMode: 'richText',
      formatter: (p: { value: number[] }) =>
        combined
          ? `Die (${p.value[0]}, ${p.value[1]})\nFlag ${p.value[2]} / ${p.value[3]} (${p.value[4].toFixed(1)}%) · 합성`
          : `Die (${p.value[0]}, ${p.value[1]})\nBin ${p.value[2]} · 합성`,
    },
    series: [
      {
        type: 'scatter',
        symbol: 'rect',
        symbolSize: 3.3,
        data: combined
          ? composite.dies.map((row) => ({
              value: [row.x, row.y, row.flags, row.observed, row.percent],
              itemStyle: {
                color:
                  row.percent < threshold
                    ? '#f3f5f4'
                    : frequencyColor(row.percent),
              },
            }))
          : (current?.dies || []).map((row) => ({
              value: [row.x, row.y, row.bin],
              itemStyle: { color: bins[row.bin] },
            })),
      },
    ],
  });

  const exportComposite = () =>
    download(
      `${incident}-composite-map.json`,
      JSON.stringify(
        {
          synthetic: true,
          incident,
          selection,
          gridId,
          selected: selectedMaps.map(({ lotId, waferId }) => ({
            lotId,
            waferId,
          })),
          scope: candidates.map(({ lotId, waferId, timestamp }) => ({
            lotId,
            waferId,
            timestamp,
          })),
          flagRule: 'bin >= 3',
          denominator: 'observed wafers per coordinate; missing is not pass',
          physicalAlignmentVerified: false,
          displayThresholdPercent: threshold,
          ...composite,
        },
        null,
        2,
      ),
      'application/json',
    );
  const expand = (
    label: string,
    tab: Parameters<ViewProps['navigate']>[0],
    mode?: string,
  ) => (
    <button
      className="icon-button"
      title={label}
      onClick={() => navigate(tab, undefined, mode)}
    >
      <ArrowUpRight size={14} />
    </button>
  );
  return (
    <div className="investigation-board">
      <div className="board-scope">
        <strong>{signal.title}</strong>
        <span>{signal.step}</span>
        <label>
          후속 설비
          <select
            aria-label="조사 설비"
            value={selection.equipment}
            onChange={(event) => change({ equipment: event.target.value })}
          >
            <option value="">전체</option>
            {[...new Set(data.fab.map((row) => row.equipment))].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Recipe
          <select
            aria-label="조사 Recipe"
            value={selection.recipe}
            onChange={(event) => change({ recipe: event.target.value })}
          >
            <option value="">전체</option>
            {[...new Set(data.fab.map((row) => row.recipe))].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <span className="board-scope-window">
          {time(from)} ~ {time(to)} UTC
        </span>
        <span className="board-demo">SYNTHETIC · 실측 / LLM 미연결</span>
      </div>
      <div className="board-grid">
        <section
          className="board-panel board-signals"
          aria-label="이상감지 선택 목록"
        >
          <header>
            <h2>이상감지</h2>
            <span>{data.signals.length} items</span>
            {expand('이상감지 상세', 'signals')}
          </header>
          <div className="board-signal-list">
            {data.signals.map((row) => (
              <button
                key={row.id}
                className={row.id === signal.id ? 'selected' : ''}
                aria-pressed={row.id === signal.id}
                onClick={() => choose(row)}
              >
                <AlertTriangle size={13} className={row.severity} />
                <strong>{row.title}</strong>
                <small>
                  {row.equipment} · {row.recipe}
                </small>
              </button>
            ))}
          </div>
        </section>
        <section
          className="board-panel board-trend"
          aria-label="선택 이상감지 Trend"
        >
          <header>
            <h2>{signal.title} Trend</h2>
            <span>
              {signal.equipment} · 시작{' '}
              {time(data.trend[signal.onsetIndex].timestamp)}
            </span>
            <button
              className="icon-button"
              title="감지 구간 복원"
              onClick={() =>
                change({ start: signal.startIndex, end: signal.endIndex })
              }
            >
              <RotateCcw size={14} />
            </button>
          </header>
          <div className="board-trend-body">{trend}</div>
          <div className="board-range">
            <label>
              시작
              <input
                aria-label="Trend 구간 시작"
                type="range"
                min={0}
                max={data.trend.length - 1}
                value={selection.start}
                onChange={(event) =>
                  change({
                    start: Math.min(+event.target.value, selection.end),
                  })
                }
              />
              <output>{time(from)}</output>
            </label>
            <label>
              끝
              <input
                aria-label="Trend 구간 끝"
                type="range"
                min={0}
                max={data.trend.length - 1}
                value={selection.end}
                onChange={(event) =>
                  change({
                    end: Math.max(+event.target.value, selection.start),
                  })
                }
              />
              <output>{time(to)}</output>
            </label>
          </div>
        </section>
        <section
          className="board-panel board-correlation"
          aria-label="과거 완료 이력 상관분석"
        >
          <HistoricalCorrelation
            workspace={workspace}
            data={data}
            selection={selection}
            compact
          />
        </section>
        <section
          className="board-panel board-cohort"
          aria-label="선택 구간 Wafer 목록"
        >
          <header>
            <h2>Wafer</h2>
            <output aria-live="polite">
              {checked.size} / {candidates.length}
            </output>
            <input
              type="checkbox"
              aria-label="Wafer 전체 선택"
              checked={
                !!candidates.length && checked.size === candidates.length
              }
              ref={(node) => {
                if (node)
                  node.indeterminate =
                    checked.size > 0 && checked.size < candidates.length;
              }}
              disabled={!candidates.length}
              onChange={(event) =>
                setChecked(
                  new Set(event.target.checked ? candidates.map(pairKey) : []),
                )
              }
            />
          </header>
          <div className="board-wafer-list">
            {candidates.map((row) => (
              <div
                key={pairKey(row)}
                className={
                  focused && pairKey(focused) === pairKey(row) ? 'selected' : ''
                }
              >
                <input
                  type="checkbox"
                  aria-label={`${row.lotId} / ${row.waferId} 합성 포함`}
                  checked={checked.has(pairKey(row))}
                  onChange={(event) =>
                    setChecked((previous) => {
                      const next = new Set(previous);
                      if (event.target.checked) next.add(pairKey(row));
                      else next.delete(pairKey(row));
                      return next;
                    })
                  }
                />
                <button
                  title={`${row.lotId} / ${row.waferId} 개별 Map`}
                  aria-pressed={!!focused && pairKey(focused) === pairKey(row)}
                  onClick={() => onFocus(row)}
                >
                  <span>
                    {row.lotId} <strong>{row.waferId}</strong>
                  </span>
                  <small>{row.timestamp.slice(11, 16)} · Fab</small>
                </button>
              </div>
            ))}
          </div>
          {!candidates.length && (
            <p className="board-empty">해당 구간 Wafer 없음</p>
          )}
          <footer>
            현재 Fab · EDS 대기
            <br />
            등록 범위 ≠ 사고 영향 범위
          </footer>
        </section>
        <section
          className="board-panel board-single-map"
          aria-label="개별 Wafer Map"
        >
          <header>
            <h2>Wafer Map</h2>
            <span>합성</span>
            {expand('개별 Map 상세', 'map', 'wafer')}
          </header>
          <div className="board-map-label">
            {focused
              ? `${focused.lotId} / ${focused.waferId}`
              : '선택 Wafer 없음'}
          </div>
          <div className="board-map-stage">
            {focused ? (
              <Chart
                option={mapOption(false)}
                className="board-map-canvas"
                label="선택 Wafer 개별 Map"
              />
            ) : (
              <p className="board-empty">Map 없음</p>
            )}
          </div>
          <footer>
            <i style={{ background: bins[3] }} />
            Bin 3 <i style={{ background: bins[4] }} />
            Bin 4 · Flag ≥ 3
          </footer>
        </section>
        <section
          className="board-panel board-composite"
          aria-label="선택 Wafer 합성 Map"
        >
          <header>
            <h2>합성 Map</h2>
            <output>{composite.waferCount} Wafers</output>
            <button
              className="icon-button"
              title="합성 Map 데이터 다운로드"
              disabled={!composite.waferCount}
              onClick={exportComposite}
            >
              <ArrowDownToLine size={14} />
            </button>
          </header>
          <div className="board-map-label">동일 Die 좌표 · Flag / 관측 수</div>
          <div className="board-map-stage">
            {composite.waferCount ? (
              <Chart
                option={mapOption(true)}
                className="board-map-canvas"
                label={`선택 ${composite.waferCount}개 Wafer 합성 Map`}
                onSelect={(p) => setDie([p.value[0], p.value[1]])}
              />
            ) : (
              <p className="board-empty">합성 대상 없음</p>
            )}
          </div>
          <div className="board-frequency">
            <span>0</span>
            {[0, 12, 37, 62, 100].map((n) => (
              <i key={n} style={{ background: frequencyColor(n) }} />
            ))}
            <span>100%</span>
            <input
              type="range"
              aria-label="합성 Map 최소 Flag 빈도"
              title="최소 Flag 빈도"
              min={0}
              max={100}
              step={5}
              value={threshold}
              onChange={(event) => setThreshold(+event.target.value)}
            />
            <output>{threshold}%</output>
          </div>
          <footer aria-live="polite">
            {selectedDie
              ? `Die (${selectedDie.x},${selectedDie.y}) · ${selectedDie.flags}/${selectedDie.observed} (${selectedDie.percent.toFixed(0)}%)`
              : `${composite.dies.filter((row) => row.flags > 0).length} Flag 좌표 · 정렬 미검증`}
          </footer>
        </section>
        <section
          className="board-panel board-changes"
          aria-label="Recipe와 전산 변경 이력"
        >
          <header>
            <h2>변경 이력</h2>
            <span>합성</span>
          </header>
          <div className="board-change-onset">
            <strong>{time(data.trend[signal.onsetIndex].timestamp)}</strong>
            <span>변동 시작 · 합성 기준</span>
          </div>
          <div className="board-records">
            {events.map((event) => (
              <div key={event.id} title={event.sourceRef}>
                <time>{time(event.timestamp)}</time>
                <b>
                  {event.kind === 'recipe' ? 'Recipe 변경' : '전산 Rule 변경'}
                </b>
                <span>
                  {event.before} → {event.after}
                </span>
                <small>
                  {event.equipment}
                  {event.timestamp < from
                    ? ' · 선택 이전'
                    : event.timestamp > to
                      ? ' · 선택 이후'
                      : ' · 구간 내'}
                </small>
              </div>
            ))}
          </div>
          <footer>선후 관계만 표시 · 원인 미확정</footer>
        </section>
        <section
          className="board-panel board-images"
          aria-label="SEM과 Overlay"
        >
          <header>
            <h2>SEM · Overlay</h2>
            <span>합성</span>
            {expand('SEM Overlay 상세', 'map', 'sem')}
          </header>
          <div className="board-image-pair">
            <figure>
              <img
                src="/assets/synthetic-sem.png"
                alt="AI 생성 합성 SEM 예시, 실제 선택 Wafer 이미지 아님"
              />
              <figcaption>SEM · AI 생성 예시</figcaption>
            </figure>
            <figure>
              <Chart
                option={{
                  ...mapOption(true),
                  series: [
                    {
                      type: 'scatter',
                      symbol: 'rect',
                      symbolSize: 2.5,
                      data: (current?.dies || []).map((row) => [row.x, row.y]),
                      itemStyle: { color: '#dfe6e4' },
                    },
                    {
                      type: 'scatter',
                      symbol: 'rect',
                      symbolSize: 2.7,
                      data: (current?.dies || [])
                        .filter((row) => row.bin >= 3)
                        .map((row) => [row.x, row.y]),
                      itemStyle: { color: '#548db2' },
                    },
                    {
                      type: 'scatter',
                      symbol: 'circle',
                      symbolSize: 2,
                      data: (overlayB?.dies || [])
                        .filter((row) => row.bin >= 3)
                        .map((row) => [row.x, row.y]),
                      itemStyle: { color: '#ce7886', opacity: 0.65 },
                    },
                  ],
                  tooltip: { show: false },
                }}
                className="board-overlay-canvas"
                label="합성 두 Wafer Overlay 예시"
              />
              <figcaption>
                Overlay · {maps.length > 1 ? '2' : maps.length} Maps
              </figcaption>
            </figure>
          </div>
          <div className="board-image-source">
            {focused
              ? `선택 ${focused.waferId} · 실측 연결 없음`
              : '선택 Wafer 없음'}
          </div>
          <footer>물리 좌표 · 배율 · 정렬 미검증</footer>
        </section>
        <section
          className="board-panel board-production"
          aria-label="생산 재공과 다운코드"
        >
          <header>
            <h2>생산 · 재공 · 다운코드</h2>
            <span>MES / FDC 미연결</span>
            {expand('생산 상세', 'production')}
          </header>
          <div className="board-production-columns">
            <div>
              <h3>
                WIP <span>{wip.length} Lots · 스냅샷</span>
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Lot</th>
                    <th>Status</th>
                    <th>Queue</th>
                  </tr>
                </thead>
                <tbody>
                  {wip.map((row) => (
                    <tr key={row.lotId}>
                      <td>{row.lotId}</td>
                      <td>
                        <span
                          className={`board-status ${row.status.toLowerCase()}`}
                        >
                          {row.status}
                        </span>
                      </td>
                      <td>{row.queueHours.toFixed(1)}h</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!wip.length && <p className="board-empty">일치 재공 없음</p>}
            </div>
            <div>
              <h3>
                설비 다운 <span>{downtime.length}건 · 구간 내</span>
              </h3>
              <div className="board-downcodes">
                {downtime.map((row) => (
                  <div key={row.id}>
                    <time>{row.start.slice(11, 16)}</time>
                    <b>{row.code}</b>
                    <span>{row.category}</span>
                  </div>
                ))}
              </div>
              {!downtime.length && (
                <p className="board-empty">겹치는 다운코드 없음</p>
              )}
            </div>
          </div>
          <footer>
            합성 운전 기록 · 현재 공정 상태 및 Hold/Release 조치 미실행
          </footer>
        </section>
        <section
          className="board-panel board-documents"
          aria-label="Inform Note 회의록과 이전 이력"
        >
          <header>
            <h2>Inform Note · 회의록</h2>
            <span>{workspace.meetings.length} chunks</span>
            {expand('문서 원문 상세', 'inform')}
          </header>
          <div className="board-inform-state">
            <span>Eng’r Inform</span>
            <strong>원본 미연결</strong>
            <span>승인 · 변경 근거 확인 대기</span>
          </div>
          <div className="board-doc-list">
            {workspace.meetings.map((meeting) => (
              <article key={meeting.chunk_id} title={meeting.text}>
                <strong>{meeting.title}</strong>
                <span>
                  {meeting.meeting_date} · {meeting.version} · 합성 DB
                </span>
                <p>{meeting.text}</p>
              </article>
            ))}
          </div>
          {!workspace.meetings.length && (
            <p className="board-empty">현재 범위 회의록 없음</p>
          )}
          <footer>
            이전 사고 {related.length}건 ·{' '}
            {related
              .slice(0, 2)
              .map((row) => row.incident_number)
              .join(' · ') || '등록 없음'}
          </footer>
        </section>
        <section
          className="board-panel board-assessment"
          aria-label="설명과 판정"
        >
          <header>
            <h2>설명 · 판정</h2>
            <span>LLM 미연결</span>
          </header>
          <div className="board-verdict">
            <ShieldAlert size={17} />
            <strong>원인 판정 보류</strong>
          </div>
          <p>
            현재 Fab <b>{candidates.length} Wafers</b> · EDS 대기
            <br />
            Yield 비교: 같은 Item의 과거 완료 이력
          </p>
          <p>
            변경 {events.length}건 · 다운코드 {downtime.length}건<br />
            시간상 연관 · 원인 근거 미확인
          </p>
          <div className="board-agent-state">
            <strong>로컬 요약 · 실제 LLM 판정 없음</strong>
          </div>
          <button
            className="board-prepare"
            onClick={() =>
              prepare(
                `${incident} / ${signal.title}: ${time(from)}~${time(to)} UTC, ${selection.equipment || '전체 설비'}, ${selection.recipe || '전체 Recipe'}. 현재 Wafer는 Fab 상태라 EDS 결과 없음. 같은 Item의 과거 완료 이력으로 Fab-Yield 상관관계를 비교하고 Recipe/전산 변경, Inform Note, 회의록, 생산 기록을 수집해 사실과 가설을 구분해줘. 현재 화면은 합성 데이터이며 원인 근거가 아니다.`,
              )
            }
          >
            <Check size={13} />
            채팅 질문 준비
          </button>
        </section>
      </div>
    </div>
  );
}

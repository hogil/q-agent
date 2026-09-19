import { Fragment, useMemo, useState } from 'react';
import {
  Activity,
  ChevronDown,
  ChevronUp,
  Download,
  Factory,
  FilePlus2,
  Link2,
  Search,
  Server,
} from 'lucide-react';
import { download, type Attachment, type Workspace } from './api';
import { ProductionView } from './Sources';
import type { EngineeringData } from './engineeringData';
import type { Tab } from './Views';
import './operations.css';

type OperationsSubview = 'wip' | 'downtime' | 'systems';
type WipStatus = 'ALL' | 'RUN' | 'WAIT' | 'HOLD';

type OperationsProps = {
  workspace: Workspace;
  data: EngineeringData;
  equipment: string;
  recipe?: string;
  selectEquipment: (id: string) => void;
  attach: (item: Attachment) => void;
  navigate: (tab: Tab, document?: string) => void;
  selectedDocument: string | null;
  selectDocument: (id: string | null) => void;
  reference?: string;
  window?: { from: string; to: string };
};

function minutesBetween(start: string, end: string) {
  const delta = new Date(end).getTime() - new Date(start).getTime();
  return Number.isFinite(delta) && delta >= 0
    ? Math.round(delta / 60000)
    : null;
}

function csvCell(value: unknown) {
  return `"${String(value ?? '').replaceAll('"', '""')}"`;
}

function formatMinutes(value: number | null) {
  return value === null ? '시간 미상' : `${value.toLocaleString()} min`;
}

export function OperationsView({
  workspace,
  data,
  equipment,
  recipe = '',
  selectEquipment,
  attach,
  navigate,
  selectedDocument,
  selectDocument,
  reference = '',
  window,
}: OperationsProps) {
  const [subview, setSubview] = useState<OperationsSubview>(
    reference.startsWith('engineering:down:') ? 'downtime' : 'wip',
  );
  const [wipStatus, setWipStatus] = useState<WipStatus>('ALL');
  const [search, setSearch] = useState('');
  const [expandedDowntime, setExpandedDowntime] = useState<string | null>(
    reference.startsWith('engineering:down:')
      ? reference.slice('engineering:down:'.length)
      : null,
  );
  const query = search.trim().toLowerCase();

  const equipmentOptions = useMemo(
    () =>
      Array.from(
        new Set([
          ...data.wip.map((row) => row.equipment),
          ...data.downtime.map((row) => row.equipment),
        ]),
      ).sort(),
    [data],
  );

  const wipRows = useMemo(
    () =>
      data.wip.filter((row) => {
        const matchesEquipment = !equipment || row.equipment === equipment;
        const matchesStatus = wipStatus === 'ALL' || row.status === wipStatus;
        const matchesSearch =
          !query ||
          `${row.lotId} ${row.step} ${row.equipment} ${row.recipe} ${row.holdCode}`
            .toLowerCase()
            .includes(query);
        return (
          matchesEquipment &&
          matchesStatus &&
          matchesSearch &&
          (!recipe || row.recipe === recipe)
        );
      }),
    [data.wip, equipment, query, wipStatus, recipe],
  );

  const downtimeRows = useMemo(
    () =>
      data.downtime.filter((row) => {
        const matchesEquipment = !equipment || row.equipment === equipment;
        const matchesSearch =
          !query ||
          `${row.id} ${row.equipment} ${row.code} ${row.category} ${row.description}`
            .toLowerCase()
            .includes(query);
        const matchesWindow =
          !window || (row.start <= window.to && row.end >= window.from);
        return matchesEquipment && matchesSearch && matchesWindow;
      }),
    [data.downtime, equipment, query, window?.from, window?.to],
  );

  const wipLotCount = new Set(wipRows.map((row) => row.lotId)).size;
  const waferCount = wipRows.reduce((sum, row) => sum + row.wafers, 0);
  const holdCount = wipRows.filter((row) => row.status === 'HOLD').length;
  const downtimeMinutes = downtimeRows.reduce(
    (sum, row) =>
      sum +
      (minutesBetween(
        window && window.from > row.start ? window.from : row.start,
        window && window.to < row.end ? window.to : row.end,
      ) || 0),
    0,
  );

  function exportRows() {
    if (subview === 'wip') {
      const header = [
        'lotId',
        'step',
        'equipment',
        'recipe',
        'status',
        'wafers',
        'queueHours',
        'holdCode',
      ];
      const body = wipRows.map((row) => [
        row.lotId,
        row.step,
        row.equipment,
        row.recipe,
        row.status,
        row.wafers,
        row.queueHours,
        row.holdCode,
      ]);
      download(
        `${workspace.incident.incident_number}-wip.csv`,
        '\uFEFF' +
          [header, ...body]
            .map((line) => line.map(csvCell).join(','))
            .join('\n'),
        'text/csv;charset=utf-8',
      );
      return;
    }
    const header = [
      'id',
      'equipment',
      'start',
      'end',
      'code',
      'category',
      'description',
    ];
    const body = downtimeRows.map((row) => [
      row.id,
      row.equipment,
      row.start,
      row.end,
      row.code,
      row.category,
      row.description,
    ]);
    download(
      `${workspace.incident.incident_number}-equipment-events.csv`,
      '\uFEFF' +
        [header, ...body].map((line) => line.map(csvCell).join(',')).join('\n'),
      'text/csv;charset=utf-8',
    );
  }

  return (
    <section className="detail-view operations-view">
      <div className="section-title operations-heading">
        <div>
          <h2>Production context</h2>
          <span>
            합성 재공 스냅샷 {workspace.incident.occurred_at.slice(0, 10)} ·
            다운코드 구간 UTC
          </span>
        </div>
        <div className="operations-heading-actions">
          <span className="status-tag amber">합성 운전 기록</span>
          <button
            className="icon-button"
            title="현재 운영 조회 CSV 다운로드"
            disabled={subview === 'systems'}
            onClick={exportRows}
          >
            <Download size={17} />
          </button>
        </div>
      </div>

      <div className="data-notice operations-notice">
        <Factory size={15} />
        <span>MES · FDC · SPC · Recipe 원본 미연결</span>
        <span className="synthetic-label">읽기 전용</span>
      </div>

      <div className="operations-toolbar">
        <label className="select-field">
          Equipment
          <select
            aria-label="설비 선택"
            value={equipment}
            onChange={(event) => selectEquipment(event.target.value)}
          >
            <option value="">전체 설비</option>
            {equipmentOptions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="inline-search small operations-search">
          <Search size={14} />
          <input
            aria-label="재공 및 다운코드 검색"
            placeholder="Lot · code · detail 검색"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>

      <div
        className="segmented operations-tabs"
        aria-label="Production context subview"
      >
        <button
          className={subview === 'wip' ? 'selected' : ''}
          onClick={() => setSubview('wip')}
        >
          재공 <small>{wipRows.length}</small>
        </button>
        <button
          className={subview === 'downtime' ? 'selected' : ''}
          onClick={() => setSubview('downtime')}
        >
          설비 다운코드 <small>{downtimeRows.length}</small>
        </button>
        <button
          className={subview === 'systems' ? 'selected' : ''}
          onClick={() => setSubview('systems')}
        >
          사내 시스템
        </button>
      </div>

      {subview === 'systems' ? (
        <ProductionView
          workspace={workspace}
          attach={attach}
          navigate={navigate}
          selectedDocument={selectedDocument}
          selectDocument={selectDocument}
        />
      ) : (
        <>
          <div className="metric-strip operations-metrics">
            <div>
              <span>재공 Lot</span>
              <strong>{wipLotCount}</strong>
            </div>
            <div>
              <span>재공 Wafer</span>
              <strong>{waferCount}</strong>
            </div>
            <div>
              <span>HOLD Lot</span>
              <strong>{holdCount}</strong>
            </div>
            <div>
              <span>다운타임 · 선택 구간</span>
              <strong>{formatMinutes(downtimeMinutes)}</strong>
            </div>
          </div>

          {subview === 'wip' ? (
            <section className="operations-section">
              <div className="section-title">
                <div>
                  <h3>Work in process</h3>
                  <span>
                    필터 결과 {wipRows.length} rows · Lot 중복 제거 KPI
                  </span>
                </div>
                <div
                  className="segmented compact-segmented"
                  aria-label="재공 상태"
                >
                  {(['ALL', 'RUN', 'WAIT', 'HOLD'] as WipStatus[]).map(
                    (status) => (
                      <button
                        key={status}
                        className={wipStatus === status ? 'selected' : ''}
                        onClick={() => setWipStatus(status)}
                      >
                        {status}
                      </button>
                    ),
                  )}
                </div>
              </div>
              <div className="table-scroll operations-table-scroll">
                <table className="operations-table">
                  <thead>
                    <tr>
                      <th>Lot ID</th>
                      <th>Step</th>
                      <th>Equipment</th>
                      <th>Recipe</th>
                      <th>Status</th>
                      <th>Wafer</th>
                      <th>Queue</th>
                      <th>Hold code</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {!wipRows.length && (
                      <tr>
                        <td colSpan={9} className="operations-empty">
                          현재 조건의 재공 없음
                        </td>
                      </tr>
                    )}
                    {wipRows.map((row) => (
                      <tr key={`${row.lotId}-${row.step}-${row.equipment}`}>
                        <td className="mono">{row.lotId}</td>
                        <td>{row.step}</td>
                        <td className="mono">{row.equipment}</td>
                        <td className="mono">{row.recipe}</td>
                        <td>
                          <span
                            className={`status-tag ${row.status === 'HOLD' ? 'amber' : row.status === 'RUN' ? 'green' : ''}`}
                          >
                            {row.status}
                          </span>
                        </td>
                        <td>{row.wafers}</td>
                        <td>{row.queueHours.toFixed(1)} h</td>
                        <td className="mono">{row.holdCode || '—'}</td>
                        <td>
                          <button
                            className="icon-button"
                            title="재공 행을 검토 대상에 추가"
                            onClick={() =>
                              attach({
                                kind: 'request',
                                id: `engineering:wip:${row.lotId}`,
                                label: `합성 재공 ${row.lotId}`,
                              })
                            }
                          >
                            <FilePlus2 size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : (
            <section className="operations-section">
              <div className="section-title">
                <div>
                  <h3>Equipment downtime codes</h3>
                  <span>
                    다운코드 {downtimeRows.length}건 · 행의 Duration은 이벤트
                    전체 시간
                  </span>
                </div>
                <Activity size={18} />
              </div>
              <div className="table-scroll operations-table-scroll">
                <table className="operations-table downtime-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Duration</th>
                      <th>Equipment</th>
                      <th>Code</th>
                      <th>Category</th>
                      <th>Detail</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {!downtimeRows.length && (
                      <tr>
                        <td colSpan={7} className="operations-empty">
                          현재 구간의 다운코드 없음
                        </td>
                      </tr>
                    )}
                    {downtimeRows.map((row) => {
                      const expanded = expandedDowntime === row.id;
                      const duration = minutesBetween(row.start, row.end);
                      return (
                        <Fragment key={row.id}>
                          <tr
                            key={row.id}
                            className={expanded ? 'expanded-row' : ''}
                          >
                            <td>
                              <button
                                className="operations-expand"
                                onClick={() =>
                                  setExpandedDowntime(expanded ? null : row.id)
                                }
                              >
                                <span>{row.start.replace('T', ' ')}</span>
                                {expanded ? (
                                  <ChevronUp size={14} />
                                ) : (
                                  <ChevronDown size={14} />
                                )}
                              </button>
                            </td>
                            <td>{formatMinutes(duration)}</td>
                            <td className="mono">{row.equipment}</td>
                            <td className="mono">{row.code}</td>
                            <td>{row.category}</td>
                            <td>{row.description}</td>
                            <td>
                              <button
                                className="icon-button"
                                title="다운코드를 검토 대상에 추가"
                                onClick={() =>
                                  attach({
                                    kind: 'request',
                                    id: `engineering:down:${row.id}`,
                                    label: `합성 다운코드 ${row.code}`,
                                  })
                                }
                              >
                                <Link2 size={15} />
                              </button>
                            </td>
                          </tr>
                          {expanded && (
                            <tr
                              key={`${row.id}-detail`}
                              className="operations-detail-row"
                            >
                              <td
                                className="operations-expanded-cell"
                                colSpan={7}
                              >
                                <div>
                                  <span>Record source</span>
                                  <code>
                                    synthetic://equipment-events/{row.id}
                                  </code>
                                  <span>종료 시각</span>
                                  <strong>{row.end.replace('T', ' ')}</strong>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}

      <div className="operations-footer">
        <Server size={14} />
        <span>
          조회 범위: {workspace.incident.incident_number} ·{' '}
          {equipment || '전체 설비'} · {recipe || '전체 Recipe'} · as of{' '}
          {workspace.as_of}
        </span>
      </div>
    </section>
  );
}

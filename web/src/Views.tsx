import { useMemo, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  ChevronRight,
  FileText,
  Link2,
  Search,
  SlidersHorizontal,
  Table2,
  X,
} from 'lucide-react';
import { download, type Attachment, type Meeting, type Workspace } from './api';
import { TrendChart, WaferChart, waferData, type Die } from './charts';

export type Tab =
  | 'signals'
  | 'correlation'
  | 'assessment'
  | 'overview'
  | 'trend'
  | 'map'
  | 'inform'
  | 'data'
  | 'production'
  | 'history'
  | 'review';
export type ViewProps = {
  workspace: Workspace;
  attach: (item: Attachment) => void;
  navigate: (tab: Tab, document?: string, mode?: string) => void;
  initialWafer?: { lotId: string; waferId: string };
  selectedDocument: string | null;
  selectDocument: (id: string | null) => void;
};
type Props = ViewProps;
export const incidentSeed = (workspace: Workspace) =>
  Number(workspace.incident.incident_number.split('-').at(-1)) || 1;

function SectionTitle({
  title,
  note,
  action,
}: {
  title: string;
  note?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        {note && <span>{note}</span>}
      </div>
      {action}
    </div>
  );
}
function Legend({ map = false }: { map?: boolean }) {
  return (
    <div className="legend">
      {map ? (
        <>
          <span>
            <i className="swatch neutral" />
            Reference
          </span>
          <span>
            <i className="swatch amber" />
            Edge flag
          </span>
          <span>
            <i className="swatch coral" />
            High flag
          </span>
        </>
      ) : (
        <>
          <span>
            <i className="line-swatch" />
            측정값
          </span>
          <span>
            <i className="line-swatch dashed" />
            기준값
          </span>
          <span>
            <i className="swatch light-amber" />
            관찰 구간
          </span>
        </>
      )}
    </div>
  );
}

export function Overview(props: Props) {
  const { workspace: w, attach, navigate } = props;
  const seed = incidentSeed(w);
  const latestMeeting = [...w.meetings].sort(
    (a, b) =>
      b.meeting_date.localeCompare(a.meeting_date) ||
      b.version.localeCompare(a.version, undefined, { numeric: true }),
  )[0];
  return (
    <div className="overview">
      <div className="stat-band">
        <div>
          <span>등록 Lot</span>
          <strong>
            {w.lots.length}
            <small> lots</small>
          </strong>
          <p>사고 DB 연결 목록</p>
        </div>
        <div>
          <span>등록 Wafer</span>
          <strong>
            {w.wafers.length}
            <small> wafers</small>
          </strong>
          <p>영향 범위 완전성 미확인</p>
        </div>
        <div>
          <span>회의록 근거</span>
          <strong>
            {w.meetings.length}
            <small> sources</small>
          </strong>
          <p>{w.as_of} 기준 승인 문서</p>
        </div>
      </div>
      <section className="record-comparison" aria-label="DB와 회의록 기록 비교">
        <div>
          <div className="section-title">
            <h2>사고 DB 기록</h2>
            <span
              className={`status-tag ${w.incident.confirmed_cause ? 'green' : 'amber'}`}
            >
              {w.incident.confirmed_cause ? '확정 원인 필드' : '원인 미확정'}
            </span>
          </div>
          <p>
            {w.incident.confirmed_cause ||
              w.incident.analysis_detail ||
              '분석 기록 없음'}
          </p>
          <button className="text-button" onClick={() => navigate('data')}>
            DB 원문
            <ArrowUpRight size={14} />
          </button>
        </div>
        <div>
          <div className="section-title">
            <h2>최근 승인 회의록</h2>
            <FileText size={16} />
          </div>
          {latestMeeting ? (
            <>
              <p>{latestMeeting.text}</p>
              <button
                className="text-button"
                onClick={() => navigate('inform', latestMeeting.chunk_id)}
              >
                {latestMeeting.meeting_date} · {latestMeeting.version}
                <ArrowUpRight size={14} />
              </button>
            </>
          ) : (
            <p className="muted">현재 범위의 승인 회의록 없음</p>
          )}
        </div>
      </section>
      <div className="visual-band">
        <section className="overview-trend">
          <SectionTitle
            title="Process trend"
            note="공정 온도 · °C"
            action={
              <button
                className="icon-button"
                title="Trend 확대"
                onClick={() => navigate('trend')}
              >
                <ArrowUpRight size={17} />
              </button>
            }
          />
          <div className="plot-meta">
            <span className="synthetic-label">합성 시각화</span>
            <span>30 days</span>
          </div>
          <TrendChart
            seed={seed}
            compact
            onSelect={(label) =>
              attach({
                kind: 'trend',
                id: `trend-${seed}-${label}`,
                label: `합성 Trend ${label}`,
              })
            }
          />
          <Legend />
        </section>
        <section className="overview-map">
          <SectionTitle
            title="Wafer map"
            note={
              w.wafers[0]
                ? `${w.wafers[0].lot_id} / ${w.wafers[0].wafer_id}`
                : '등록 Wafer 없음'
            }
            action={
              <button
                className="icon-button"
                title="Map 확대"
                onClick={() => navigate('map')}
              >
                <ArrowUpRight size={17} />
              </button>
            }
          />
          <div className="plot-meta">
            <span className="synthetic-label">합성 시각화</span>
            <span>Die-level</span>
          </div>
          <WaferChart
            seed={seed}
            compact
            onSelect={(die) =>
              attach({
                kind: 'map',
                id: `die-${seed}-${die.x}-${die.y}`,
                label: `합성 Die (${die.x}, ${die.y})`,
              })
            }
          />
          <Legend map />
        </section>
      </div>
      <section className="findings-section">
        <SectionTitle
          title="후속 확인"
          note="사고 DB의 미완료 기록"
          action={
            <button className="text-button" onClick={() => navigate('data')}>
              DB 보기 <ChevronRight size={14} />
            </button>
          }
        />
        <div className="finding-row">
          <span className="record-index">01</span>
          <div>
            <h3>조회 범위</h3>
            <p>
              {w.incident.remaining ||
                '등록 목록과 실제 영향 범위의 완전성을 별도로 확인해야 합니다.'}
            </p>
          </div>
          <span className="status-tag">확인 필요</span>
        </div>
      </section>
      <section className="sources-section">
        <SectionTitle
          title="관련 Inform · 회의록"
          note={`${w.meetings.length} sources`}
          action={
            <button className="text-button" onClick={() => navigate('inform')}>
              전체 보기 <ChevronRight size={14} />
            </button>
          }
        />
        {w.meetings.length ? (
          w.meetings.slice(0, 3).map((item) => (
            <button
              className="source-row"
              key={item.chunk_id}
              onClick={() => {
                navigate('inform', item.chunk_id);
              }}
            >
              <span className="document-icon">
                <FileText size={18} />
              </span>
              <span className="source-body">
                <strong>{item.title}</strong>
                <span>
                  {item.meeting_date} <b>·</b> {item.version} <b>·</b> 회의록
                </span>
              </span>
              <span className="source-type">승인</span>
              <ArrowUpRight size={16} />
            </button>
          ))
        ) : (
          <Empty
            title="조회된 회의록이 없습니다"
            detail="기준일·승인 상태·선택 사고 범위에 맞는 근거가 없습니다."
          />
        )}
      </section>
    </div>
  );
}

export function MapView({ workspace: w, attach, initialWafer }: Props) {
  const [index, setIndex] = useState(() =>
    Math.max(
      0,
      w.wafers.findIndex(
        (row) =>
          row.lot_id === initialWafer?.lotId &&
          row.wafer_id === initialWafer?.waferId,
      ),
    ),
  );
  const [filter, setFilter] = useState('all');
  const [die, setDie] = useState<Die | null>(null);
  const wafer = w.wafers[index];
  const seed = incidentSeed(w) + index;
  const dice = useMemo(() => waferData(seed), [seed]);
  if (!wafer)
    return (
      <Empty
        title="등록된 Wafer가 없습니다"
        detail="현재 사고 범위에서 Wafer 연결을 확인할 수 없습니다."
      />
    );
  return (
    <section className="detail-view map-detail">
      <SectionTitle title="Wafer map" note="공간 패턴 확인" />
      <div className="view-toolbar">
        <label className="select-field">
          Wafer{' '}
          <select
            aria-label="Wafer 선택"
            value={index}
            onChange={(e) => {
              setIndex(Number(e.target.value));
              setDie(null);
            }}
          >
            {w.wafers.map((item, i) => (
              <option key={`${item.lot_id}-${item.wafer_id}`} value={i}>
                {item.lot_id} / {item.wafer_id}
              </option>
            ))}
          </select>
        </label>
        <div className="segmented">
          <button
            className={filter === 'all' ? 'selected' : ''}
            onClick={() => setFilter('all')}
          >
            전체
          </button>
          <button
            className={filter === 'flagged' ? 'selected' : ''}
            onClick={() => setFilter('flagged')}
          >
            Flag
          </button>
        </div>
      </div>
      <div className="data-notice">
        <span className="synthetic-label">합성 시각화</span>
        <span>등록 Wafer ID에 연결한 예시 Map · 실제 불량 분포 아님</span>
      </div>
      <div className="map-stage">
        <div className="map-axis-label top">Y+</div>
        <WaferChart seed={seed} filter={filter} onSelect={setDie} />
        <div className="notch" />
        <span className="map-axis-label bottom">NOTCH · 6 O'CLOCK</span>
      </div>
      <Legend map />
      <div className="selection-bar">
        <div>
          <span className="eyebrow">SELECTED DIE</span>
          <strong>
            {die
              ? `X ${die.x} / Y ${die.y} · ${die.bin >= 3 ? 'Edge flag' : 'Reference'}`
              : '선택된 Die 없음'}
          </strong>
        </div>
        <button
          className="outline-button"
          onClick={() =>
            attach({
              kind: 'map',
              id: `${wafer.lot_id}/${wafer.wafer_id}${die ? `/${die.x}/${die.y}` : ''}`,
              label: `합성 Map ${wafer.wafer_id}${die ? ` · Die (${die.x}, ${die.y})` : ''}`,
            })
          }
        >
          <Link2 size={15} />
          검토 대상에 추가
        </button>
      </div>
      <div className="metric-strip">
        <div>
          <span>합성 Die</span>
          <strong>{dice.length}</strong>
        </div>
        <div>
          <span>합성 Flag</span>
          <strong>{dice.filter((d) => d.bin >= 3).length}</strong>
        </div>
        <div>
          <span>등록 상태</span>
          <strong className="text-value">{wafer.status}</strong>
        </div>
      </div>
    </section>
  );
}

export function InformView({
  workspace: w,
  attach,
  selectedDocument,
  selectDocument,
}: Props) {
  const [search, setSearch] = useState('');
  const visible = w.meetings.filter((m) =>
    `${m.title} ${m.text}`.toLowerCase().includes(search.toLowerCase()),
  );
  const selected =
    visible.find((m) => m.chunk_id === selectedDocument) || visible[0];
  return (
    <section className="detail-view inform-detail">
      <SectionTitle
        title="Inform & meeting notes"
        note={`${w.meetings.length}개 승인 근거 · ${w.as_of} 기준`}
      />
      <div className="inline-search">
        <Search size={16} />
        <input
          aria-label="Inform 검색"
          placeholder="제목 또는 내용 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            className="icon-button"
            title="검색 초기화"
            onClick={() => setSearch('')}
          >
            <X size={14} />
          </button>
        )}
      </div>
      <div className="document-options">
        {visible.map((m) => (
          <button
            key={m.chunk_id}
            onClick={() => selectDocument(m.chunk_id)}
            className={selected?.chunk_id === m.chunk_id ? 'selected' : ''}
          >
            <FileText size={15} />
            <span>{m.title}</span>
            <small>{m.version}</small>
          </button>
        ))}
      </div>
      {!visible.length ? (
        <Empty
          title="일치하는 근거가 없습니다"
          detail={
            search
              ? '다른 검색어로 검색해 주세요.'
              : '현재 사고의 승인 문서를 찾지 못했습니다.'
          }
        />
      ) : (
        selected && <Document item={selected} attach={attach} />
      )}
    </section>
  );
}

function Document({
  item,
  attach,
}: {
  item: Meeting;
  attach: (item: Attachment) => void;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <article className="document-reader" key={item.chunk_id}>
      <div className="document-topline">
        <span className="document-category">
          MEETING NOTE <span>합성 원문</span>
        </span>
        <span className="status-tag green">
          <Check size={12} />
          Approved
        </span>
      </div>
      <h2>{item.title}</h2>
      <div className="document-metadata">
        <span>{item.meeting_date}</span>
        <span>{item.version}</span>
        <span>{item.meeting_id}</span>
      </div>
      <div className="document-rule" />
      <h3>검토 내용</h3>
      <p className="original-text">{item.text}</p>
      <div className="source-reference">
        <span>Source reference</span>
        <code>{item.source_ref}</code>
        <span>Chunk ID</span>
        <code>{item.chunk_id}</code>
      </div>
      <div className="document-actions">
        <button
          className="primary-button"
          onClick={() =>
            attach({
              kind: 'inform',
              id: item.chunk_id,
              label: `${item.title} · ${item.version}`,
            })
          }
        >
          <Link2 size={15} />
          검토 대상에 추가
        </button>
        <button
          className="text-button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(
                `${item.title}\n${item.text}\n${item.source_ref}`,
              );
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? '복사됨' : '원문 복사'}
        </button>
      </div>
      <p className="reader-note">
        기존 합성 회의록의 원문입니다. 사내 Inform 서비스는 아직 연결되지
        않았습니다.
      </p>
    </article>
  );
}

export function DataView({ workspace: w, attach }: Props) {
  const [type, setType] = useState<'lots' | 'wafers'>('lots');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState(1);
  const rows = [...(type === 'lots' ? w.lots : w.wafers)]
    .filter((r) =>
      Object.values(r).join(' ').toLowerCase().includes(search.toLowerCase()),
    )
    .sort((a, b) => sort * a.lot_id.localeCompare(b.lot_id));
  return (
    <section className="detail-view">
      <SectionTitle
        title="Incident data"
        note="사고 DB · 읽기 전용"
        action={
          <button
            className="icon-button"
            title="조회 결과 JSON 다운로드"
            onClick={() =>
              download(
                `${w.incident.incident_number}-${type}.json`,
                JSON.stringify(
                  {
                    synthetic: true,
                    incident: w.incident.incident_number,
                    rows,
                  },
                  null,
                  2,
                ),
              )
            }
          >
            <ArrowDownToLine size={17} />
          </button>
        }
      />
      <div className="incident-facts">
        <div>
          <span>사고번호</span>
          <strong>{w.incident.incident_number}</strong>
        </div>
        <div>
          <span>부서 / 라인</span>
          <strong>
            {w.incident.department} / {w.incident.line}
          </strong>
        </div>
        <div>
          <span>발생일</span>
          <strong>{w.incident.occurred_at?.slice(0, 10)}</strong>
        </div>
        <div>
          <span>확정 원인 기록</span>
          <strong>{w.incident.confirmed_cause || '미확정'}</strong>
        </div>
      </div>
      <div className="view-toolbar">
        <div className="segmented">
          <button
            className={type === 'lots' ? 'selected' : ''}
            onClick={() => setType('lots')}
          >
            Lot <small>{w.lots.length}</small>
          </button>
          <button
            className={type === 'wafers' ? 'selected' : ''}
            onClick={() => setType('wafers')}
          >
            Wafer <small>{w.wafers.length}</small>
          </button>
        </div>
        <div className="inline-search small">
          <Search size={14} />
          <input
            aria-label="조회 목록 검색"
            placeholder="목록 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>
                <button onClick={() => setSort(-sort)}>
                  Lot ID <SlidersHorizontal size={12} />
                </button>
              </th>
              <th>{type === 'lots' ? 'Product' : 'Wafer ID'}</th>
              <th>Status</th>
              <th>
                <span className="sr-only">첨부</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.lot_id}-${i}`}>
                <td className="mono">{r.lot_id}</td>
                <td className="mono">
                  {'product_code' in r ? r.product_code : r.wafer_id}
                </td>
                <td>
                  <span
                    className={`status-tag ${r.status === 'REGISTERED' ? 'green' : 'amber'}`}
                  >
                    {r.status}
                  </span>
                </td>
                <td>
                  <button
                    className="icon-button"
                    title="이 행을 검토 대상에 추가"
                    onClick={() =>
                      attach({
                        kind: 'data',
                        id:
                          r.lot_id + ('wafer_id' in r ? `/${r.wafer_id}` : ''),
                        label:
                          r.lot_id +
                          ('wafer_id' in r ? ` / ${r.wafer_id}` : ''),
                      })
                    }
                  >
                    <Link2 size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <Empty
          title="조회 결과 없음"
          detail="현재 검색 조건에 맞는 등록 항목이 없습니다."
        />
      )}
      <div className="table-footer">
        <span>{rows.length} rows</span>
        <span>등록 목록의 완전성: unknown</span>
      </div>
      <div className="data-notice bottom-notice">
        <Table2 size={15} />
        <span>
          등록 수와 사고 영향 수는 다를 수 있습니다. 수량을 임의 보정하지
          않습니다.
        </span>
      </div>
    </section>
  );
}

export function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <Search size={25} strokeWidth={1.3} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

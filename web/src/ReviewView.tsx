import { useState } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  Columns2,
  FileText,
  Link2,
  NotebookPen,
  X,
} from 'lucide-react';
import { download, type Attachment, type Workspace } from './api';
import { Empty } from './Views';
import { makeEngineeringData, matchFabYield } from './engineeringData';
import {
  correlationSummary,
  parseEngineeringReference,
} from './engineeringAnalysis';

const kinds: Record<string, string> = {
  inform: '회의록',
  data: '사고 DB',
  trend: 'Trend',
  map: 'Map',
  image: 'SEM',
  history: '비교 사고',
  request: '미연결 원본',
};

function resolveSource(item: Attachment, workspace: Workspace) {
  const sameScope = item.incident_number === workspace.incident.incident_number;
  if (sameScope && item.id.startsWith('engineering:')) {
    const data = makeEngineeringData(workspace);
    const selection = parseEngineeringReference(item.id, data);
    const down = data.downtime.find(
      (row) => item.id === `engineering:down:${row.id}`,
    );
    const wip = data.wip.find(
      (row) => item.id === `engineering:wip:${row.lotId}`,
    );
    const matched = selection
      ? matchFabYield(data.fab, data.yields, {
          from: data.trend[selection.start].timestamp,
          to: data.trend[selection.end].timestamp,
          equipment: selection.equipment || undefined,
          recipe: selection.recipe || undefined,
          maxLagDays: selection.maxLagDays,
        })
      : null;
    const payload =
      matched && selection
        ? {
            synthetic: true,
            selection,
            from: data.trend[selection.start].timestamp,
            to: data.trend[selection.end].timestamp,
            ...(item.id.startsWith('engineering:corr:')
              ? {
                  matching: matched,
                  summary: correlationSummary(matched.pairs),
                }
              : {
                  trace: data.trend.slice(selection.start, selection.end + 1),
                }),
          }
        : down || wip;
    if (payload)
      return {
        reference: item,
        source: 'synthetic://engineering/v1',
        date: workspace.incident.occurred_at,
        version: 'fixture-v1',
        text: JSON.stringify(payload, null, 2),
      };
  }
  const meeting =
    sameScope && item.kind === 'inform'
      ? workspace.meetings.find((m) => m.chunk_id === item.id)
      : undefined;
  const lot =
    sameScope && item.kind === 'data'
      ? workspace.lots.find((l) => l.lot_id === item.id)
      : undefined;
  const wafer =
    sameScope && item.kind === 'data'
      ? workspace.wafers.find((w) => `${w.lot_id}/${w.wafer_id}` === item.id)
      : undefined;
  const isIncident =
    sameScope &&
    item.kind === 'data' &&
    item.id === workspace.incident.incident_id;
  return {
    reference: item,
    source:
      meeting?.source_ref ||
      (lot || wafer || isIncident ? '합성 사고 DB' : null),
    date: meeting?.meeting_date || null,
    version: meeting?.version || null,
    text:
      meeting?.text ||
      (lot
        ? `Lot: ${lot.lot_id}\nProduct: ${lot.product_code}\nStatus: ${lot.status}`
        : wafer
          ? `Lot: ${wafer.lot_id}\nWafer: ${wafer.wafer_id}\nStatus: ${wafer.status}`
          : isIncident
            ? `분석 기록: ${workspace.incident.analysis_detail || '없음'}\n확정 원인: ${workspace.incident.confirmed_cause || '미확정'}`
            : null),
  };
}

function SourcePreview({
  item,
  workspace,
  open,
}: {
  item: Attachment;
  workspace: Workspace;
  open: (item: Attachment) => void;
}) {
  const source = resolveSource(item, workspace);
  const syntheticImage =
    item.kind === 'image' &&
    ['synthetic-sem', 'synthetic-sem-roi-01'].includes(item.id);
  return (
    <article className="evidence-preview">
      <div className="evidence-preview-heading">
        <span className="status-tag">
          {item.id.startsWith('engineering:')
            ? '합성 분석 근거'
            : kinds[item.kind] || '참조'}
        </span>
        <button
          className="icon-button"
          title={`${item.label} 원본 화면 열기`}
          onClick={() => open(item)}
        >
          <ArrowUpRight size={17} />
        </button>
      </div>
      <h3>{item.label}</h3>
      <dl className="evidence-metadata">
        <dt>사고</dt>
        <dd>{item.incident_number || '미지정'}</dd>
        <dt>Reference</dt>
        <dd>{item.id}</dd>
        {source.date && (
          <>
            <dt>문서 기준일</dt>
            <dd>
              {source.date} · {source.version}
            </dd>
          </>
        )}
      </dl>
      {source.text ? (
        <>
          <p className="evidence-original">{source.text}</p>
          <div className="evidence-source">
            <Link2 size={13} />
            <span>{source.source}</span>
          </div>
        </>
      ) : syntheticImage ? (
        <>
          <img
            className="evidence-image"
            src="/assets/synthetic-sem.png"
            alt="AI 생성 합성 SEM, 실제 측정 근거 아님"
          />
          <p className="evidence-limitation">
            AI 생성 이미지 · 실측값 및 사고 관계 미검증
          </p>
        </>
      ) : (
        <p className="evidence-limitation">
          {item.kind === 'request'
            ? '원본 서비스 미연결. 조회 요청만 선택돼 있습니다.'
            : ['trend', 'map'].includes(item.kind)
              ? '합성 시각화의 선택 참조입니다. 실제 측정 원본은 연결되지 않았습니다.'
              : '현재 조회 범위에 이 참조의 원문이 없습니다. 사고 범위를 확인한 뒤 원본 화면에서 조회해야 합니다.'}
        </p>
      )}
    </article>
  );
}

export default function ReviewView({
  workspace,
  attachments,
  question,
  notes,
  setNotes,
  open,
  remove,
  storageError,
}: {
  workspace: Workspace;
  attachments: Attachment[];
  question: string;
  notes: string;
  setNotes: (value: string) => void;
  open: (item: Attachment) => void;
  remove: (index: number) => void;
  storageError: boolean;
}) {
  const [selected, setSelected] = useState(0);
  const [compare, setCompare] = useState(false);
  const [otherIndex, setOtherIndex] = useState(1);
  const index = Math.min(selected, Math.max(0, attachments.length - 1));
  const item = attachments[index];
  const other =
    attachments[otherIndex] && otherIndex !== index
      ? otherIndex
      : index === 0
        ? 1
        : 0;
  return (
    <section className="detail-view review-view">
      <div className="section-title">
        <div>
          <h2>근거 검토</h2>
          <span>
            {workspace.incident.incident_number} · {attachments.length}개 선택 ·
            수동 검토
          </span>
        </div>
        <button
          className="icon-button"
          title="검토 기록 JSON 다운로드"
          disabled={!attachments.length && !notes.trim() && !question.trim()}
          onClick={() =>
            download(
              `${workspace.incident.incident_number}-review.json`,
              JSON.stringify(
                {
                  synthetic: true,
                  review_type: 'manual_notes_not_agent_verdict',
                  incident: workspace.incident.incident_number,
                  cutoff: workspace.as_of,
                  exported_at: new Date().toISOString(),
                  prepared_question: question,
                  notes,
                  sources: attachments.map((a) => resolveSource(a, workspace)),
                },
                null,
                2,
              ),
            )
          }
        >
          <ArrowDownToLine size={18} />
        </button>
      </div>
      <div className="evidence-toolbar">
        <span>{attachments.length} references</span>
        <button
          className={`icon-button ${compare ? 'selected' : ''}`}
          title="근거 나란히 비교"
          aria-pressed={compare}
          disabled={attachments.length < 2}
          onClick={() => setCompare(!compare)}
        >
          <Columns2 size={18} />
        </button>
      </div>
      {!item ? (
        <Empty
          title="선택된 근거 없음"
          detail="현재 검토 목록이 비어 있습니다."
        />
      ) : (
        <>
          <div className="evidence-list">
            {attachments.map((a, i) => (
              <div
                className={i === index ? 'selected' : ''}
                key={`${a.kind}-${a.id}-${a.incident_number}`}
              >
                <button
                  className="evidence-select"
                  aria-pressed={i === index}
                  onClick={() => setSelected(i)}
                >
                  <FileText size={15} />
                  <span>
                    <strong>{a.label}</strong>
                    <small>
                      {kinds[a.kind] || a.kind} ·{' '}
                      {a.incident_number || '미지정'}
                    </small>
                  </span>
                </button>
                <button
                  className="icon-button"
                  title={`${a.label} 검토 목록에서 제거`}
                  onClick={() => remove(i)}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
          {compare && attachments.length > 1 && (
            <label className="select-field evidence-compare-select">
              비교 대상
              <select
                aria-label="비교할 근거"
                value={other}
                onChange={(e) => setOtherIndex(Number(e.target.value))}
              >
                {attachments.map(
                  (a, i) =>
                    i !== index && (
                      <option key={i} value={i}>
                        {a.label}
                      </option>
                    ),
                )}
              </select>
            </label>
          )}
          <div
            className={`evidence-preview-grid ${compare && attachments.length > 1 ? 'comparison' : ''}`}
          >
            <SourcePreview item={item} workspace={workspace} open={open} />
            {compare && attachments[other] && attachments.length > 1 && (
              <SourcePreview
                item={attachments[other]}
                workspace={workspace}
                open={open}
              />
            )}
          </div>
        </>
      )}
      <div className="review-notes">
        <div className="section-title">
          <h2>
            <NotebookPen size={16} />
            검토 메모
          </h2>
          <span role="status" className={storageError ? 'save-error' : ''}>
            {storageError ? '브라우저 저장 실패' : '이 브라우저에 저장'}
          </span>
        </div>
        <textarea
          aria-label="검토 메모"
          value={notes}
          maxLength={8000}
          placeholder="확인한 내용 / 남은 질문"
          onChange={(e) => setNotes(e.target.value)}
        />
        <div className="notes-footer">
          <span>사용자 메모 · Agent 판정 아님</span>
          <span>{notes.length.toLocaleString()} / 8,000</span>
        </div>
      </div>
    </section>
  );
}

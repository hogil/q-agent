import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  Check,
  FlaskConical,
  Loader2,
  RotateCcw,
  X,
} from 'lucide-react';
import { api } from './api';
import type { AnalysisContext } from './engineeringAnalysis';

type Pair = { lot_id: string; wafer_id: string };
type Event = {
  event_id: string;
  item: string;
  score: number;
  threshold: number;
  context: AnalysisContext;
  state: string;
  action_status: string;
  error: string | null;
  created_at: string;
  result: { room_id?: string; comparison_status?: string } | null;
};
type Status = {
  worker_running: boolean;
  events: Event[];
  image_tools: Record<
    'sem' | 'overlay',
    {
      configured: boolean;
      connection_verified: boolean;
      synthetic_model?: boolean;
    }
  >;
};
const states: Record<string, string> = {
  queued: '조회 대기',
  analyzing: '합성 DB 조회 중',
  review_required: '검토 요청',
  failed: '조회 실패',
  below_threshold: '기준 미달',
  acknowledged: '검토 확인',
  rejected: '검토 기각',
};
const actions: Record<string, string> = {
  requested: '검토 대기',
  acknowledged: '확인됨',
  rejected: '기각됨',
  not_requested: '요청 없음',
  failed: '요청 실패',
};

export default function DetectionFlow({
  context,
  a,
  b,
}: {
  context: AnalysisContext;
  a?: Pair;
  b?: Pair;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    let active = true,
      timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const data = await api<Status>('/monitoring');
        if (active) {
          setStatus(data);
          setError('');
        }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (active) timer = setTimeout(poll, 2000);
      }
    }
    void poll();
    return () => {
      active = false;
      alive.current = false;
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    if (expanded) dialog.current?.showModal();
  }, [expanded]);
  const events =
    status?.events.filter(
      (e) =>
        e.item === context.item &&
        e.context.incident_number === context.incident_number,
    ) || [];
  const latest = events[0];
  async function command(path: string, body: unknown) {
    setBusy(true);
    setError('');
    try {
      await api(path, 'POST', body);
      const data = await api<Status>('/monitoring');
      if (alive.current) setStatus(data);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  return (
    <>
      <div className="detection-flow" aria-label="감지와 자동 분석 상태">
        <Activity size={13} />
        <strong>감지 · 분석 · 조치</strong>
        <span className="unavailable">감지 모델 미연결</span>
        <span>
          SEM{' '}
          {status?.image_tools.sem.configured
            ? status.image_tools.sem.synthetic_model
              ? '합성 학습 모델'
              : status.image_tools.sem.connection_verified
                ? '연결 확인'
                : '설정됨 · 연결 미검증'
            : '미연결'}
        </span>
        <span>
          Overlay{' '}
          {status?.image_tools.overlay.configured
            ? status.image_tools.overlay.synthetic_model
              ? '합성 학습 모델'
              : status.image_tools.overlay.connection_verified
                ? '연결 확인'
                : '설정됨 · 연결 미검증'
            : '미연결'}
        </span>
        <span className="detection-current" aria-live="polite">
          {error ||
            (latest
              ? `${states[latest.state] || latest.state} · ${actions[latest.action_status] || latest.action_status}`
              : '감지 이벤트 없음')}
        </span>
        <span className="unavailable">생산 조치 미연결</span>
        <button
          className="icon-button"
          title="합성 감지 이벤트 1회 재생"
          disabled={busy || !status?.worker_running || !a || !b}
          onClick={() =>
            void command('/monitoring/replay', {
              context,
              comparison: { item: context.item, a, b },
            })
          }
        >
          {busy ? (
            <Loader2 className="spin" size={14} />
          ) : (
            <FlaskConical size={14} />
          )}
        </button>
        <button
          className="icon-button"
          title="감지·분석·조치 기록"
          onClick={() => setExpanded(true)}
        >
          <ArrowUpRight size={14} />
        </button>
      </div>
      {expanded && (
        <dialog
          ref={dialog}
          className="detection-dialog"
          aria-label="감지·분석·조치 기록"
          onCancel={() => setExpanded(false)}
          onClose={() => setExpanded(false)}
        >
          <header>
            <h2>{context.item} · 감지 이벤트</h2>
            <span>합성 이벤트 · DB 조회 · 생산 실행 없음</span>
            <button
              className="icon-button"
              title="감지 기록 닫기"
              onClick={() => setExpanded(false)}
            >
              <X size={18} />
            </button>
          </header>
          {error && <p role="alert">{error}</p>}
          <div className="detection-events">
            <table>
              <thead>
                <tr>
                  <th>시각</th>
                  <th>입력 점수 / 기준</th>
                  <th>조회 상태</th>
                  <th>조치</th>
                  <th>기록</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.event_id}>
                    <td title={event.event_id}>
                      {event.created_at.slice(5, 19).replace('T', ' ')} UTC
                    </td>
                    <td>
                      {event.score.toFixed(2)} / {event.threshold.toFixed(2)}
                    </td>
                    <td>
                      {states[event.state] || event.state}
                      {event.error && <small>{event.error}</small>}
                    </td>
                    <td>
                      {actions[event.action_status] || event.action_status}
                    </td>
                    <td>
                      <div className="detection-actions">
                        {event.result?.room_id && (
                          <a
                            href={`/?room=${encodeURIComponent(event.result.room_id)}&view=chat`}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="자동 조회 대화 열기"
                          >
                            <ArrowUpRight size={15} />
                          </a>
                        )}
                        {event.state === 'failed' && (
                          <button
                            className="icon-button"
                            title="실패 조회 재시도"
                            disabled={busy}
                            onClick={() =>
                              void command(
                                `/monitoring/${event.event_id}/retry`,
                                {},
                              )
                            }
                          >
                            <RotateCcw size={15} />
                          </button>
                        )}
                        {event.state === 'review_required' &&
                          event.action_status === 'requested' && (
                            <>
                              <button
                                className="icon-button"
                                title="검토 요청 확인 · 생산 실행 아님"
                                disabled={busy}
                                onClick={() =>
                                  void command(
                                    `/monitoring/${event.event_id}/decision`,
                                    { decision: 'acknowledge' },
                                  )
                                }
                              >
                                <Check size={15} />
                              </button>
                              <button
                                className="icon-button"
                                title="검토 요청 기각"
                                disabled={busy}
                                onClick={() =>
                                  void command(
                                    `/monitoring/${event.event_id}/decision`,
                                    { decision: 'reject' },
                                  )
                                }
                              >
                                <X size={15} />
                              </button>
                            </>
                          )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!events.length && <p>현재 Item의 감지 이벤트 없음</p>}
          </div>
          <footer>
            감지 이벤트는 사고 후보입니다. 현재 기록은 합성 이벤트 재생이며,
            모델 추론·사고 확정·Lot Hold·설비 정지·Recipe 변경은 실행하지
            않았습니다.
          </footer>
        </dialog>
      )}
    </>
  );
}

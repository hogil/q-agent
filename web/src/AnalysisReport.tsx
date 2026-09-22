import { useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight,
  LayoutDashboard,
  MessageSquare,
  X,
  ZoomIn,
} from 'lucide-react';
import type { AnalysisReportData, Workspace } from './api';
import './analysisReport.css';

const timestamp = (value: string) =>
  value
    ?.replace('T', ' ')
    .replace(/\.\d+/, '')
    .replace(/Z$|\+00:00$/, ' UTC');
const value = (number: number | null | undefined) =>
  number == null ? 'N/A' : number.toFixed(3);
const labels: Record<string, string> = {
  historical_match: '과거 사고 비교',
  check: '점검 권고',
  eds_followup: 'EDS 후속 확인',
};

export default function AnalysisReport({
  report,
  workspace,
  onBoard,
  onChat,
}: {
  report: AnalysisReportData;
  workspace: Workspace | null;
  onBoard: () => void;
  onChat: () => void;
}) {
  const [selected, setSelected] = useState<
    AnalysisReportData['images'][number] | null
  >(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const model =
    report.trace.find((row) => row.role === 'answer')?.model || 'LLM';
  useEffect(() => {
    if (selected) dialog.current?.showModal();
  }, [selected]);
  return (
    <main className="startup-report">
      <header className="report-header">
        <div>
          <span className="report-brand">Q-Agent</span>
          <h1>불량 분석 결과</h1>
          <span className="report-incident">{report.incident_number}</span>
        </div>
        <nav aria-label="분석 결과 탐색">
          <button onClick={onBoard}>
            <LayoutDashboard size={15} />
            분석 보드
          </button>
          <button onClick={onChat}>
            <MessageSquare size={15} />
            추가 질문
            <ArrowUpRight size={13} />
          </button>
        </nav>
      </header>
      <div className="report-scope">
        <strong>
          {report.context.step} · {report.context.item}
        </strong>
        <span>
          {report.context.equipment || '전체 설비'} ·{' '}
          {report.context.wafers.length} Wafers
        </span>
        <span>
          {timestamp(report.context.from)} ~ {timestamp(report.context.to)}
        </span>
      </div>
      <div className="report-boundary">
        <strong>
          합성 사고 데이터 ·{' '}
          {report.status === 'partial' ? '부분 분석' : '분석 완료'}
        </strong>
        <span>저장된 LLM 분석 · 실측 불량 확정 및 조치 완료 아님</span>
        <time>{timestamp(report.completed_at)}</time>
      </div>
      <div className="report-columns">
        <section className="report-reason" aria-label="LLM 분석과 점검 계획">
          <h2>왜 불량을 의심하나</h2>
          <p className="report-model">
            {model} · Router → Tool → Judge → Answer
          </p>
          <div className="report-summary">{report.summary}</div>
          {!!report.trend.length && (
            <section
              className="report-measurements"
              aria-label="조회된 Trend 수치"
            >
              <h3>조회된 Trend 수치</h3>
              {report.trend.map((trend, index) => (
                <div key={index}>
                  <small>
                    변동 기준 {timestamp(trend.onset_summary.timestamp || '')}
                  </small>
                  <dl>
                    <div>
                      <dt>변동 전 평균</dt>
                      <dd>
                        {value(trend.onset_summary.before.mean)}{' '}
                        <small>{trend.unit}</small>
                      </dd>
                    </div>
                    <div>
                      <dt>변동 후 평균</dt>
                      <dd>
                        {value(trend.onset_summary.after.mean)}{' '}
                        <small>{trend.unit}</small>
                      </dd>
                    </div>
                    <div>
                      <dt>차이</dt>
                      <dd>
                        {value(trend.onset_summary.delta?.value)}{' '}
                        <small>{trend.unit}</small>
                      </dd>
                    </div>
                  </dl>
                  <small>
                    표본 {trend.onset_summary.before.count} →{' '}
                    {trend.onset_summary.after.count} · 규격 이탈 판정 아님
                  </small>
                </div>
              ))}
            </section>
          )}
          <section className="report-plan" aria-label="점검 및 EDS 계획">
            <h3>점검과 후속 확인</h3>
            {report.inspection_plan.map((row, index) => (
              <div className="report-plan-row" key={index}>
                <strong>{labels[row.kind] || row.kind}</strong>
                <div>
                  <b>{row.target}</b>
                  <p>{row.basis}</p>
                  <p>{row.comparison}</p>
                </div>
              </div>
            ))}
          </section>
          {!!report.limitations.length && (
            <section className="report-limitations">
              <h3>확인되지 않은 내용</h3>
              <ul>
                {report.limitations.map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ul>
            </section>
          )}
        </section>
        <section className="report-evidence" aria-label="분석 근거 이미지">
          <div className="report-mobile-summary">
            <h2>왜 불량을 의심하나</h2>
            <p>{report.summary}</p>
          </div>
          <h2>SEM 비교 · 과거 불량 참조</h2>
          {report.image_findings.some(
            (row) => row.status === 'INCOMPARABLE',
          ) && (
            <p className="report-image-status">
              SEM 정량 비교 불가 · INCOMPARABLE
            </p>
          )}
          <div className="report-images">
            {report.images.map((image) => {
              const asset = workspace?.raw?.sem_assets.find(
                (row) => row.id === image.id && row.src === image.src,
              );
              const wafer =
                asset &&
                workspace?.raw?.engineering.fab.find(
                  (row) =>
                    row.lotId === asset.lotId && row.waferId === asset.waferId,
                );
              const selected =
                asset &&
                report.context.wafers.some(
                  (row) =>
                    row.lot_id === asset.lotId &&
                    row.wafer_id === asset.waferId,
                );
              return (
                <figure key={image.id}>
                  <div className="report-image-heading">
                    <strong>
                      {image.kind === 'historical'
                        ? '과거 참조'
                        : selected
                          ? '선택 범위'
                          : '비교 대상'}
                    </strong>
                    <span>{image.id}</span>
                  </div>
                  <button
                    className="report-image-button"
                    title={`${image.label} 이미지 확대`}
                    onClick={() => setSelected(image)}
                  >
                    <img
                      src={image.src}
                      alt={`${image.label}: ${image.description}`}
                    />
                    <ZoomIn size={16} />
                  </button>
                  <figcaption>
                    <b>{image.label}</b>
                    {wafer && (
                      <span>
                        {wafer.equipment} · {wafer.step}
                      </span>
                    )}
                    <span>{image.description}</span>
                    <small>
                      {timestamp(image.time)}
                      <br />
                      합성 이미지
                    </small>
                  </figcaption>
                </figure>
              );
            })}
          </div>
          {!report.images.length && <p>이 분석에 저장된 근거 이미지 없음</p>}
          <details className="report-image-findings">
            <summary>
              이미지 Tool 결과 · {report.image_findings.length}회
            </summary>
            {report.image_findings.map((row, i) => (
              <section key={i}>
                <h3>
                  {row.model} · {row.status}
                </h3>
                <ul>
                  {[...row.findings, ...row.limitations].map((text, j) => (
                    <li key={j}>{text}</li>
                  ))}
                </ul>
              </section>
            ))}
          </details>
        </section>
      </div>
      {selected && (
        <dialog
          className="report-image-dialog"
          ref={dialog}
          aria-label="근거 이미지 확대"
          onCancel={() => setSelected(null)}
          onClick={(event) => {
            if (event.target === event.currentTarget) setSelected(null);
          }}
        >
          <header>
            <strong>{selected.label}</strong>
            <button
              title="이미지 닫기"
              aria-label="이미지 닫기"
              onClick={() => setSelected(null)}
            >
              <X size={19} />
            </button>
          </header>
          <img src={selected.src} alt={selected.description} />
          <p>{selected.description}</p>
          <small>{selected.provenance}</small>
        </dialog>
      )}
    </main>
  );
}

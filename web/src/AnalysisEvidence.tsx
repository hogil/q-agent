import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, X, ZoomIn } from 'lucide-react';
import type { AnalysisReportData, Workspace } from './api';
import type { AnalysisContext } from './engineeringAnalysis';
import { documentUrl } from './investigationData';
import AnalysisMaps from './AnalysisMaps';

type Media = {
  id: string;
  label: string;
  description: string;
  src?: string;
};

export default function AnalysisEvidence({
  report,
  context,
  workspace,
}: {
  report: AnalysisReportData;
  context: AnalysisContext;
  workspace: Workspace;
}) {
  const [preview, setPreview] = useState<Media | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (preview) dialog.current?.showModal();
  }, [preview]);
  const current = report.images.filter((image) => {
    const asset = workspace.raw?.sem_assets.find(
      (row) => row.id === image.id && row.src === image.src && (!row.item || row.item === context.item),
    );
    return (
      asset &&
      context.wafers.some(
        (row) => row.lot_id === asset.lotId && row.wafer_id === asset.waferId,
      )
    );
  });
  const cases = report.historical_cases || [];
  const retrievalEvidence = report.retrieval_evidence || [];
  const media: Media[] = [
    ...current
      .slice(0, 1)
      .map((image) => ({ ...image, label: `선택 SEM · ${image.label}` })),
    ...cases
      .slice(0, 1)
      .flatMap((item) => [
        ...(item.sem.src
          ? [
              {
                id: item.sem.id,
                src: item.sem.src,
                label: `과거 SEM · ${item.incident_number}`,
                description: item.sem.description,
              },
            ]
          : []),
      ]),
  ];
  return (
    <section className="agent-evidence" aria-label="현재 선택과 과거 사고 근거">
      {workspace.synthetic && <AnalysisMaps key={context.item} context={context} report={report} />}
      {!!media.length && (
        <div className="agent-evidence-media">
          {media.map((item) => (
            <figure key={item.id}>
              <button
                title={`${item.label} 확대`}
                aria-label={`${item.label} 확대`}
                onClick={() => setPreview(item)}
              >
                <img src={item.src} alt={item.description} />
                <ZoomIn className="agent-evidence-zoom" size={12} />
              </button>
              <figcaption>{item.label}</figcaption>
            </figure>
          ))}
        </div>
      )}
      {cases.map((item) => (
        <section className="agent-past-case" key={item.id}>
          <header>
            <strong>{item.incident_number}</strong>
            <time>{item.date.slice(0, 10)}</time>
            <a
              href={documentUrl(
                context.incident_number,
                'inform',
                item.inform_id,
              )}
              target="_blank"
              rel="noreferrer"
              title="과거 사고 Inform 원문"
            >
              <ArrowUpRight size={14} />
            </a>
          </header>
          <p>{item.sem.description}</p>
          <p>{item.overlay.description}</p>
          <dl>
            <div>
              <dt>일치 조건</dt>
              <dd>
                {item.step} · {item.equipment} · {item.item}
              </dd>
            </div>
            <div>
              <dt>당시 CD</dt>
              <dd>
                {item.cd.measurements
                  .map((point) => `${point.site} ${point.value}`)
                  .join(' / ')}{' '}
                {item.cd.unit}
              </dd>
            </div>
            <div>
              <dt>당시 EDS</dt>
              <dd>
                Yield {item.historical_eds.yieldPct}% · Bin3{' '}
                {item.historical_eds.bin3Pct}% · Bin4{' '}
                {item.historical_eds.bin4Pct}%
              </dd>
            </div>
          </dl>
          <small>조회된 과거 합성 기록 · 현재 EDS 및 동일 원인 확정 아님</small>
        </section>
      ))}
      {!!report.image_findings.length && (
        <details className="agent-model-evidence">
          <summary>
            이미지 모델 관측 ·{' '}
            {report.image_findings.map((row) => row.status).join(', ')}
          </summary>
          {report.image_findings.map((row, index) => (
            <div key={index}>
              <strong>{row.model}</strong>
              <ul>
                {[...row.findings, ...row.limitations].map((text, i) => (
                  <li key={i}>{text}</li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}
      {!!retrievalEvidence.length && (
        <details className="agent-model-evidence">
          <summary>문서 · MES 검색 근거 · {retrievalEvidence.length}건</summary>
          {retrievalEvidence.map(({ source, result }, index) => {
            const mes = source === 'search_mes_reference';
            const sourceLabel = source === 'search_engineer_notes'
              ? 'Eng’r Inform Note 검색'
              : source === 'search_internal_documents'
                ? '사내문서 검색'
                : mes ? 'MES 기준정보 검색' : source;
            const items = result.items || [];
            return (
              <section className="agent-past-case" key={`${source}-${index}`}>
                <strong>{sourceLabel} · Tool {source} · {result.status || '응답 상태 미상'}</strong>
                {(result.source_kind || result.retrieval_method) && (
                  <p>{result.source_kind || ''}{result.source_kind && result.retrieval_method ? ' · ' : ''}{result.retrieval_method || ''}</p>
                )}
                <p>기준일: {result.as_of || '미기록'}</p>
                <p>선택 사고 범위: {context.incident_number} · Tool 범위: {(result.incident_ids || []).join(', ') || '미기록'}</p>
                {result.historical_incident_ids?.length ? (
                  <p>과거 후보 범위: {result.historical_incident_ids.join(', ')}</p>
                ) : null}
                {result.status === 'NO_MATCH' && <p>일치 결과 없음 (NO_MATCH)</p>}
                {result.truncated && <p>일부 결과만 표시 · {result.candidate_count ?? items.length}건 후보</p>}
                {items.map((item, itemIndex) => (
                  <article key={`${item.record_id || item.chunk_id || item.document_id || item.kind || itemIndex}-${item.version || ''}`}>
                    <strong>{mes ? `${item.kind || 'MES record'} · ${item.name || item.record_id || '이름 미기록'}` : `${item.document_id || '문서'} · chunk ${item.chunk_id || 'ID 미기록'}`}</strong>
                    {!mes && item.text && <p>{item.text}</p>}
                    <p>출처: {item.source_ref || '미기록'}{item.locator ? ` · 위치: ${item.locator}` : ''}</p>
                    <p>버전: {item.version || '미기록'} · 사용 가능 시각: {item.available_at || '미기록'}</p>
                    {mes ? (
                      <>
                        <p>적용 상태: {typeof item.applicability === 'string' ? item.applicability : 'unknown'} · 범위 관계: {item.scope_relation || '미기록'} · 시간 상태: {item.time_status || '미기록'}</p>
                        <p>유효 기간: {item.effective_from || '시작 미상'} ~ {item.effective_to || '종료 미상'}</p>
                      </>
                    ) : (
                      <>
                        <p>관계: {item.relation || '미기록'} · 적용 상태: {item.applicability_status || '미검증'} · 문서 상태: {item.status || '미기록'}</p>
                        <p>문서 유효 기간: {item.effective_from || '시작 미상'} ~ {item.effective_to || '종료 미상'}</p>
                      </>
                    )}
                  </article>
                ))}
                {!!result.limitations?.length && (
                  <div>
                    <strong>제한사항</strong>
                    <ul>{result.limitations.map((limitation, limitationIndex) => <li key={limitationIndex}>{limitation}</li>)}</ul>
                  </div>
                )}
              </section>
            );
          })}
          <small>검색 결과는 출처·시점 정보이며, 후보 또는 미검증 적용 상태를 확인 완료로 간주하지 않습니다.</small>
        </details>
      )}
      {preview && (
        <dialog
          ref={dialog}
          className="agent-evidence-dialog"
          aria-label="분석 근거 확대"
          onCancel={() => setPreview(null)}
        >
          <header>
            <h2>{preview.label}</h2>
            <button
              aria-label="근거 확대 닫기"
              onClick={() => setPreview(null)}
            >
              <X size={18} />
            </button>
          </header>
          <img src={preview.src} alt={preview.description} />
          <p>{preview.description}</p>
          <small>{preview.id} · 합성 자료</small>
        </dialog>
      )}
    </section>
  );
}

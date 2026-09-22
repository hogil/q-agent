import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, X, ZoomIn } from 'lucide-react';
import type { AnalysisReportData, Workspace } from './api';
import type { AnalysisContext } from './engineeringAnalysis';
import { Chart } from './charts';
import { vectorRenderer } from './BoardOverlay';
import { waferOutline } from './metrologyMap';
import type { OverlayVectorPoint } from './overlayVectors';
import { documentUrl } from './investigationData';

function OverlayEvidence({
  points,
  label,
}: {
  points: OverlayVectorPoint[];
  label: string;
}) {
  const option = useMemo(
    () => ({
      animation: false,
      grid: { left: 6, right: 6, top: 6, bottom: 6 },
      xAxis: { type: 'value', min: -16, max: 16, show: false },
      yAxis: { type: 'value', min: -16, max: 16, show: false },
      tooltip: {
        trigger: 'item',
        renderMode: 'richText',
        formatter: (p: { value: number[] }) =>
          `X ${p.value[0]}, Y ${p.value[1]} (normalized)\ndX ${p.value[2]?.toFixed(3)}, dY ${p.value[3]?.toFixed(3)} (원본값)`,
      },
      series: [
        {
          type: 'line',
          data: waferOutline(16),
          symbol: 'none',
          silent: true,
          lineStyle: { color: '#c0cec5', width: 1 },
        },
        {
          type: 'custom',
          renderItem: vectorRenderer('#297b70', 0.45),
          data: points.map((p) => [p.x, p.y, p.dx, p.dy, 0, 1]),
        },
      ],
    }),
    [points],
  );
  return <Chart option={option} label={label} className="agent-evidence-map" />;
}

type Media = {
  id: string;
  label: string;
  description: string;
  src?: string;
  points?: OverlayVectorPoint[];
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
      (row) => row.id === image.id && row.src === image.src,
    );
    return (
      asset &&
      context.wafers.some(
        (row) => row.lot_id === asset.lotId && row.wafer_id === asset.waferId,
      )
    );
  });
  const cases = report.historical_cases || [];
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
        ...(item.overlay.vectors?.length
          ? [
              {
                id: item.overlay.id,
                points: item.overlay.vectors,
                label: '과거 Overlay · Raw',
                description: item.overlay.description,
              },
            ]
          : []),
      ]),
  ];
  return (
    <section className="agent-evidence" aria-label="현재 선택과 과거 사고 근거">
      {!!media.length && (
        <div className="agent-evidence-media">
          {media.map((item) => (
            <figure key={item.id}>
              <button
                title={`${item.label} 확대`}
                aria-label={`${item.label} 확대`}
                onClick={() => setPreview(item)}
              >
                {item.src ? (
                  <img src={item.src} alt={item.description} />
                ) : (
                  <OverlayEvidence points={item.points!} label={item.label} />
                )}
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
          {preview.src ? (
            <img src={preview.src} alt={preview.description} />
          ) : (
            <OverlayEvidence points={preview.points!} label={preview.label} />
          )}
          <p>{preview.description}</p>
          <small>{preview.id} · 합성 자료</small>
        </dialog>
      )}
    </section>
  );
}

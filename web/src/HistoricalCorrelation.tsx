import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, FileSearch, X } from 'lucide-react';
import { correlationSummary } from './engineeringAnalysis';
import type { EngineeringData } from './engineeringData';
import { Chart } from './charts';
import {
  historicalData,
  selectHistoricalData,
  type HistoricalRecord,
} from './historicalData';
import { download, type Workspace } from './api';
import type { InvestigationSelection } from './engineeringAnalysis';

type XMetric = 'temperature' | 'queue' | 'availability';
type YMetric = 'yieldPct' | 'bin3Pct' | 'bin4Pct';

const xLabels: Record<XMetric, string> = {
  temperature: 'Fab 온도 (°C)',
  queue: 'Queue (h)',
  availability: '가동률 (%)',
};
const yLabels: Record<YMetric, string> = {
  yieldPct: 'Yield (%)',
  bin3Pct: 'Bin 3 (%)',
  bin4Pct: 'Bin 4 (%)',
};

function value(record: HistoricalRecord, metric: XMetric | YMetric): number {
  return record[metric];
}

function dateLabel(value: string): string {
  return value.slice(5, 16).replace('T', ' ');
}

function axisBounds(values: number[]): { min: number; max: number } {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return { min: 0, max: 1 };
  const minimum = Math.min(...finite);
  const maximum = Math.max(...finite);
  const span = maximum - minimum;
  const margin =
    span > 0 ? span * 0.12 : Math.max(Math.abs(maximum) * 0.05, 0.5);
  return { min: minimum - margin, max: maximum + margin };
}

function axisValueLabel(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : '';
}

export default function HistoricalCorrelation({
  workspace,
  data,
  selection,
  compact = false,
}: {
  workspace: Workspace;
  data: EngineeringData;
  selection: InvestigationSelection;
  compact?: boolean;
}) {
  const [xMetric, setXMetric] = useState<XMetric>('temperature');
  const [yMetric, setYMetric] = useState<YMetric>('yieldPct');
  const records = useMemo(
    () =>
      selectHistoricalData(historicalData(workspace, data), data, selection),
    [workspace, data, selection],
  );
  const summary = useMemo(
    () =>
      correlationSummary(
        records.map((record) => ({
          value: value(record, xMetric),
          yieldPct: value(record, yMetric),
        })),
      ),
    [records, xMetric, yMetric],
  );
  const selectedSignal = data.signals.find(
    (signal) => signal.id === selection.signalId,
  );
  useEffect(() => {
    if (selectedSignal) setXMetric(selectedSignal.metric);
  }, [selectedSignal?.id]);
  const cutoff = data.trend[selection.start]?.timestamp || '';
  const [detailId, setDetailId] = useState<string | null>(null);
  const detail = records.find((record) => record.id === detailId);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    setDetailId(null);
  }, [
    workspace.incident.incident_number,
    selection.signalId,
    selection.equipment,
    selection.recipe,
    cutoff,
  ]);
  useEffect(() => {
    if (detail) dialog.current?.showModal();
  }, [detail]);
  const scatterValues = records.map(
    (record): [number, number, HistoricalRecord] => [
      value(record, xMetric),
      value(record, yMetric),
      record,
    ],
  );
  const xBounds = axisBounds(records.map((record) => value(record, xMetric)));
  const yBounds = axisBounds(records.map((record) => value(record, yMetric)));
  const scatterOption = {
    animation: false,
    grid: {
      left: compact ? 47 : 52,
      right: 12,
      top: compact ? 8 : 20,
      bottom: compact ? 31 : 40,
    },
    xAxis: {
      type: 'value',
      scale: true,
      splitNumber: 3,
      name: xLabels[xMetric],
      nameLocation: 'middle',
      nameGap: compact ? 24 : 25,
      nameTextStyle: { fontSize: compact ? 9 : 11 },
      axisLabel: { fontSize: 9, formatter: axisValueLabel },
      min: xBounds.min,
      max: xBounds.max,
    },
    yAxis: {
      type: 'value',
      name: yLabels[yMetric],
      splitNumber: compact ? 2 : 4,
      nameLocation: 'middle',
      nameGap: compact ? 35 : 40,
      nameTextStyle: { fontSize: compact ? 9 : 11 },
      min: yBounds.min,
      max: yBounds.max,
      axisLabel: { fontSize: 9, formatter: axisValueLabel },
    },
    tooltip: {
      renderMode: 'richText',
      formatter: (params: {
        data: { record: HistoricalRecord };
        value: [number, number, string];
      }) =>
        `${params.data.record.lotId} / ${params.data.record.waferId}\n${xLabels[xMetric]} ${params.value[0].toFixed(2)}\n${yLabels[yMetric]} ${params.value[1].toFixed(2)}\nFab ${dateLabel(params.data.record.fabAt)}\nEDS ${dateLabel(params.data.record.edsAt)} · 합성`,
    },
    series: [
      {
        type: 'scatter',
        symbolSize: 7,
        data: scatterValues.map(([x, y, record]) => ({
          record,
          value: [x, y, (record as HistoricalRecord).edsAt],
          itemStyle: { color: '#367f99' },
        })),
      },
    ],
  };
  return (
    <section
      className={`history-correlation ${compact ? 'compact' : 'detail-view'}`}
      aria-label="과거 Fab과 EDS 상관분석"
    >
      <div className="history-heading">
        <div>
          <h3>Fab × EDS Corr</h3>
          <span>{selectedSignal?.item || 'Item 없음'} · 과거 완료</span>
        </div>
        <span className="status-tag">SYN-HIST</span>
      </div>
      <div className="history-controls">
        <label>
          X
          <select
            aria-label="과거 Fab 지표"
            value={xMetric}
            onChange={(event) => setXMetric(event.target.value as XMetric)}
          >
            {Object.entries(xLabels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Y
          <select
            aria-label="과거 EDS 지표"
            value={yMetric}
            onChange={(event) => setYMetric(event.target.value as YMetric)}
          >
            {Object.entries(yLabels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="icon-button"
          title="과거 Fab EDS 표본 상세"
          disabled={!records.length}
          onClick={() => setDetailId(records[0].id)}
        >
          <FileSearch size={14} />
        </button>
      </div>
      {!records.length ? (
        <p className="board-empty">조건에 맞는 과거 완료 표본 없음</p>
      ) : (
        <div className="history-charts">
          <div className="history-scatter">
            <Chart
              option={scatterOption}
              className="history-scatter-chart"
              label="과거 Fab과 EDS 산점도"
              onSelect={(event) => {
                const record = records[event.dataIndex];
                if (record) setDetailId(record.id);
              }}
            />
          </div>
        </div>
      )}
      <div className="history-stats">
        <strong>n={summary.n}</strong>
        <strong>r={summary.r?.toFixed(3) ?? 'N/A'}</strong>
        <span>
          Fab {selection.equipment || '전체'} · Recipe{' '}
          {selection.recipe || '전체'}
        </span>
        <span>
          EDS cutoff &lt; {cutoff ? dateLabel(cutoff) : 'N/A'} · 합성 출처
        </span>
      </div>
      {detail && (
        <dialog
          ref={dialog}
          className="analysis-dialog history-record-dialog"
          aria-label="과거 Fab EDS 표본 상세"
          onCancel={() => setDetailId(null)}
          onClose={() => setDetailId(null)}
        >
          <header>
            <h2>과거 Fab / EDS 표본</h2>
            <span>합성 · 현재 Fab Wafer 아님</span>
            <button
              className="icon-button"
              title="과거 표본 JSON 다운로드"
              onClick={() =>
                download(
                  `${detail.id}.json`,
                  JSON.stringify(
                    {
                      synthetic: true,
                      source: 'synthetic://historical/v1',
                      incident_number: workspace.incident.incident_number,
                      selection,
                      cutoff,
                      xMetric,
                      yMetric,
                      record: detail,
                    },
                    null,
                    2,
                  ),
                )
              }
            >
              <Download size={16} />
            </button>
            <button
              className="icon-button"
              title="과거 표본 닫기"
              onClick={() => setDetailId(null)}
            >
              <X size={18} />
            </button>
          </header>
          <label className="history-record-picker">
            표본
            <select
              aria-label="상세 과거 표본 선택"
              value={detail.id}
              onChange={(event) => setDetailId(event.target.value)}
            >
              {records.map((record) => (
                <option key={record.id} value={record.id}>
                  {record.lotId} / {record.waferId}
                </option>
              ))}
            </select>
          </label>
          <dl>
            <dt>Lot / Wafer</dt>
            <dd>
              {detail.lotId} / {detail.waferId}
            </dd>
            <dt>Item / Step</dt>
            <dd>
              {detail.item} / {detail.step}
            </dd>
            <dt>설비 / Recipe</dt>
            <dd>
              {detail.equipment} / {detail.recipe}
            </dd>
            <dt>Fab 시각 · UTC</dt>
            <dd>{detail.fabAt}</dd>
            <dt>EDS 시각 · UTC</dt>
            <dd>{detail.edsAt}</dd>
            <dt>X · {xLabels[xMetric]}</dt>
            <dd>{value(detail, xMetric).toFixed(2)}</dd>
            <dt>Y · {yLabels[yMetric]}</dt>
            <dd>{value(detail, yMetric).toFixed(2)}</dd>
            <dt>EDS cutoff · UTC</dt>
            <dd>{cutoff}</dd>
            <dt>출처</dt>
            <dd>synthetic://historical/v1 · {detail.id}</dd>
          </dl>
        </dialog>
      )}
    </section>
  );
}

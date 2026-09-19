import { useEffect, useMemo, useState } from 'react';
import { correlationSummary } from './engineeringAnalysis';
import type { EngineeringData } from './engineeringData';
import { Chart } from './charts';
import {
  historicalData,
  selectHistoricalData,
  type HistoricalRecord,
} from './historicalData';
import type { Workspace } from './api';
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
      formatter: (params: { value: [number, number, string] }) =>
        `${xLabels[xMetric]} ${params.value[0].toFixed(2)}\n${yLabels[yMetric]} ${params.value[1].toFixed(2)}\nEDS ${dateLabel(String(params.value[2]))}`,
    },
    series: [
      {
        type: 'scatter',
        symbolSize: 7,
        data: scatterValues.map(([x, y, record]) => ({
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
    </section>
  );
}

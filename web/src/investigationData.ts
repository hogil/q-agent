import type { Workspace } from './api';
import type { EngineeringData, FabRow, WipRow } from './engineeringData';

export type InformNote = {
  id: string;
  title: string;
  step: string;
  equipment: string;
  date: string;
  version: string;
  body: string;
};

export type SemAsset = {
  id: string;
  lotId: string;
  waferId: string;
  src: string;
  provenance: string;
  description: string;
};

export function filterSemWafers(rows: readonly FabRow[], query: string): FabRow[] {
  const terms = query.trim().toLocaleLowerCase().split(/[\s/]+/).filter(Boolean);
  return rows.filter((row) => {
    const identity = `${row.lotId} / ${row.waferId}`.toLocaleLowerCase();
    return terms.every((term) => identity.includes(term));
  });
}

// UI fixtures only; never treated as retrieved company documents.
export function makeInformNotes(data: EngineeringData): InformNote[] {
  if (data.informNotes) return data.informNotes;
  const scopes = [
    ...new Map(
      data.signals.map((s) => [`${s.step}:${s.equipment}`, s]),
    ).values(),
  ];
  return scopes.flatMap((signal, index) => [
    {
      id: `SYN-INFORM-${index + 1}-recipe`,
      title: 'Recipe 변경 검토',
      step: signal.step,
      equipment: signal.equipment,
      date: data.trend[4].timestamp,
      version: 'v1.0 · 미승인 예시',
      body: `합성 Inform Note. 실제 사내 문서가 아닙니다.\n\n대상: ${signal.step} / ${signal.equipment}\nRecipe: ${signal.recipe}\n\n검토 안건\nRecipe 변경 전후의 측정 분포와 설비별 차이를 확인합니다. 현재 Fab Wafer에는 완료 EDS가 없으므로 같은 Item의 과거 완료 이력을 별도로 비교합니다.\n\n추가 확인\n변경 승인 기록, 실제 적용 시각, 변경 전후 조건과 센서 보정 이력이 필요합니다. 시간상 겹침만으로 불량 원인을 확정하지 않습니다.\n\n판정\n원본 및 승인자 미연결. 원인 판정 보류.`,
    },
    {
      id: `SYN-INFORM-${index + 1}-check`,
      title: '설비 점검 후 확인',
      step: signal.step,
      equipment: signal.equipment,
      date: data.trend[12].timestamp,
      version: 'v0.1 · 미승인 예시',
      body: `합성 Inform Note. 실제 사내 문서가 아닙니다.\n\n대상: ${signal.step} / ${signal.equipment}\n\n점검 안건\n설비 다운코드와 복구 시각, 대기 Lot의 Queue time을 함께 확인합니다.\n\n필요 자료\n실제 점검 결과, 공정 이력, Hold 사유 및 승인 내역.\n\n판정\n생산 시스템 미연결. Hold/Release 조치는 수행하지 않았습니다.`,
    },
  ]);
}

export function selectInformNotes(
  notes: InformNote[],
  step: string,
  equipment: string,
) {
  return notes
    .filter((note) => note.step === step && note.equipment === equipment)
    .sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
}

export function formatInformTimestamp(timestamp: string) {
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime())
    ? `${timestamp} UTC`
    : `${parsed.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

export function documentUrl(
  incident: string,
  kind: 'inform' | 'meeting',
  id: string,
) {
  return `/?${new URLSearchParams({ view: 'document', incident, kind, document: id })}`;
}

export function semRecord(
  workspace: Workspace,
  lotId: string,
  waferId: string,
) {
  if (workspace.raw) return workspace.raw.sem_assets.find(
    (asset) => asset.lotId === lotId && asset.waferId === waferId,
  ) || null;
  const owners = [...workspace.wafers].sort(
    (a, b) =>
      a.lot_id.localeCompare(b.lot_id) || a.wafer_id.localeCompare(b.wafer_id),
  );
  const index = owners.findIndex(
    (row) => row.lot_id === lotId && row.wafer_id === waferId,
  );
  // Explicit fixture owners; no measured SEM or pixel alignment is implied.
  return index >= 0 && index < 2
    ? {
        id: `SYN-SEM-0${index + 1}`,
        lotId,
        waferId,
        src:
          index === 0
            ? '/assets/synthetic-sem.png'
            : '/assets/synthetic-sem-reference.png',
        provenance: 'AI 생성 합성 예시',
        description:
          index === 0 ? 'Bridge / Particle 예시' : '분리된 Line 예시',
      }
    : null;
}

export function wipLayerBounds(rows: WipRow[]) {
  const layers = rows.map((row) => row.layer).filter(Number.isFinite);
  if (!layers.length) return null;
  const min = Math.min(...layers),
    max = Math.max(...layers);
  const padding = Math.max(0.5, (max - min) * 0.08);
  return {
    min: Math.max(0, Math.floor((min - padding) * 10) / 10),
    max: Math.ceil((max + padding) * 10) / 10,
  };
}

export function wipLayerOption(rows: WipRow[]) {
  const bounds = wipLayerBounds(rows);
  const products = [...new Set(rows.map((row) => row.productCode))];
  const colors = { RUN: '#448c74', WAIT: '#528cbb', HOLD: '#c18134' };
  return {
    animation: false,
    grid: { left: 110, right: 12, top: 10, bottom: 28 },
    tooltip: {
      trigger: 'item',
      renderMode: 'richText',
      formatter: (p: { data: { lot?: WipRow }; value: number[] }) => {
        const row = p.data.lot;
        return row
          ? `${row.productCode}\n${row.lotId} · Layer ${row.layer.toFixed(1)}\n${row.status} · ${row.wafers} Wafers · Queue ${row.queueHours.toFixed(1)}h\nFab 0.0 ~ ${row.endLayer.toFixed(1)} · 합성`
          : '';
      },
    },
    xAxis: {
      type: 'value',
      ...bounds,
      name: 'Layer',
      nameLocation: 'middle',
      nameGap: 19,
      nameTextStyle: { fontSize: 9 },
      axisLabel: { fontSize: 9, formatter: (v: number) => v.toFixed(1) },
      splitLine: { lineStyle: { color: '#eef1f0' } },
    },
    yAxis: {
      type: 'category',
      data: products,
      name: '제품',
      nameTextStyle: { fontSize: 9 },
      axisLabel: { fontSize: 9, width: 100, overflow: 'truncate' },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [
      ...products.map((product, index) => ({
        name: product,
        type: 'line',
        silent: true,
        symbol: 'none',
        clip: true,
        lineStyle: { color: '#c7d2ce', width: 2 },
        data: [
          [0, index],
          [
            Math.max(
              ...rows
                .filter((r) => r.productCode === product)
                .map((r) => r.endLayer),
            ),
            index,
          ],
        ],
      })),
      {
        type: 'scatter',
        symbolSize: 10,
        data: rows.map((row) => ({
          value: [row.layer, products.indexOf(row.productCode)],
          lot: row,
          itemStyle: {
            color: colors[row.status],
            borderWidth: 1,
            borderColor: '#fff',
          },
        })),
      },
    ],
  };
}

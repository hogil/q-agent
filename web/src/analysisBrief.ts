import type { AnalysisReportData } from './api';
import type { AnalysisContext } from './engineeringAnalysis';

const number = (value: number) => Number(value.toFixed(4)).toLocaleString('en-US', { maximumFractionDigits: 4 });
const units: Record<string, string> = { degC: '°C', hours: 'h', '%': '%' };

// Display saved Tool observations and recommendations, not a new risk-model verdict.
export function analysisBrief(report: AnalysisReportData, context: AnalysisContext) {
  const observations = report.trend.flatMap((trend) => {
    const onset = trend.onset_summary;
    if (!onset || onset.before.mean == null || onset.after.mean == null) return [];
    const unit = units[trend.unit] || trend.unit;
    const delta = onset.delta?.value;
    return [`${onset.timestamp?.replace('T', ' ').replace('Z', ' UTC') || '감지 구간'} · ` +
      `평균 ${number(onset.before.mean)} → ${number(onset.after.mean)} ${unit}` +
      (delta == null ? '' : ` (${delta > 0 ? '+' : ''}${number(delta)} ${unit})`) +
      '. 현재 공정 변동과 불량 위험의 연관성을 확인할 대상입니다.'];
  });
  const cases = (report.historical_cases || []).filter((row) => row.item === context.item && row.step === context.step);
  const comparisons = cases.map((row) => {
    const fields = ['Step', 'Item', ...(context.equipment && row.equipment === context.equipment ? ['설비'] : [])];
    const cd = row.cd.measurements.map((point) => `${point.site} ${number(point.value)}`).join(' / ');
    return {
      id: row.incident_number,
      text: `${row.date.slice(0, 10)} · ${fields.join('·')} 일치. 당시 CD ${cd} ${row.cd.unit}, ` +
        `EDS Yield ${number(row.historical_eds.yieldPct)}%, Bin3 ${number(row.historical_eds.bin3Pct)}%. ` +
        '현재 SEM·Map과 대조할 유사 사고 후보이며, 같은 원인으로 확정된 것은 아닙니다.',
    };
  });
  const conflictsWithCases = (text: string) => cases.length > 0 && /과거 사고.*(?:존재하지|없습니다)/.test(text);
  return {
    observations,
    comparisons,
    checks: report.inspection_plan.filter((row) => row.kind === 'check').map((row) => ({
      ...row,
      target: conflictsWithCases(row.target) ? '저장 답변과 조회 근거 재검토' : row.target,
      comparison: conflictsWithCases(row.comparison)
        ? '저장 답변은 과거 사고가 없다고 설명하지만 조회된 사고 후보가 있습니다. 후보의 원인·조치와 현재 조건을 대조해야 합니다.'
        : row.comparison.includes(' ') ? row.comparison
        : `${context.equipment || context.step}의 감지 시각 전후 PM/DOWN·Recipe·계측 보정 이력을 비교하고, ` +
          `${context.item}의 변동 시작 시점과 겹치는 변경이 있는지 확인합니다.`,
      basis: row.basis.includes(' ') ? row.basis : '저장된 Trend 변동과 점검 대상',
    })),
    eds: report.inspection_plan.filter((row) => row.kind === 'eds_followup').map((row) => ({
      ...row,
      comparison: !conflictsWithCases(row.comparison) && row.comparison.includes(' ') ? row.comparison
        : '현재 선택 Lot/Wafer의 EDS 수신 후 Yield·Bin·Fail 위치를 과거 사고 및 같은 조건의 비교군과 대조합니다. 현재 불량 판정은 대기입니다.',
    })),
  };
}

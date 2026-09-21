export type Attachment = {
  kind: string;
  label: string;
  id: string;
  incident_number?: string;
};
export type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  attachments?: Attachment[];
};
export type RoomSummary = {
  id: string;
  title: string;
  incident_number: string;
  updated_at: string;
};
export type Room = RoomSummary & {
  messages: Message[];
  has_more?: boolean;
  oldest_id?: string;
};
export type Incident = {
  incident_id: string;
  incident_number: string;
  title: string;
  city: string;
  line: string;
  department: string;
  occurred_at: string;
  expected_lot_count: number;
  affected_wafer_count?: number;
  confirmed_cause?: string;
  analysis_detail?: string;
  containment?: string;
  remaining?: string;
};
export type Lot = { lot_id: string; product_code: string; status: string };
export type Wafer = { lot_id: string; wafer_id: string; status: string };
export type Meeting = {
  chunk_id: string;
  meeting_id: string;
  title: string;
  meeting_date: string;
  version: string;
  text: string;
  source_ref: string;
  status: string;
};
export type WaferGeometry = {
  radius_mm: number;
  coordinate_radius: number;
  chip_pitch_x_mm: number;
  chip_pitch_y_mm: number;
  chip_origin_x_mm: number;
  chip_origin_y_mm: number;
};
export type Workspace = {
  incident: Incident;
  lots: Lot[];
  wafers: Wafer[];
  meetings: Meeting[];
  synthetic: true;
  as_of: string;
  wafer_geometry?: WaferGeometry;
  raw?: {
    engineering: EngineeringData;
    trend_fleets: Record<string, TrendFleet[]>;
    comparison_traces: Record<string, Record<string, EquipmentTracePoint[]>>;
    inform_notes: InformNote[];
    sem_assets: SemAsset[];
  };
};
export type Bootstrap = {
  synthetic: true;
  mode: string;
  llm_connected: boolean;
  llm_configured?: boolean;
  models?: Record<string, string>;
  incidents: Incident[];
  rooms: RoomSummary[];
  release: string;
};

export async function api<T>(
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers:
      body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response
    .json()
    .catch(() => ({ error: '서버 응답을 읽을 수 없습니다.' }));
  if (!response.ok) throw new Error(value.error || `HTTP ${response.status}`);
  return value;
}

export function download(
  name: string,
  content: string,
  type = 'application/json',
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
import type { EngineeringData, TrendFleet } from './engineeringData';
import type { InformNote, SemAsset } from './investigationData';
import type { EquipmentTracePoint } from './equipmentComparison';

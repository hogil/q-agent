import {
  Activity,
  Database,
  Factory,
  FileText,
  Focus,
  History,
  LayoutDashboard,
  NotebookPen,
  AlertTriangle,
  ScatterChart,
  ClipboardCheck,
} from 'lucide-react';
import type { Tab } from './Views';

export const modules: {
  id: Tab;
  label: string;
  name: string;
  status: string;
  icon: typeof Activity;
  plan: boolean;
}[] = [
  {
    id: 'signals',
    label: 'Signals',
    name: '이상 감지 목록',
    status: '합성',
    icon: AlertTriangle,
    plan: false,
  },
  {
    id: 'overview',
    label: 'Overview',
    name: '분석 개요',
    status: '조회 결과',
    icon: LayoutDashboard,
    plan: false,
  },
  {
    id: 'trend',
    label: 'Trend',
    name: 'Trend 구간 확인',
    status: '합성',
    icon: Activity,
    plan: true,
  },
  {
    id: 'correlation',
    label: 'Fab × EDS',
    name: 'Fab · EDS Yield 상관분석',
    status: '합성 계산',
    icon: ScatterChart,
    plan: true,
  },
  {
    id: 'map',
    label: 'Map / Images',
    name: 'Wafer · SEM · Overlay',
    status: '합성',
    icon: Focus,
    plan: true,
  },
  {
    id: 'inform',
    label: 'Inform',
    name: 'Eng’r Inform · 회의록',
    status: '회의록 연결',
    icon: FileText,
    plan: true,
  },
  {
    id: 'production',
    label: 'Production',
    name: '생산 시스템 기록',
    status: '합성 / 미연결',
    icon: Factory,
    plan: true,
  },
  {
    id: 'history',
    label: 'History',
    name: '이전 사고 비교',
    status: '합성 DB',
    icon: History,
    plan: true,
  },
  {
    id: 'data',
    label: 'Data',
    name: 'Lot / Wafer 관계',
    status: '합성 DB',
    icon: Database,
    plan: true,
  },
  {
    id: 'review',
    label: 'Review',
    name: '근거 검토',
    status: '수동 검토',
    icon: NotebookPen,
    plan: false,
  },
  {
    id: 'assessment',
    label: 'Assessment',
    name: '설명 · 판정',
    status: 'LLM 미연결',
    icon: ClipboardCheck,
    plan: true,
  },
];

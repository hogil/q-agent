import { useState } from 'react';
import {
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Database,
  ListFilter,
  Plus,
} from 'lucide-react';
import type { Tab } from './Views';
import { modules } from './modules';

const tasks = modules
  .filter((item) => item.plan)
  .map((item) => ({ ...item, label: item.name }));

export default function PlanPanel({
  roomId,
  navigate,
  prepare,
  disabled,
}: {
  roomId: string;
  navigate: (tab: Tab) => void;
  prepare: (labels: string[]) => void;
  disabled: boolean;
}) {
  const key = `q-agent-plan-${roomId}`;
  const [expanded, setExpanded] = useState(true);
  const [selected, setSelected] = useState<Tab[]>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(key) || 'null');
      return Array.isArray(value)
        ? value.filter((v) => tasks.some((t) => t.id === v))
        : ['data', 'inform'];
    } catch {
      return ['data', 'inform'];
    }
  });
  function toggle(id: Tab) {
    const next = selected.includes(id)
      ? selected.filter((v) => v !== id)
      : [...selected, id];
    setSelected(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* Preferences are optional; room history is server-owned. */
    }
  }
  return (
    <section className="plan-panel" aria-label="분석 계획">
      <button
        className="plan-heading"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <ClipboardList size={14} />
        <strong>분석 계획</strong>
        <span>{selected.length}개 선택</span>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {expanded && (
        <div className="plan-body">
          <div className="plan-prerequisite">
            <Database size={12} />
            <span>사고 범위 확인</span>
            <small>필수</small>
          </div>
          {tasks.map((task) => (
            <div
              className={`plan-task ${selected.includes(task.id) ? 'checked' : ''}`}
              key={task.id}
            >
              <label>
                <input
                  type="checkbox"
                  checked={selected.includes(task.id)}
                  onChange={() => toggle(task.id)}
                  disabled={disabled}
                />
                <task.icon size={13} />
                <span>{task.label}</span>
              </label>
              <small>{task.status}</small>
              <button
                className="icon-button"
                title={`${task.label} 화면 열기`}
                aria-label={`${task.label} 화면 열기`}
                onClick={() => navigate(task.id)}
                disabled={disabled}
              >
                <ArrowUpRight size={14} />
              </button>
            </div>
          ))}
          <div className="plan-footer">
            <span>
              <ListFilter size={11} />
              선택 ≠ 실행 완료
            </span>
            <button
              className="text-button"
              disabled={!selected.length || disabled}
              onClick={() =>
                prepare(
                  tasks
                    .filter((t) => selected.includes(t.id))
                    .map((t) => t.label),
                )
              }
            >
              <Plus size={12} />
              질문에 적용
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

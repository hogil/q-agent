import { useMemo, useState } from 'react';
import {
  Check,
  ChevronRight,
  Database,
  ExternalLink,
  Factory,
  FileText,
  History,
  Link2,
} from 'lucide-react';
import { api, type Incident, type Workspace } from './api';
import { Empty, InformView, type ViewProps } from './Views';

export function InformWorkspace(props: ViewProps & { initialMode?: string }) {
  const [source, setSource] = useState(
    props.initialMode === 'engineer' ? 'engineer' : 'meetings',
  );
  return (
    <div>
      <div className="map-mode-bar">
        <button
          className={source === 'meetings' ? 'active' : ''}
          onClick={() => setSource('meetings')}
        >
          <FileText size={14} />
          회의록
        </button>
        <button
          className={source === 'engineer' ? 'active' : ''}
          onClick={() => setSource('engineer')}
        >
          <FileText size={14} />
          Eng’r Inform
        </button>
      </div>
      {source === 'meetings' ? (
        <InformView {...props} />
      ) : (
        <section className="detail-view">
          <div className="section-title">
            <div>
              <h2>Eng’r Inform</h2>
              <span>Engineer Inform Note · 원문 및 버전</span>
            </div>
            <span className="status-tag amber">사내 서비스 미연결</span>
          </div>
          <div className="document-reader">
            <div className="document-topline">
              <span className="document-category">ENGINEER INFORM NOTE</span>
              <span className="status-tag">합성 양식</span>
            </div>
            <h2>공정 이상 검토 · Inform 확인 항목</h2>
            <div className="document-metadata">
              <span>{props.workspace.incident.incident_number}</span>
              <span>초안 · 실제 Inform 아님</span>
            </div>
            <div className="document-rule" />
            <h3>현재 확인할 수 있는 사고 기록</h3>
            <p className="original-text">
              {props.workspace.incident.analysis_detail ||
                '분석 기록이 없습니다.'}
            </p>
            <h3 className="inform-subheading">연결이 필요한 원본</h3>
            <dl className="source-fields">
              <dt>Inform 번호</dt>
              <dd>미연결</dd>
              <dt>작성자 · 승인자</dt>
              <dd>미연결</dd>
              <dt>설비 / 공정 / Recipe</dt>
              <dd>원본 참조 필요</dd>
              <dt>문서 버전 · 변경 이력</dt>
              <dd>원본 참조 필요</dd>
              <dt>원문 chunk / source_ref</dt>
              <dd>기존 Hybrid RAG 서비스 연동 대상</dd>
            </dl>
            <div className="document-actions">
              <button
                className="outline-button"
                onClick={() =>
                  props.attach({
                    kind: 'request',
                    id: 'engineer-inform-unavailable',
                    label: 'Eng’r Inform 원본 확인 요청 · 미연결',
                  })
                }
              >
                <Link2 size={14} />
                확인 요청에 추가
              </button>
            </div>
            <p className="reader-note">
              위 분석 기록은 합성 사고 DB에서 가져왔습니다. Eng’r Inform의
              내용이나 승인 상태로 해석하지 않습니다.
            </p>
          </div>
        </section>
      )}
    </div>
  );
}

const systems = [
  {
    id: 'mes',
    name: 'MES',
    label: 'Lot · 공정 진행 이력',
    fields: [
      'Operation / Step',
      '장비 ID',
      '투입 · 완료 시간',
      'Hold / Release 이력',
    ],
  },
  {
    id: 'fdc',
    name: 'FDC',
    label: '설비 Trace · Alarm',
    fields: [
      'Sensor trace',
      'Alarm 발생 시각',
      'Chamber / Module',
      '원본 데이터 구간',
    ],
  },
  {
    id: 'spc',
    name: 'SPC',
    label: '관리도 · 공정 품질',
    fields: ['관리 항목 · 단위', 'UCL / LCL', '측정 시각', 'Rule violation'],
  },
  {
    id: 'recipe',
    name: 'Recipe',
    label: '조건 · 변경 이력',
    fields: [
      'Recipe ID / 버전',
      '변경 전 · 후 값',
      '변경 승인',
      '영향 Lot 범위',
    ],
  },
];

export function ProductionView(props: ViewProps) {
  const [systemId, setSystemId] = useState('mes');
  const [lot, setLot] = useState(props.workspace.lots[0]?.lot_id || '');
  const source = systems.find((s) => s.id === systemId)!;
  const selected = props.workspace.lots.find((l) => l.lot_id === lot);
  return (
    <section className="detail-view production-view">
      <div className="section-title">
        <div>
          <h2>Production systems</h2>
          <span>선택 사고 · Lot 기준 원본 조회</span>
        </div>
        <Factory size={21} />
      </div>
      <div className="system-picker">
        {systems.map((s) => (
          <button
            key={s.id}
            className={s.id === systemId ? 'selected' : ''}
            onClick={() => setSystemId(s.id)}
          >
            <strong>{s.name}</strong>
            <span>{s.label}</span>
            <small>미연결</small>
          </button>
        ))}
      </div>
      <div className="view-toolbar">
        <label className="select-field">
          Lot 범위
          <select
            aria-label="생산 시스템 Lot 선택"
            value={lot}
            onChange={(e) => setLot(e.target.value)}
          >
            {props.workspace.lots.map((item) => (
              <option key={item.lot_id}>{item.lot_id}</option>
            ))}
          </select>
        </label>
        <span className="status-tag amber">{source.name} 미연결</span>
      </div>
      <div className="production-scope">
        <Database size={18} />
        <div>
          <strong>{lot || '등록 Lot 없음'}</strong>
          <span>
            {selected?.product_code || '제품 정보 없음'} ·{' '}
            {selected?.status || '등록 상태 없음'}
          </span>
        </div>
        <span className="status-tag">출처: 합성 사고 DB</span>
      </div>
      <div className="record-heading">
        <h3>{source.name} 원본 조회 항목</h3>
        <span>연결 상태</span>
      </div>
      <dl className="source-fields">
        {source.fields.map((field) => (
          <div key={field}>
            <dt>{field}</dt>
            <dd>원본 미연결</dd>
          </div>
        ))}
      </dl>
      <div className="production-status">
        <span className="unconnected-icon">
          <ExternalLink size={22} />
        </span>
        <h3>생산 시스템 원본이 연결되지 않았습니다</h3>
        <p>사고 DB의 등록 목록과 생산 시스템의 실제 처리 이력은 구분됩니다.</p>
        <button
          className="outline-button"
          onClick={() =>
            props.attach({
              kind: 'request',
              id: `${source.id}:${lot}`,
              label: `${source.name} · ${lot} 원본 조회 요청`,
            })
          }
        >
          <Link2 size={14} />
          확인 요청에 추가
        </button>
      </div>
    </section>
  );
}

export function HistoryView({
  incidents,
  ...props
}: ViewProps & { incidents: Incident[] }) {
  const [range, setRange] = useState('previous');
  const [detail, setDetail] = useState<Workspace | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const current = props.workspace.incident;
  const candidates = useMemo(
    () =>
      incidents
        .filter(
          (i) =>
            i.incident_id !== current.incident_id &&
            i.department === current.department &&
            i.line === current.line &&
            (range === 'all' ||
              new Date(i.occurred_at) < new Date(current.occurred_at)),
        )
        .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)),
    [incidents, current, range],
  );
  async function inspect(incident: Incident) {
    setLoading(true);
    setError('');
    try {
      setDetail(
        await api<Workspace>(
          `/workspace?incident=${encodeURIComponent(incident.incident_number)}`,
        ),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="detail-view history-view">
      <div className="section-title">
        <div>
          <h2>Related incident history</h2>
          <span>동일 부서 · 동일 라인으로 찾은 비교 후보</span>
        </div>
        <History size={21} />
      </div>
      <div className="view-toolbar">
        <div className="segmented">
          <button
            className={range === 'previous' ? 'selected' : ''}
            onClick={() => {
              setRange('previous');
              setDetail(null);
            }}
          >
            이전 사고
          </button>
          <button
            className={range === 'all' ? 'selected' : ''}
            onClick={() => {
              setRange('all');
              setDetail(null);
            }}
          >
            전체 기간
          </button>
        </div>
        <span className="history-cutoff">
          발생일 기준 {current.occurred_at.slice(0, 10)}
        </span>
      </div>
      <div className="data-notice">
        <span className="synthetic-label">합성 DB</span>
        <span>
          조건 일치 후보이며 동일 원인·재발 사고로 판정한 결과가 아닙니다.
        </span>
      </div>
      <div className="history-list">
        {candidates.map((item) => (
          <button
            disabled={loading}
            className={
              detail?.incident.incident_id === item.incident_id
                ? 'selected'
                : ''
            }
            key={item.incident_id}
            onClick={() => inspect(item)}
          >
            <span className="history-node" />
            <time>{item.occurred_at.slice(0, 10)}</time>
            <span>
              <strong>{item.title}</strong>
              <small>
                {item.incident_number} ·{' '}
                {item.confirmed_cause ? '확정 원인 기록 있음' : '원인 미확정'}
              </small>
            </span>
            <ChevronRight size={15} />
          </button>
        ))}
      </div>
      {!candidates.length && (
        <Empty
          title="조건에 맞는 이전 사고가 없습니다"
          detail="현재 합성 DB에서 선택 사고보다 이전의 동일 부서·라인 기록이 없습니다."
        />
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {detail && (
        <div className="history-comparison">
          <div className="section-title">
            <div>
              <h2>{detail.incident.incident_number}</h2>
              <span>비교 기록 · 현재 사고 선택은 유지</span>
            </div>
            <button
              className="outline-button"
              onClick={() =>
                props.attach({
                  kind: 'history',
                  id: detail.incident.incident_id,
                  incident_number: detail.incident.incident_number,
                  label: `비교 사고 ${detail.incident.incident_number}`,
                })
              }
            >
              <Link2 size={14} />
              비교 대상에 추가
            </button>
          </div>
          <div className="comparison-grid">
            <div>
              <span>CURRENT</span>
              <h3>{current.title}</h3>
              <p>{current.confirmed_cause || current.analysis_detail}</p>
            </div>
            <div>
              <span>COMPARISON</span>
              <h3>{detail.incident.title}</h3>
              <p>
                {detail.incident.confirmed_cause ||
                  detail.incident.analysis_detail}
              </p>
            </div>
          </div>
          <div className="history-evidence">
            <Check size={14} />
            <span>
              등록 Lot {detail.lots.length}건 · Wafer {detail.wafers.length}건 ·
              승인 회의록 {detail.meetings.length}건
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

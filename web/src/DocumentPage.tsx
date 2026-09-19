import { useEffect, useState } from 'react';
import { FileText, Printer } from 'lucide-react';
import { api, type Workspace } from './api';
import { makeEngineeringData } from './engineeringData';
import { makeInformNotes } from './investigationData';

export default function DocumentPage() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState('');
  const query = new URLSearchParams(location.search);
  const incident = query.get('incident') || '';
  const id = query.get('document');
  const kind = query.get('kind');
  useEffect(() => {
    let active = true;
    api<Workspace>(`/workspace?incident=${encodeURIComponent(incident)}`)
      .then((data) => {
        if (active) setWorkspace(data);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [incident]);
  const note =
    workspace && kind === 'inform'
      ? makeInformNotes(makeEngineeringData(workspace)).find((n) => n.id === id)
      : null;
  const meeting =
    workspace && kind === 'meeting'
      ? workspace.meetings.find((m) => m.chunk_id === id)
      : null;
  return (
    <main className="full-document">
      <header>
        <FileText size={18} />
        <strong>{kind === 'inform' ? 'Eng’r Inform' : '회의록'}</strong>
        <span>합성 데이터 · 실제 사내 문서 아님</span>
        <button
          className="icon-button"
          title="문서 인쇄"
          onClick={() => window.print()}
        >
          <Printer size={18} />
        </button>
      </header>
      {error ? (
        <p role="alert">{error}</p>
      ) : !workspace ? (
        <p role="status">문서 조회 중</p>
      ) : !note && !meeting ? (
        <p role="alert">해당 사고 범위에서 문서를 찾을 수 없습니다.</p>
      ) : (
        <article>
          <h1>{note?.title || meeting?.title}</h1>
          <dl>
            <dt>사고</dt>
            <dd>{incident}</dd>
            <dt>문서 ID</dt>
            <dd>{id}</dd>
            <dt>버전</dt>
            <dd>{note?.version || meeting?.version}</dd>
            <dt>작성일</dt>
            <dd>{note?.date || meeting?.meeting_date}</dd>
            {note && (
              <>
                <dt>Step / 설비</dt>
                <dd>
                  {note.step} / {note.equipment}
                </dd>
              </>
            )}
          </dl>
          <div className="full-document-body">
            {note?.body || meeting?.text}
          </div>
          <footer>
            {note
              ? 'UI fixture · 원본/승인자 미연결'
              : `${meeting?.source_ref} · 저장된 전체 chunk (회의 전체 문서 아님)`}
          </footer>
        </article>
      )}
    </main>
  );
}

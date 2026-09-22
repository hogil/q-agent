import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import {
  Activity,
  ArrowDownToLine,
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ClipboardList,
  Database,
  Factory,
  FileText,
  Focus,
  LayoutDashboard,
  Link2,
  Loader2,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import {
  api,
  download,
  type Attachment,
  type Bootstrap,
  type Room,
  type RoomSummary,
  type Workspace,
} from './api';
import { DataView, Empty, Overview, type Tab } from './Views';
import PlanPanel from './PlanPanel';
import Images from './Images';
import { HistoryView, InformWorkspace } from './Sources';
import { modules } from './modules';
import ReviewView from './ReviewView';
import EngineeringWorkspace from './EngineeringWorkspace';
import AnalysisReport from './AnalysisReport';
import {
  clearReviewDraft,
  loadReviewDraft,
  saveReviewDraft,
} from './reviewState';

const tabs = modules;
type ModalType =
  | 'search'
  | 'settings'
  | 'rename'
  | 'delete'
  | 'run'
  | 'attachment'
  | null;

function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="modal"
      aria-label={title}
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="닫기" onClick={close}>
          <X size={19} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export default function App() {
  const isChat = new URLSearchParams(location.search).get('view') === 'chat';
  const [showStartupReport, setShowStartupReport] = useState(() => !location.search);
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [roomId, setRoomId] = useState('');
  const [room, setRoom] = useState<Room | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [tab, setTab] = useState<Tab>(
    () =>
      modules.find(
        (m) => m.id === new URLSearchParams(location.search).get('tab'),
      )?.id || 'trend',
  );
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [detailMode, setDetailMode] = useState(
    new URLSearchParams(location.search).get('mode') || '',
  );
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [notes, setNotes] = useState('');
  const [reviewContext, setReviewContext] = useState('');
  const [storageError, setStorageError] = useState(false);
  const [planCollapsed, setPlanCollapsed] = useState(true);
  const [boardToolsOpen, setBoardToolsOpen] = useState(false);
  const [storage] = useState(() => {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [modal, setModal] = useState<ModalType>(null);
  const [search, setSearch] = useState('');
  const [rename, setRename] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [reload, setReload] = useState(0);
  const [copied, setCopied] = useState('');
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [pendingAttachment, setPendingAttachment] = useState<Attachment | null>(
    null,
  );
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const contentColumns = useRef<HTMLDivElement>(null);
  const skipScroll = useRef(false);

  const reportError = (reason: unknown) =>
    setError(
      reason instanceof Error ? reason.message : '요청을 완료하지 못했습니다.',
    );
  async function refreshRooms() {
    const data = await api<Bootstrap>('/bootstrap');
    setBootstrap(data);
    return data;
  }
  function restoreReview(id: string, incident: string) {
    const saved = loadReviewDraft(storage, id, incident);
    setDraft(saved.text);
    setAttachments(saved.attachments);
    setNotes(saved.notes);
    setReviewContext(`${id}:${incident}`);
  }
  function persistReview() {
    if (!room || !workspace) return false;
    const saved = saveReviewDraft(
      storage,
      room.id,
      workspace.incident.incident_number,
      { text: draft, attachments, notes },
    );
    setStorageError(!saved);
    const hasDraft = !!(draft.trim() || attachments.length || notes.trim());
    if (!saved && hasDraft)
      setError(
        '브라우저 저장 실패. 이동 전 초안을 내려받고 브라우저 저장 공간과 설정을 확인해 주세요.',
      );
    return saved || !hasDraft;
  }
  function downloadDraft() {
    download(
      `${workspace?.incident.incident_number}-draft.json`,
      JSON.stringify(
        {
          synthetic: true,
          room_id: roomId,
          incident_number: workspace?.incident.incident_number,
          prepared_question: draft,
          notes,
          references: attachments,
          review_type: 'manual_notes_not_agent_verdict',
        },
        null,
        2,
      ),
    );
  }
  useEffect(() => {
    let active = true;
    api<Bootstrap>('/bootstrap')
      .then((data) => {
        if (!active) return;
        setBootstrap(data);
        if (showStartupReport && data.startup_report) {
          setRoomId(data.startup_report.room_id);
          return;
        }
        let previous = new URLSearchParams(location.search).get('room');
        try {
          previous ||= storage?.getItem('q-agent-room') || null;
        } catch {
          /* Storage does not gate the server room list. */
        }
        setRoomId(
          data.rooms.find((r) => r.id === previous)?.id ||
            data.rooms[0]?.id ||
            '',
        );
        if (!data.rooms.length) setLoading(false);
      })
      .catch((e) => {
        if (active) {
          reportError(e);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!roomId) return;
    let active = true;
    setLoading(true);
    setRoom(null);
    setWorkspace(null);
    setAttachments([]);
    setDraft('');
    setNotes('');
    setReviewContext('');
    setDocumentId(new URLSearchParams(location.search).get('document'));
    api<Room>(`/rooms/${roomId}`)
      .then(async (value) => {
        const data = await api<Workspace>(
          `/workspace?incident=${encodeURIComponent(value.incident_number)}`,
        );
        if (!active) return;
        setRoom(value);
        setWorkspace(data);
        setLoading(false);
        try {
          storage?.setItem('q-agent-room', roomId);
        } catch {
          /* Optional last room preference. */
        }
        const url = new URL(location.href);
        if (!showStartupReport || !bootstrap?.startup_report) {
          url.searchParams.set('room', roomId);
          history.replaceState(null, '', url);
        }
        restoreReview(roomId, data.incident.incident_number);
      })
      .catch((e) => {
        if (active) {
          reportError(e);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [roomId, reload]);
  useEffect(() => {
    if (
      loading ||
      !workspace ||
      room?.id !== roomId ||
      reviewContext !== `${roomId}:${workspace.incident.incident_number}`
    )
      return;
    setStorageError(
      !saveReviewDraft(storage, roomId, workspace.incident.incident_number, {
        text: draft,
        attachments,
        notes,
      }),
    );
  }, [
    roomId,
    workspace,
    room?.id,
    loading,
    reviewContext,
    draft,
    attachments,
    notes,
    storage,
  ]);
  useEffect(() => {
    if (skipScroll.current) {
      skipScroll.current = false;
      return;
    }
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [room?.messages.length, busy]);
  useEffect(() => {
    contentColumns.current?.scrollTo(0, 0);
    contentColumns.current?.querySelector('.analysis-scroll')?.scrollTo(0, 0);
    const tabs = document.querySelector<HTMLElement>('.workspace-tabs');
    const active = tabs?.querySelector<HTMLElement>('.active');
    if (tabs && active)
      tabs.scrollTo({
        left:
          active.offsetLeft -
          tabs.offsetLeft -
          (tabs.clientWidth - active.clientWidth) / 2,
      });
  }, [tab, workspace?.incident.incident_number]);
  useEffect(() => {
    if (!notice) return;
    const timeout = setTimeout(() => setNotice(''), 3500);
    return () => clearTimeout(timeout);
  }, [notice]);
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setModal('search');
      }
      if (e.key === 'Escape') setSidebarOpen(false);
    };
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, []);

  async function createRoom() {
    if (room && workspace && !persistReview()) return;
    setBusy(true);
    setError('');
    try {
      const value = await api<Room>('/rooms', 'POST', {
        title: '새 분석',
        incident_number:
          workspace?.incident.incident_number ||
          bootstrap?.incidents[0]?.incident_number,
      });
      await refreshRooms();
      setRoomId(value.id);
      if (!isChat) navigate('trend');
      setSidebarOpen(false);
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  }
  async function selectIncident(number: string) {
    if (!roomId || busy) return;
    if (!persistReview()) return;
    setBusy(true);
    setError('');
    try {
      await api(`/rooms/${roomId}`, 'PATCH', { incident_number: number });
      await refreshRooms();
      setReload((r) => r + 1);
      setModal(null);
      setSearch('');
      if (!isChat) navigate('trend');
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  }
  function attach(item: Attachment) {
    if (busy) return;
    const reference = {
      ...item,
      incident_number:
        item.incident_number || workspace?.incident.incident_number,
    };
    if (
      attachments.some(
        (a) =>
          a.id === reference.id &&
          a.kind === reference.kind &&
          a.incident_number === reference.incident_number,
      )
    ) {
      setNotice('이미 검토 목록에 있는 근거입니다.');
      return;
    }
    if (attachments.length >= 8) {
      setNotice(
        '검토 근거는 최대 8개입니다. 기존 항목을 제거한 뒤 추가해 주세요.',
      );
      return;
    }
    setAttachments((items) => [...items, reference]);
    setNotice('검토 대상에 추가했습니다.');
    if (isChat) setTimeout(() => composer.current?.focus(), 60);
  }
  function launchChat() {
    if (!persistReview()) return;
    location.assign(`/?view=chat&room=${encodeURIComponent(roomId)}`);
  }
  function navigate(
    value: Tab,
    document?: string,
    mode?: string,
    preserveDraft = true,
  ) {
    const selected = value === 'inform' ? document || documentId : null;
    if (isChat) {
      if (preserveDraft && !persistReview()) return;
      location.assign(
        `/?room=${encodeURIComponent(roomId)}&tab=${value}${selected ? `&document=${encodeURIComponent(selected)}` : ''}${mode ? `&mode=${encodeURIComponent(mode)}` : ''}`,
      );
    } else {
      setTab(value);
      setDocumentId(selected);
      setDetailMode(mode || '');
      const url = new URL(location.href);
      url.searchParams.set('tab', value);
      if (selected) url.searchParams.set('document', selected);
      else url.searchParams.delete('document');
      if (mode) url.searchParams.set('mode', mode);
      else url.searchParams.delete('mode');
      history.replaceState(null, '', url);
      contentColumns.current?.scrollTo(0, 0);
    }
    setSidebarOpen(false);
  }
  async function send(event?: FormEvent) {
    event?.preventDefault();
    if (!room || busy || !draft.trim()) return;
    const content = draft.trim();
    setBusy(true);
    setError('');
    try {
      const result = await api<{
        messages: Room['messages'];
        room: RoomSummary;
      }>(`/rooms/${room.id}/messages`, 'POST', { content, attachments });
      setRoom((current) =>
        current
          ? {
              ...current,
              ...result.room,
              messages: [...current.messages, ...result.messages],
            }
          : current,
      );
      setDraft('');
      setAttachments([]);
      if (workspace)
        saveReviewDraft(storage, room.id, workspace.incident.incident_number, {
          text: '',
          attachments: [],
          notes,
        });
      if (result.room.incident_number !== workspace?.incident.incident_number) {
        const next = await api<Workspace>(
          `/workspace?incident=${encodeURIComponent(result.room.incident_number)}`,
        );
        setWorkspace(next);
        setDocumentId(null);
        restoreReview(room.id, next.incident.incident_number);
      }
      await refreshRooms();
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  }
  async function manageRoom(action: 'rename' | 'delete') {
    if (!roomId || busy) return;
    setBusy(true);
    try {
      if (action === 'rename') {
        const title = rename.trim();
        if (!title) return;
        await api(`/rooms/${roomId}`, 'PATCH', { title });
        setRoom((current) => (current ? { ...current, title } : current));
        await refreshRooms();
      } else {
        await api(`/rooms/${roomId}`, 'DELETE');
        bootstrap?.incidents.forEach((i) =>
          clearReviewDraft(storage, roomId, i.incident_number),
        );
        const data = await refreshRooms();
        setRoomId(data.rooms[0]?.id || '');
        setRoom(null);
        setWorkspace(null);
        if (!data.rooms.length) setLoading(false);
      }
      setModal(null);
    } catch (e) {
      reportError(e);
    } finally {
      setBusy(false);
    }
  }
  async function openAttachment(item: Attachment, switchConfirmed = false) {
    if (
      item.incident_number &&
      item.incident_number !== workspace?.incident.incident_number
    ) {
      if (!switchConfirmed) {
        setPendingAttachment(item);
        setModal('attachment');
        return;
      }
      if (busy) return;
      if (!persistReview()) return;
      setBusy(true);
      try {
        const next = await api<Workspace>(
          `/workspace?incident=${encodeURIComponent(item.incident_number)}`,
        );
        await api(`/rooms/${roomId}`, 'PATCH', {
          incident_number: item.incident_number,
        });
        setWorkspace(next);
        setRoom((current) =>
          current
            ? { ...current, incident_number: item.incident_number! }
            : current,
        );
        restoreReview(roomId, next.incident.incident_number);
        await refreshRooms();
        setModal(null);
        setPendingAttachment(null);
      } catch (e) {
        reportError(e);
        return;
      } finally {
        setBusy(false);
      }
    } else if (
      item.kind === 'inform' &&
      !workspace?.meetings.some((m) => m.chunk_id === item.id)
    ) {
      setNotice(
        '현재 사고 범위에 없는 근거입니다. 해당 사고를 먼저 선택해 주세요.',
      );
      return;
    }
    const target: Tab = item.id.startsWith('engineering:corr:')
      ? 'correlation'
      : item.kind === 'inform'
        ? 'inform'
        : ['map', 'image'].includes(item.kind)
          ? 'map'
          : item.kind === 'trend'
            ? 'trend'
            : item.kind === 'history'
              ? 'history'
              : item.kind === 'request'
                ? item.id.startsWith('engineer-inform-')
                  ? 'inform'
                  : 'production'
                : 'data';
    if (item.kind === 'inform') setDocumentId(item.id);
    const mode = item.id.startsWith('engineering:')
      ? item.id
      : item.kind === 'image'
        ? 'sem'
        : item.id.startsWith('overlay-')
          ? 'overlay'
          : item.id.startsWith('engineer-inform-')
            ? 'engineer'
            : '';
    setDetailMode(mode);
    navigate(
      target,
      item.kind === 'inform' ? item.id : undefined,
      mode,
      !switchConfirmed,
    );
  }
  async function loadEarlier() {
    if (!room || loadingHistory) return;
    setLoadingHistory(true);
    try {
      const previous = await api<Room>(
        `/rooms/${room.id}?before=${encodeURIComponent(room.oldest_id || room.messages[0]?.id || '')}`,
      );
      skipScroll.current = true;
      setRoom((current) =>
        current?.id === previous.id
          ? {
              ...current,
              messages: [...previous.messages, ...current.messages],
              has_more: previous.has_more,
              oldest_id: previous.oldest_id,
            }
          : current,
      );
    } catch (e) {
      reportError(e);
    } finally {
      setLoadingHistory(false);
    }
  }
  const activeProps = workspace
    ? {
        workspace,
        attach,
        navigate,
        selectedDocument: documentId,
        selectDocument: (id: string | null) => {
          setDocumentId(id);
          const url = new URL(location.href);
          if (id) url.searchParams.set('document', id);
          else url.searchParams.delete('document');
          history.replaceState(null, '', url);
        },
      }
    : null;

  if (showStartupReport && bootstrap?.startup_report) {
    const report = bootstrap.startup_report;
    return <AnalysisReport report={report} workspace={workspace}
      onBoard={() => {
        setShowStartupReport(false);
        navigate('trend');
        const url = new URL(location.href);
        url.searchParams.set('room', report.room_id);
        history.replaceState(null, '', url);
      }}
      onChat={() => location.assign(`/?view=chat&room=${encodeURIComponent(report.room_id)}`)} />;
  }

  return (
    <div
      className={`app-shell ${isChat ? 'chat-view' : 'workbench-view'} ${!isChat && tab === 'trend' ? 'board-view' : ''} ${planCollapsed ? 'plan-collapsed' : ''} ${boardToolsOpen ? 'board-tools-open' : ''}`}
    >
      {sidebarOpen && (
        <button
          className="mobile-scrim"
          aria-label="메뉴 닫기"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <a className="brand" href="/" aria-label="Q-Agent 홈">
          <span className="brand-mark">
            <Focus size={22} strokeWidth={2.2} />
          </span>
          <strong>
            Q-Agent<span>WORKSPACE</span>
          </strong>
        </a>
        <button
          className="new-analysis"
          onClick={createRoom}
          disabled={busy || !bootstrap}
        >
          <Plus size={17} />새 분석<span>+</span>
        </button>
        <button
          className="sidebar-search"
          onClick={() => {
            setModal('search');
            setSidebarOpen(false);
          }}
        >
          <Search size={16} />
          사고 검색<kbd>Ctrl K</kbd>
        </button>
        <div className="sidebar-section-label">WORKSPACE</div>
        <button
          className={`nav-item ${!isChat && tab === 'signals' ? 'active' : ''}`}
          onClick={() => navigate('signals')}
        >
          <Activity size={17} />
          이상 감지
        </button>
        <button
          className={`nav-item ${!isChat && tab !== 'signals' ? 'active' : ''}`}
          onClick={() => navigate('trend')}
        >
          <LayoutDashboard size={17} />
          분석 작업실{!isChat && <span className="nav-active-dot" />}
        </button>
        <button
          className={`nav-item ${isChat ? 'active' : ''}`}
          disabled={!room}
          onClick={() => {
            if (!isChat) launchChat();
            setSidebarOpen(false);
          }}
        >
          <MessageSquare size={17} />
          분석 채팅{isChat && <span className="nav-active-dot" />}
        </button>
        <button className="nav-item" onClick={() => navigate('inform')}>
          <BookOpen size={17} />
          Inform · 회의록
          <span className="nav-count">{workspace?.meetings.length ?? 0}</span>
        </button>
        <button className="nav-item" onClick={() => navigate('production')}>
          <Factory size={17} />
          생산 시스템
        </button>
        <div className="sidebar-section-label conversations-label">
          CONVERSATIONS <span>{bootstrap?.rooms.length ?? 0}</span>
        </div>
        <div className="room-list">
          {bootstrap?.rooms.map((item) => (
            <button
              key={item.id}
              disabled={busy}
              className={`room-item ${item.id === roomId ? 'selected' : ''}`}
              onClick={() => {
                if (room && workspace && !persistReview()) return;
                setRoomId(item.id);
                setSidebarOpen(false);
              }}
            >
              <MessageSquare size={15} />
              <span>
                <strong>{item.title}</strong>
                <small>{item.incident_number}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="sidebar-footer">
          <button
            className="connection-summary"
            onClick={() => setModal('settings')}
          >
            <span className="connection-dot" />
            <span>
              Local workspace<small>합성 데이터 · 로컬 저장</small>
            </span>
            <Settings2 size={16} />
          </button>
          <div className="profile-row">
            <span className="avatar">QA</span>
            <span>
              Quality analyst<small>Demo session</small>
            </span>
            <button
              className="icon-button"
              title="연결 정보"
              onClick={() => setModal('settings')}
            >
              <CircleHelp size={17} />
            </button>
          </div>
        </div>
      </aside>

      <div className="workspace-shell">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button menu-button"
              title="메뉴 열기"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu size={19} />
            </button>
            <span>
              {!isChat && tab === 'trend'
                ? workspace?.incident.incident_number
                : 'Workspace'}
            </span>
            <ChevronRight size={13} />
            <strong>
              {isChat
                ? 'Analysis chat'
                : tab === 'trend'
                  ? room?.title
                  : 'Quality analysis'}
            </strong>
          </div>
          <div className="topbar-actions">
            {!isChat && tab === 'trend' && (
              <button
                className="icon-button"
                title="사고·화면 선택"
                aria-expanded={boardToolsOpen}
                onClick={() => setBoardToolsOpen((value) => !value)}
              >
                <LayoutDashboard size={18} />
              </button>
            )}
            {!isChat && (
              <button
                className="icon-button plan-toggle"
                title="분석 계획 보기/접기"
                onClick={() => {
                  if (
                    tab !== 'trend' &&
                    window.matchMedia('(max-width: 900px)').matches
                  ) {
                    const heading =
                      document.querySelector<HTMLElement>('.inspector-header');
                    heading?.scrollIntoView({ block: 'start' });
                    heading?.focus({ preventScroll: true });
                  } else setPlanCollapsed((value) => !value);
                }}
              >
                {planCollapsed ? (
                  <PanelRightOpen size={18} />
                ) : (
                  <ClipboardList size={18} />
                )}
              </button>
            )}
            <span className="environment-badge">
              <span />
              SYNTHETIC
            </span>
            <button
              className="icon-button"
              title="연결 상태"
              onClick={() => setModal('settings')}
            >
              <Settings2 size={18} />
            </button>
            <span className="topbar-divider" />
            {bootstrap?.startup_report && (
              <button
                className="icon-button"
                title="첫 화면 분석 결과"
                disabled={!room}
                onClick={() => { if (persistReview()) location.assign('/'); }}
              >
                <FileText size={18} />
              </button>
            )}
            <button
              className="outline-button screen-switch"
              disabled={!room}
              onClick={() => (isChat ? navigate('trend') : launchChat())}
            >
              {isChat ? (
                <LayoutDashboard size={15} />
              ) : (
                <MessageSquare size={15} />
              )}
              <span>{isChat ? '분석 작업실' : '채팅 열기'}</span>
              <ArrowUpRight size={13} />
            </button>
          </div>
        </header>
        <div className="content-columns" ref={contentColumns}>
          {!isChat && (
            <main className="analysis-panel">
              <header className="analysis-header">
                <div className="analysis-title-row">
                  <h1 tabIndex={-1}>
                    {room?.title ||
                      (loading ? '분석 불러오는 중' : '새로운 분석')}
                  </h1>
                  <span className="record-pill">
                    {workspace?.incident.incident_number || 'NEW'}
                  </span>
                  <button
                    className="icon-button"
                    title="대화방 이름 변경"
                    disabled={!room || busy}
                    onClick={() => {
                      setRename(room?.title || '');
                      setModal('rename');
                    }}
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    className="icon-button export-button"
                    title="현재 조회 결과 다운로드"
                    disabled={!room || !workspace}
                    onClick={() =>
                      download(
                        `${workspace?.incident.incident_number}-workspace.json`,
                        JSON.stringify(
                          { synthetic: true, room, workspace },
                          null,
                          2,
                        ),
                      )
                    }
                  >
                    <ArrowDownToLine size={17} />
                  </button>
                </div>
                <div className="scope-row">
                  <button
                    className="scope-select"
                    onClick={() => setModal('search')}
                    disabled={busy}
                  >
                    <Database size={13} />
                    <span>{workspace?.incident.title || '사고 선택'}</span>
                    <ChevronDown size={13} />
                  </button>
                  <span className="scope-date">
                    회의록 기준 {workspace?.as_of || '2026-03-31'}
                  </span>
                </div>
                {workspace && (
                  <div className="scope-facts">
                    <span>
                      <Factory size={13} />
                      {workspace.incident.department} ·{' '}
                      {workspace.incident.line}
                    </span>
                    <span>
                      발생 {workspace.incident.occurred_at.slice(0, 10)}
                    </span>
                    <span className="scope-source">합성 DB · 읽기 전용</span>
                  </div>
                )}
              </header>
              <nav className="workspace-tabs" aria-label="분석 보기">
                <label className="mobile-view-picker">
                  <span>개별 보기</span>
                  <select
                    aria-label="분석 화면 선택"
                    value={tab}
                    onChange={(event) => navigate(event.target.value as Tab)}
                  >
                    {tabs.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.label}
                        {item.id === 'review' && attachments.length
                          ? ` (${attachments.length})`
                          : ''}
                      </option>
                    ))}
                  </select>
                </label>
                {tabs
                  .filter((item) =>
                    ['trend', 'signals', 'review'].includes(item.id),
                  )
                  .map((item) => (
                    <button
                      key={item.id}
                      className={tab === item.id ? 'active' : ''}
                      aria-current={tab === item.id ? 'page' : undefined}
                      onClick={() => navigate(item.id)}
                    >
                      <item.icon size={16} />
                      <span>{item.label}</span>
                      {item.id === 'inform' && workspace && (
                        <small>{workspace.meetings.length}</small>
                      )}
                      {item.id === 'review' && attachments.length > 0 && (
                        <small>{attachments.length}</small>
                      )}
                    </button>
                  ))}
              </nav>
              {error && (
                <div className="error-banner" role="alert">
                  <span>{error}</span>
                  {storageError && (
                    <button
                      className="icon-button"
                      title="초안 JSON 다운로드"
                      onClick={downloadDraft}
                    >
                      <ArrowDownToLine size={17} />
                    </button>
                  )}
                  <button
                    className="text-button"
                    onClick={() => {
                      if (room && workspace && !persistReview()) return;
                      setError('');
                      if (roomId) setReload((r) => r + 1);
                      else location.reload();
                    }}
                  >
                    다시 불러오기
                  </button>
                  <button
                    className="icon-button"
                    title="오류 닫기"
                    onClick={() => setError('')}
                  >
                    <X size={15} />
                  </button>
                </div>
              )}
              <div className="analysis-scroll">
                {loading ? (
                  <div className="loading-state">
                    <Loader2 className="spin" size={25} />
                    <span>분석 데이터 조회 중</span>
                  </div>
                ) : !activeProps ? (
                  <div className="empty-workspace">
                    <Empty title="새 분석" detail="선택된 분석이 없습니다." />
                    <button
                      className="primary-button"
                      disabled={busy}
                      onClick={createRoom}
                    >
                      <Plus size={16} />새 분석
                    </button>
                  </div>
                ) : (
                  <EngineeringWorkspace
                    key={`${roomId}:${workspace!.incident.incident_number}`}
                    {...activeProps}
                    roomId={roomId}
                    onConversationChange={() => {
                      void api<Room>(`/rooms/${roomId}`)
                        .then((value) =>
                          setRoom((current) =>
                            current?.id === value.id ? value : current,
                          ),
                        )
                        .catch(reportError);
                      void refreshRooms().catch(reportError);
                    }}
                    tab={tab}
                    reference={detailMode}
                    attachments={attachments}
                    notes={notes}
                    onNotes={setNotes}
                    onRemoveAttachment={(item) =>
                      setAttachments((current) =>
                        current.filter(
                          (row) =>
                            row.id !== item.id ||
                            row.kind !== item.kind ||
                            row.incident_number !== item.incident_number,
                        ),
                      )
                    }
                    onOpenAttachment={openAttachment}
                    storageError={storageError}
                    incidents={bootstrap?.incidents || []}
                    prepare={(question) => {
                      setDraft(question);
                      setNotice('현재 조사 조건으로 채팅 질문을 준비했습니다.');
                    }}
                  >
                    {(context) => (
                      <>
                        {tab === 'overview' && <Overview {...activeProps} />}
                        {tab === 'map' && (
                          <Images
                            key={detailMode}
                            {...activeProps}
                            initialWafer={context.initialWafer}
                            initialMode={detailMode}
                          />
                        )}
                        {tab === 'inform' && (
                          <InformWorkspace
                            key={detailMode}
                            {...activeProps}
                            initialMode={detailMode}
                          />
                        )}
                        {tab === 'history' && (
                          <HistoryView
                            {...activeProps}
                            incidents={bootstrap?.incidents || []}
                          />
                        )}
                        {tab === 'data' && <DataView {...activeProps} />}
                        {tab === 'review' && (
                          <ReviewView
                            workspace={workspace!}
                            attachments={attachments}
                            question={draft}
                            notes={notes}
                            setNotes={setNotes}
                            open={openAttachment}
                            remove={(index) =>
                              setAttachments((items) =>
                                items.filter((_, i) => i !== index),
                              )
                            }
                            storageError={storageError}
                          />
                        )}
                      </>
                    )}
                  </EngineeringWorkspace>
                )}
                <footer className="analysis-footer">
                  <ShieldCheck size={13} />
                  <span>Read-only · 합성 DB</span>
                  <span>{bootstrap?.release || 'Q-Agent'}</span>
                </footer>
              </div>
            </main>
          )}

          {!isChat && (
            <aside className="investigation-panel" aria-label="분석 검토 목록">
              <header className="inspector-header" tabIndex={-1}>
                <ClipboardList size={17} />
                <h2>Investigation plan</h2>
                <span className="status-tag">수동 검토</span>
                <button
                  className="icon-button"
                  title="분석 화면 넓게 보기"
                  onClick={() => {
                    if (
                      tab !== 'trend' &&
                      window.matchMedia('(max-width: 900px)').matches
                    ) {
                      contentColumns.current?.scrollTo(0, 0);
                      document
                        .querySelector<HTMLElement>('.analysis-title-row h1')
                        ?.focus();
                    } else setPlanCollapsed(true);
                  }}
                >
                  <PanelRightClose size={16} />
                </button>
              </header>
              <div className="inspector-scroll">
                {room && (
                  <PlanPanel
                    key={room.id}
                    roomId={room.id}
                    disabled={busy || !workspace}
                    navigate={navigate}
                    prepare={(labels) => {
                      setDraft(
                        `${workspace?.incident.incident_number}의 ${labels.join(', ')} 내용을 확인해줘.`,
                      );
                      setNotice('선택한 항목으로 질문을 준비했습니다.');
                    }}
                  />
                )}
                <section className="review-section">
                  <div className="section-title">
                    <button
                      className="review-open"
                      onClick={() => navigate('review')}
                    >
                      <h2>검토 대상</h2>
                      <ArrowUpRight size={15} />
                    </button>
                    <span className="review-count">
                      {attachments.length} / 8
                    </span>
                  </div>
                  {attachments.length ? (
                    <div className="review-items">
                      {attachments.map((item, i) => (
                        <div key={`${item.id}-${i}`}>
                          <button onClick={() => openAttachment(item)}>
                            <Link2 size={13} />
                            <span>
                              {item.label}
                              <small>{item.incident_number}</small>
                            </span>
                          </button>
                          <button
                            className="icon-button"
                            title={`${item.label} 선택 제거`}
                            onClick={() =>
                              setAttachments((items) =>
                                items.filter((_, index) => index !== i),
                              )
                            }
                          >
                            <X size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="review-empty">
                      <Link2 size={20} />
                      <span>선택된 근거 없음</span>
                    </div>
                  )}
                  {attachments.length > 0 && (
                    <button
                      className="outline-button review-all"
                      onClick={() => navigate('review')}
                    >
                      <FileText size={14} />
                      근거 검토 · 비교
                    </button>
                  )}
                  {storageError && (
                    <p className="save-error" role="status">
                      브라우저 저장 실패 · 기록 다운로드 필요
                    </p>
                  )}
                </section>
                {draft && (
                  <section className="review-section prepared-question">
                    <div className="section-title">
                      <h2>준비한 질문</h2>
                      <button
                        className="icon-button"
                        title="준비한 질문 지우기"
                        onClick={() => setDraft('')}
                      >
                        <X size={14} />
                      </button>
                    </div>
                    <textarea
                      aria-label="준비한 질문"
                      value={draft}
                      maxLength={12000}
                      onChange={(e) => setDraft(e.target.value)}
                    />
                  </section>
                )}
                <section className="review-section source-status">
                  <div className="section-title">
                    <h2>Source status</h2>
                    <button
                      className="icon-button"
                      title="전체 연결 상태"
                      onClick={() => setModal('settings')}
                    >
                      <Settings2 size={15} />
                    </button>
                  </div>
                  <div>
                    <Database size={14} />
                    <span>사고 · Lot · Wafer</span>
                    <small>합성 DB</small>
                  </div>
                  <div>
                    <FileText size={14} />
                    <span>승인 회의록</span>
                    <small>{workspace?.meetings.length || 0} chunks</small>
                  </div>
                  <div>
                    <Focus size={14} />
                    <span>Trend · Map · SEM</span>
                    <small className="amber-text">합성</small>
                  </div>
                  <div>
                    <Factory size={14} />
                    <span>사내 생산 시스템</span>
                    <small className="offline-text">미연결</small>
                  </div>
                </section>
              </div>
              <footer className="inspector-bottom">
                <button
                  className="primary-button"
                  disabled={!room || busy}
                  onClick={launchChat}
                >
                  <MessageSquare size={16} />
                  채팅에서 이어가기
                  <ArrowUpRight size={15} />
                </button>
                <span>
                  {attachments.length
                    ? `근거 ${attachments.length}개 선택`
                    : '선택된 근거 없음'}{' '}
                  · {room?.incident_number || '사고 미선택'}
                </span>
              </footer>
            </aside>
          )}

          {isChat && (
            <main className="chat-panel" aria-label="분석 채팅">
              <header className="chat-header">
                <span className="agent-mark">
                  <Sparkles size={18} />
                </span>
                <div>
                  <h2>{room?.title || 'Analysis chat'}</h2>
                  <span>
                    <i />
                    {bootstrap?.llm_configured
                      ? `LLM · ${bootstrap.models?.router || '설정됨'}`
                      : 'Demo 조회 · LLM 미연결'}
                  </span>
                </div>
                <button
                  className="icon-button"
                  title="실행 연결 상태"
                  onClick={() => setModal('run')}
                >
                  <Activity size={18} />
                </button>
                <button
                  className="icon-button"
                  title="사고 범위 선택"
                  disabled={!room || busy}
                  onClick={() => setModal('search')}
                >
                  <Database size={18} />
                </button>
              </header>
              <div className="chat-context">
                <Link2 size={13} />
                <span>
                  {workspace?.incident.incident_number || '사고 미선택'}
                </span>
                <span className="context-spacer" />
                <span>{room?.messages.length || 0} messages</span>
                <button
                  className="icon-button"
                  title="대화방 관리"
                  disabled={!room || busy}
                  onClick={() => {
                    setRename(room?.title || '');
                    setModal('rename');
                  }}
                >
                  <MoreHorizontal size={16} />
                </button>
              </div>
              {error && (
                <div className="error-banner" role="alert">
                  <span>{error}</span>
                  {storageError && (
                    <button
                      className="icon-button"
                      title="초안 JSON 다운로드"
                      onClick={downloadDraft}
                    >
                      <ArrowDownToLine size={17} />
                    </button>
                  )}
                  <button
                    className="icon-button"
                    title="오류 닫기"
                    onClick={() => setError('')}
                  >
                    <X size={15} />
                  </button>
                </div>
              )}
              <div className="messages" aria-live="polite">
                {loading && (
                  <div className="loading-state">
                    <Loader2 className="spin" size={25} />
                    대화 불러오는 중
                  </div>
                )}
                {!loading && !room && (
                  <div className="empty-workspace">
                    <Empty title="대화 없음" detail="선택된 분석이 없습니다." />
                    <button className="primary-button" onClick={createRoom}>
                      <Plus size={16} />새 분석
                    </button>
                  </div>
                )}
                {room?.has_more && (
                  <button
                    className="earlier-messages text-button"
                    disabled={loadingHistory}
                    onClick={loadEarlier}
                  >
                    {loadingHistory ? '불러오는 중' : '이전 대화 불러오기'}
                  </button>
                )}
                <div className="conversation-date">
                  <span />
                  {room?.messages[0]?.created_at?.slice(0, 10) || '새 대화'}
                  <span />
                </div>
                {room?.messages.map((message) => (
                  <div className={`message ${message.role}`} key={message.id}>
                    {message.role === 'assistant' && (
                      <div className="message-author">
                        <span className="small-agent-mark">
                          <Focus size={13} />
                        </span>
                        Q-Agent <small>합성 DB 조회</small>
                      </div>
                    )}
                    <div className="message-content">
                      {message.content
                        .split('\n')
                        .map((line, i) =>
                          line ? (
                            <p key={i}>{line}</p>
                          ) : (
                            <div className="paragraph-gap" key={i} />
                          ),
                        )}
                    </div>
                    {!!message.attachments?.length && (
                      <div className="message-attachments">
                        {message.attachments.map((item, i) => (
                          <button
                            key={`${item.id}-${i}`}
                            onClick={() => openAttachment(item)}
                          >
                            <Link2 size={11} />
                            <span>{item.label}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {message.role === 'assistant' && (
                      <div className="message-actions">
                        <button
                          className="text-button"
                          onClick={async () => {
                            try {
                              await navigator.clipboard.writeText(
                                message.content,
                              );
                              setCopied(message.id);
                            } catch {
                              setNotice('클립보드에 접근할 수 없습니다.');
                            }
                          }}
                        >
                          {copied === message.id ? (
                            <Check size={12} />
                          ) : (
                            <FileText size={12} />
                          )}
                          {copied === message.id ? '복사됨' : '복사'}
                        </button>
                        <time>{message.created_at?.slice(11, 16)}</time>
                      </div>
                    )}
                  </div>
                ))}
                {room && !room.messages.length && (
                  <div className="chat-empty">
                    <Focus size={28} strokeWidth={1.4} />
                    <h3>어떤 내용을 확인할까요?</h3>
                    <p>
                      {workspace?.incident.incident_number}의 기록과 근거를
                      조회할 수 있습니다.
                    </p>
                  </div>
                )}
                {busy && (
                  <div className="query-progress">
                    <Loader2 className="spin" size={14} />
                    <span>데이터 조회 · 대화 저장 중</span>
                  </div>
                )}
                <div ref={end} />
              </div>
              <div className="chat-bottom">
                <div className="suggestions">
                  {['관련 Lot 보여줘', '회의록 근거 확인'].map((text) => (
                    <button
                      key={text}
                      disabled={busy || !room}
                      onClick={() => {
                        setDraft(text);
                        composer.current?.focus();
                      }}
                    >
                      {text}
                      <ChevronRight size={12} />
                    </button>
                  ))}
                </div>
                <form className="composer" onSubmit={send}>
                  {!!attachments.length && (
                    <div className="composer-attachments">
                      {attachments.map((item, i) => (
                        <span key={`${item.id}-${i}`}>
                          <Link2 size={12} />
                          <span>{item.label}</span>
                          <button
                            type="button"
                            aria-label={`${item.label} 첨부 제거`}
                            onClick={() =>
                              setAttachments((values) =>
                                values.filter((_, index) => index !== i),
                              )
                            }
                          >
                            <X size={12} />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                  <textarea
                    ref={composer}
                    aria-label="질문 입력"
                    maxLength={12000}
                    value={draft}
                    disabled={busy || !room}
                    placeholder="이 사고에 대해 이어서 질문하세요…"
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (
                        e.key === 'Enter' &&
                        !e.shiftKey &&
                        !e.nativeEvent.isComposing
                      ) {
                        e.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <div className="composer-footer">
                    <button
                      type="button"
                      className="icon-button"
                      title="작업실에서 근거 선택"
                      disabled={!workspace}
                      onClick={() => navigate('inform')}
                    >
                      <Plus size={18} />
                    </button>
                    <span>
                      선택 사고 · {workspace?.incident.incident_number}
                    </span>
                    <button
                      type="submit"
                      className="send-button"
                      aria-label="질문 보내기"
                      disabled={!draft.trim() || busy || !room}
                    >
                      {busy ? (
                        <Loader2 className="spin" size={17} />
                      ) : (
                        <ArrowUp size={18} />
                      )}
                    </button>
                  </div>
                </form>
                <div className="chat-disclaimer">
                  <ShieldCheck size={11} />
                  {bootstrap?.llm_configured
                    ? '로컬 대화 저장 · 합성 DB · LLM 답변'
                    : '로컬 대화 저장 · 실제 LLM 답변 아님'}
                </div>
              </div>
            </main>
          )}
        </div>
      </div>
      {notice && (
        <div className="toast" role="status">
          <Check size={15} />
          {notice}
        </div>
      )}
      {modal === 'attachment' && pendingAttachment && (
        <Modal title="이전 사고의 근거" close={() => setModal(null)}>
          <p className="modal-note">
            이 항목은 {pendingAttachment.incident_number}의 근거입니다. 해당
            사고로 조회 범위를 전환할까요? 기존 대화는 보존됩니다.
          </p>
          <div className="modal-actions">
            <button className="outline-button" onClick={() => setModal(null)}>
              취소
            </button>
            <button
              className="primary-button"
              disabled={busy}
              onClick={() => openAttachment(pendingAttachment, true)}
            >
              사고 전환 후 열기
            </button>
          </div>
        </Modal>
      )}
      {modal === 'search' && (
        <Modal
          title="사고 검색"
          close={() => {
            setModal(null);
            setSearch('');
          }}
        >
          <div className="modal-search">
            <Search size={18} />
            <input
              autoFocus
              placeholder="사고번호, 제목, 부서 검색"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="사고 검색어"
            />
          </div>
          <div className="incident-options">
            {bootstrap?.incidents
              .filter((i) =>
                `${i.title} ${i.incident_number} ${i.department}`
                  .toLowerCase()
                  .includes(search.toLowerCase()),
              )
              .map((i) => (
                <button
                  disabled={busy || !roomId}
                  key={i.incident_id}
                  onClick={() => selectIncident(i.incident_number)}
                >
                  <span className="incident-option-icon">
                    <Database size={18} />
                  </span>
                  <span>
                    <strong>{i.title}</strong>
                    <small>
                      {i.incident_number} · {i.occurred_at?.slice(0, 10)}
                    </small>
                  </span>
                  {workspace?.incident.incident_number === i.incident_number ? (
                    <Check size={16} />
                  ) : (
                    <ChevronRight size={16} />
                  )}
                </button>
              ))}
          </div>
          <p className="modal-note">
            선택 근거와 메모는 사고별로 분리해 보관합니다. 기존 대화 기록은
            보존됩니다.
          </p>
        </Modal>
      )}
      {modal === 'rename' && (
        <Modal title="대화방 관리" close={() => setModal(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void manageRoom('rename');
            }}
          >
            <label className="form-label">
              이름
              <input
                autoFocus
                value={rename}
                maxLength={120}
                onChange={(e) => setRename(e.target.value)}
              />
            </label>
            <div className="modal-actions">
              <button
                type="button"
                className="text-button danger"
                disabled={busy}
                onClick={() => setModal('delete')}
              >
                <Trash2 size={15} />
                대화 삭제
              </button>
              <button
                className="primary-button"
                disabled={busy || !rename.trim()}
              >
                저장
              </button>
            </div>
          </form>
        </Modal>
      )}
      {modal === 'delete' && (
        <Modal title="대화를 삭제할까요?" close={() => setModal(null)}>
          <p className="modal-note">
            “{room?.title}”의 질문과 답변이 삭제됩니다. 사고 DB와 원본 문서는
            변경되지 않습니다.
          </p>
          <div className="modal-actions">
            <button className="outline-button" onClick={() => setModal(null)}>
              취소
            </button>
            <button
              className="danger-button"
              disabled={busy}
              onClick={() => manageRoom('delete')}
            >
              대화 삭제
            </button>
          </div>
        </Modal>
      )}
      {modal === 'settings' && (
        <Modal title="Workspace connections" close={() => setModal(null)}>
          <div className="connection-list">
            {[
              ['사고 DB', '합성 SQLite · 읽기 전용', true],
              ['회의록', '합성 FTS5 · BM25', true],
              ['대화 저장', '로컬 SQLite', true],
              ['Router / Judge / Answer', '모델 API 미연결', false],
              ['Hybrid RAG', '사내 서비스 미연결', false],
              ['Trend / Map', '합성 시각화 · 원본 서비스 미연결', false],
            ].map(([name, description, connected]) => (
              <div key={String(name)}>
                <span
                  className={`connection-dot ${connected ? '' : 'offline'}`}
                />
                <div>
                  <strong>{name}</strong>
                  <span>{description}</span>
                </div>
              </div>
            ))}
          </div>
          <p className="modal-note">
            단일 사용자 로컬 데모입니다. 사내 로그인·사용자별 권한·모델 서버
            배포는 별도로 연결해야 합니다.
          </p>
          <code className="release-label">{bootstrap?.release}</code>
        </Modal>
      )}
      {modal === 'run' && (
        <Modal title="Agent execution" close={() => setModal(null)}>
          <div className="execution-list">
            {[
              ['Router', bootstrap?.models?.router || '모델 미연결'],
              ['사고 DB', '합성 DB 조회 가능'],
              ['후속 Tool', 'Lot · Wafer · 회의록'],
              ['Judge', bootstrap?.models?.judge || '모델 미연결'],
              ['Answer', bootstrap?.models?.answer || '모델 미연결'],
              [
                '최종 조회 상태',
                bootstrap?.llm_configured
                  ? '각 답변의 조회 근거와 제한 사항 확인'
                  : 'Demo 조회 결과 · 실제 Agent 판정 아님',
              ],
            ].map(([label, status], i) => (
              <div key={label}>
                <span>{String(i + 1).padStart(2, '0')}</span>
                <div>
                  <strong>{label}</strong>
                  <small>{status}</small>
                </div>
              </div>
            ))}
          </div>
          <p className="modal-note">
            {bootstrap?.llm_configured
              ? '합성 DB를 조회하는 LLM 분석입니다. 실제 생산계 및 이미지 모델은 미연결입니다.'
              : '현재 채팅은 데이터 조회 데모입니다. LLM 실행이나 Judge 통과를 모사하지 않습니다.'}
          </p>
        </Modal>
      )}
    </div>
  );
}

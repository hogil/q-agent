import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
  type PointerEvent,
} from 'react';
import {
  Maximize2,
  MoveDiagonal,
  MoveDiagonal2,
  MoveHorizontal,
  MoveVertical,
  X,
} from 'lucide-react';
import {
  defaultLayout,
  fitLayout,
  layoutStorageKey,
  minimumFractions,
  minColumns,
  minRows,
  moveBoundary,
  panelRows,
  parseLayout,
  type BoardLayout,
} from './boardLayout';
import './resizableBoard.css';

type Corner = 'nw' | 'ne' | 'sw' | 'se';
const corners: Corner[] = ['nw', 'ne', 'sw', 'se'];
const cornerNames = {
  nw: '왼쪽 위',
  ne: '오른쪽 위',
  sw: '왼쪽 아래',
  se: '오른쪽 아래',
};
const focusableSelector = [
  'a[href]',
  'area[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'iframe',
  'object',
  'embed',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');
type PanelProps = {
  children: ReactNode;
  'data-panel': string;
  'aria-label'?: string;
  'aria-hidden'?: boolean;
  'aria-modal'?: boolean;
  className?: string;
  inert?: boolean;
  role?: string;
};
type Drag = {
  pointer: number;
  x: number;
  y: number;
  row: number;
  columnBoundary: number;
  rowBoundary: number;
  layout: BoardLayout;
  width: number;
  height: number;
};

export default function ResizableBoard({
  children,
  locked,
  resetKey,
  onStorageError,
}: {
  children: ReactNode;
  locked: boolean;
  resetKey: number;
  onStorageError: (failed: boolean) => void;
}) {
  const grid = useRef<HTMLDivElement>(null);
  const preferred = useRef(defaultLayout());
  const current = useRef(preferred.current);
  const drag = useRef<Drag | null>(null);
  const frame = useRef(0);
  const closeButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const [active, setActive] = useState(false);
  const [expandedPanel, setExpandedPanel] = useState<string | null>(null);
  const storageCallback = useRef(onStorageError);
  storageCallback.current = onStorageError;

  function paint(layout: BoardLayout) {
    current.current = layout;
    const style = grid.current?.style;
    if (!style) return;
    style.setProperty(
      '--board-rows',
      layout.rows.map((n) => `minmax(0, ${n}fr)`).join(' '),
    );
    layout.columns.forEach((sizes, i) =>
      style.setProperty(
        `--board-columns-${i}`,
        sizes.map((n) => `minmax(0, ${n}fr)`).join(' '),
      ),
    );
  }
  function persist(layout: BoardLayout) {
    preferred.current = layout;
    try {
      localStorage.setItem(
        layoutStorageKey,
        JSON.stringify({ version: 1, ...layout }),
      );
      storageCallback.current(false);
    } catch {
      storageCallback.current(true);
    }
  }
  useEffect(() => {
    try {
      preferred.current =
        parseLayout(localStorage.getItem(layoutStorageKey)) || defaultLayout();
    } catch {
      storageCallback.current(true);
    }
    const resize = () => {
      if (!grid.current || drag.current) return;
      paint(
        fitLayout(
          preferred.current,
          grid.current.clientWidth,
          grid.current.clientHeight,
        ),
      );
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(grid.current!);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame.current);
    };
  }, []);
  useEffect(() => {
    if (!resetKey || !grid.current) return;
    const layout = defaultLayout();
    persist(layout);
    paint(
      fitLayout(layout, grid.current.clientWidth, grid.current.clientHeight),
    );
  }, [resetKey]);

  function adjust(start: Drag, dx: number, dy: number) {
    const columns = start.layout.columns.map((row) => [...row]);
    const columnPixels = start.width - columns[start.row].length + 1;
    columns[start.row] = moveBoundary(
      columns[start.row],
      start.columnBoundary,
      dx / columnPixels,
      minimumFractions(minColumns[start.row], columnPixels),
    );
    return {
      rows: moveBoundary(
        start.layout.rows,
        start.rowBoundary,
        dy / (start.height - 2),
        minimumFractions(minRows, start.height - 2),
      ),
      columns,
    };
  }
  function stop(cancel = false) {
    const start = drag.current;
    if (!start) return;
    cancelAnimationFrame(frame.current);
    if (cancel) paint(start.layout);
    else persist(current.current);
    drag.current = null;
    setActive(false);
  }
  useEffect(() => {
    if (!active) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        stop(true);
      }
    };
    const blur = () => stop(true);
    window.addEventListener('keydown', escape);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('keydown', escape);
      window.removeEventListener('blur', blur);
    };
  }, [active]);

  useLayoutEffect(() => {
    if (expandedPanel) {
      closeButton.current?.focus({ preventScroll: true });
      return;
    }
    const target = restoreFocus.current;
    restoreFocus.current = null;
    if (target?.isConnected) target.focus({ preventScroll: true });
  }, [expandedPanel]);

  useEffect(() => {
    if (!expandedPanel) return;
    const panel = () =>
      grid.current?.querySelector<HTMLElement>(
        `[data-panel="${CSS.escape(expandedPanel)}"]`,
      );
    const nativeDialogOpen = () =>
      document.querySelector('dialog[open]') !== null;
    const trapFocus = (event: FocusEvent) => {
      if (nativeDialogOpen()) return;
      const surface = panel();
      if (!surface || surface.contains(event.target as Node)) return;
      closeButton.current?.focus({ preventScroll: true });
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || nativeDialogOpen()) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        setExpandedPanel(null);
        return;
      }
      if (event.key !== 'Tab') return;
      const surface = panel();
      if (!surface) return;
      const focusable = Array.from(
        surface.querySelectorAll<HTMLElement>(focusableSelector),
      ).filter(
        (element) =>
          element.offsetWidth > 0 ||
          element.offsetHeight > 0 ||
          element === document.activeElement,
      );
      if (!focusable.length) {
        event.preventDefault();
        closeButton.current?.focus({ preventScroll: true });
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const currentFocus = document.activeElement;
      if (
        event.shiftKey
          ? currentFocus === first
          : currentFocus === last
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus({ preventScroll: true });
      }
    };
    document.addEventListener('focusin', trapFocus, true);
    document.addEventListener('keydown', handleKeyDown, true);
    return () => {
      document.removeEventListener('focusin', trapFocus, true);
      document.removeEventListener('keydown', handleKeyDown, true);
    };
  }, [expandedPanel]);

  useEffect(() => {
    if (!expandedPanel) return;
    const surface = Array.from(
      grid.current?.querySelectorAll<HTMLElement>('.board-panel') || [],
    ).find((element) => element.dataset.panel === expandedPanel);
    if (!surface) return;

    const previousInert = new Map<HTMLElement, boolean>();
    let current: HTMLElement | null = surface;
    while (current?.parentElement) {
      const parent: HTMLElement = current.parentElement;
      Array.from(parent.children).forEach((child) => {
        if (!(child instanceof HTMLElement) || child === current) return;
        if (
          child.matches('.board-panel, .board-expansion-backdrop') ||
          child.matches('dialog') ||
          child.querySelector('dialog')
        )
          return;
        previousInert.set(child, child.inert);
        child.inert = true;
      });
      if (parent === document.body) break;
      current = parent;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
      previousInert.forEach((value, element) => {
        element.inert = value;
      });
    };
  }, [expandedPanel]);

  const panels = new Map<string, ReactElement<PanelProps>>();
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    const element = child as ReactElement<PanelProps>;
    panels.set(element.props['data-panel'], element);
  });
  const expandedTitle = expandedPanel
    ? panels.get(expandedPanel)?.props['aria-label'] || expandedPanel
    : '';
  const expansionControl = (
    panel: ReactElement<PanelProps>,
    expanded: boolean,
  ) => {
    const title = panel.props['aria-label'] || panel.props['data-panel'];
    return (
      <button
        type="button"
        className="icon-button board-expand-button"
        title={expanded ? `${title} 닫기` : `${title} 크게 보기`}
        aria-label={expanded ? `${title} 닫기` : `${title} 크게 보기`}
        ref={expanded ? closeButton : undefined}
        onClick={(event) => {
          event.stopPropagation();
          if (expanded) {
            setExpandedPanel(null);
            return;
          }
          restoreFocus.current = event.currentTarget;
          setExpandedPanel(panel.props['data-panel']);
        }}
      >
        {expanded ? (
          <X size={14} aria-hidden="true" />
        ) : (
          <Maximize2 size={14} aria-hidden="true" />
        )}
      </button>
    );
  };
  const panelChildren = (
    panel: ReactElement<PanelProps>,
    expanded: boolean,
  ): { children: ReactNode; rootControl: ReactNode } => {
    const children = panel.props.children;
    const control = expansionControl(panel, expanded);
    if (Array.isArray(children)) {
      const headerIndex = children.findIndex(
        (child) => isValidElement(child) && child.type === 'header',
      );
      if (headerIndex >= 0) {
        const header = children[headerIndex] as ReactElement<{
          children?: ReactNode;
        }>;
        return {
          children: children.map((child, index) =>
            index === headerIndex
              ? cloneElement(header, {}, header.props.children, control)
              : child,
          ),
          rootControl: null,
        };
      }
    } else if (isValidElement(children) && children.type === 'header') {
      const header = children as ReactElement<{ children?: ReactNode }>;
      return {
        children: cloneElement(header, {}, header.props.children, control),
        rootControl: null,
      };
    }
    return { children, rootControl: control };
  };
  const handles = (
    panel: ReactElement<PanelProps>,
    row: number,
    column: number,
  ) =>
    corners.map((corner) => {
      const xb = corner.endsWith('e') ? column : column - 1;
      const yb = corner.startsWith('s') ? row : row - 1;
      const x = xb >= 0 && xb < panelRows[row].length - 1;
      const y = yb >= 0 && yb < panelRows.length - 1;
      if (!x && !y) return null;
      const label = `${panel.props['aria-label'] || panel.props['data-panel']} ${cornerNames[corner]} 크기 조절`;
      const Icon = !x
        ? MoveVertical
        : !y
          ? MoveHorizontal
          : corner === 'nw' || corner === 'se'
            ? MoveDiagonal2
            : MoveDiagonal;
      const snapshot = (): Drag => ({
        pointer: -1,
        x: 0,
        y: 0,
        row,
        columnBoundary: x ? xb : -1,
        rowBoundary: y ? yb : -1,
        layout: current.current,
        width: grid.current!.clientWidth,
        height: grid.current!.clientHeight,
      });
      return (
        <button
          key={corner}
          type="button"
          className={`board-resize-handle ${corner} ${!x ? 'vertical' : !y ? 'horizontal' : 'diagonal'}`}
          title={label}
          aria-label={label}
          disabled={locked || expandedPanel !== null}
          onPointerDown={(event: PointerEvent<HTMLButtonElement>) => {
            if (locked || event.button !== 0 || !event.isPrimary) return;
            event.preventDefault();
            event.stopPropagation();
            event.currentTarget.focus({ preventScroll: true });
            drag.current = {
              ...snapshot(),
              pointer: event.pointerId,
              x: event.clientX,
              y: event.clientY,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            setActive(true);
          }}
          onPointerMove={(event) => {
            const start = drag.current;
            if (!start || start.pointer !== event.pointerId) return;
            event.preventDefault();
            event.stopPropagation();
            const dx = event.clientX - start.x,
              dy = event.clientY - start.y;
            cancelAnimationFrame(frame.current);
            frame.current = requestAnimationFrame(() =>
              paint(adjust(start, dx, dy)),
            );
          }}
          onPointerUp={(event) => {
            const start = drag.current;
            if (!start || start.pointer !== event.pointerId) return;
            cancelAnimationFrame(frame.current);
            paint(
              adjust(start, event.clientX - start.x, event.clientY - start.y),
            );
            stop();
            event.currentTarget.releasePointerCapture(event.pointerId);
          }}
          onPointerCancel={() => stop(true)}
          onLostPointerCapture={() => stop(true)}
          onKeyDown={(event) => {
            if (
              !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(
                event.key,
              ) ||
              drag.current
            )
              return;
            event.preventDefault();
            event.stopPropagation();
            const step = event.shiftKey ? 40 : 10;
            const next = adjust(
              snapshot(),
              event.key === 'ArrowLeft'
                ? -step
                : event.key === 'ArrowRight'
                  ? step
                  : 0,
              event.key === 'ArrowUp'
                ? -step
                : event.key === 'ArrowDown'
                  ? step
                  : 0,
            );
            paint(next);
            persist(next);
          }}
        >
          <Icon size={12} aria-hidden="true" />
        </button>
      );
    });
  return (
    <div
      ref={grid}
      className={`board-grid board-layout ${locked ? 'layout-locked' : ''} ${active ? 'layout-resizing' : ''} ${expandedPanel ? 'layout-expanded' : ''}`}
    >
      {panelRows.map((row, rowIndex) => (
        <div className={`board-layout-row row-${rowIndex}`} key={rowIndex}>
          {row.map((id, column) => {
            const panel = panels.get(id);
            if (!panel) return null;
            const expanded = expandedPanel === id;
            const content = panelChildren(panel, expanded);
            return cloneElement(
              panel,
              {
                key: id,
                className: `${panel.props.className || ''}${expanded ? ' board-panel-expanded' : ''}`.trim(),
                role: expanded ? 'dialog' : panel.props.role,
                'aria-modal': expanded ? true : undefined,
                'aria-hidden': expandedPanel !== null && !expanded,
                inert: expandedPanel !== null && !expanded,
              },
              content.children,
              content.rootControl,
              handles(panel, rowIndex, column),
            );
          })}
        </div>
      ))}
      {expandedPanel && (
        <button
          type="button"
          className="board-expansion-backdrop"
          aria-label={`${expandedTitle} 닫기`}
          tabIndex={-1}
          onPointerDown={(event) => event.preventDefault()}
          onClick={() => setExpandedPanel(null)}
        />
      )}
    </div>
  );
}

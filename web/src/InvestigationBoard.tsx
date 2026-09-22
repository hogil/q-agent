import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { CustomSeriesRenderItem } from 'echarts';
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpRight,
  RotateCcw,
  Pin,
  Check,
  X,
  Columns2,
  ListFilter,
  Copy,
  Search,
  ListRestart,
  LockKeyhole,
  UnlockKeyhole,
  PanelsTopLeft,
} from 'lucide-react';
import { download, type Attachment, type Incident } from './api';
import { Chart } from './charts';
import {
  metricUnits,
  summarizeTrendSamples,
  trendBoxPlotOption,
} from './anomalyTrend';
import type { ViewProps } from './Views';
import {
  pairKey,
  analysisTrendSelection,
  selectFabRows,
  selectTrendFabRows,
  engineeringReference,
  changeTiming,
  signalFabScope,
  type InvestigationSelection,
} from './engineeringAnalysis';
import {
  signalMember,
  signalAxisLabel,
  type EngineeringData,
  type FabRow,
  type Signal,
} from './engineeringData';
import {
  compositeWaferMaps,
  inspectWaferDie,
  selectDieRegion,
  type DieRegion,
  waferData,
  waferSeed,
  waferCoordinateText,
} from './waferMaps';
import HistoricalCorrelation from './HistoricalCorrelation';
import { EquipmentStateTimeline } from './EquipmentStateTimeline';
import BoardSem from './BoardSem';
import { availableEquipment, compareEquipment } from './equipmentComparison';
import BoardAnalysis from './BoardAnalysis';
import DetectionFlow from './DetectionFlow';
import ResizableBoard from './ResizableBoard';
import MetrologyMap from './BoardMetrology';
import BoardOverlay, { type OverlayView } from './BoardOverlay';
import MapWaferSelection from './MapWaferSelection';
import { SourcePreview } from './ReviewView';
import {
  makeInformNotes,
  selectInformNotes,
  formatInformTimestamp,
  documentUrl,
  wipLayerOption,
  semRecord,
} from './investigationData';

const gridId = 'synthetic-grid-v1';
const bins = ['#e3e8e7', '#8cbcaf', '#3c8978', '#e7af55', '#c55961'];
const frequencyColor = (percent: number) =>
  percent === 0
    ? '#e3e8e7'
    : percent < 25
      ? '#b2d9cf'
      : percent < 50
        ? '#57ac98'
        : percent < 75
          ? '#e7af55'
          : '#c55961';
const time = (value: string) => value.slice(5, 16).replace('T', ' ');

export default function InvestigationBoard({
  workspace,
  data,
  selection,
  change,
  choose,
  trend,
  focusedKey,
  onFocus,
  navigate,
  incidents,
  roomId,
  onConversationChange,
  attach,
  attachments,
  notes,
  onNotes,
  onRemoveAttachment,
  onOpenAttachment,
  storageError,
}: ViewProps & {
  data: EngineeringData;
  selection: InvestigationSelection;
  change: (patch: Partial<InvestigationSelection>) => void;
  choose: (signal: Signal) => void;
  trend: (equipment: string) => ReactNode;
  focusedKey: string;
  onFocus: (row: FabRow) => void;
  incidents: Incident[];
  roomId: string;
  onConversationChange: () => void;
  attachments: Attachment[];
  notes: string;
  onNotes: (value: string) => void;
  onRemoveAttachment: (item: Attachment) => void;
  onOpenAttachment: (item: Attachment) => void;
  storageError: boolean;
}) {
  const incident = workspace.incident.incident_number;
  const signal = data.signals.find((row) => row.id === selection.signalId)!;
  const fabScope = signalFabScope(data, signal);
  const [layoutLocked, setLayoutLocked] = useState(false);
  const [layoutReset, setLayoutReset] = useState(0);
  const [layoutStorageError, setLayoutStorageError] = useState(false);
  const [mapMode, setMapMode] = useState<'cd' | 'thk' | 'overlay' | 'bin'>(
    'cd',
  );
  const [vectorScale, setVectorScale] = useState(1);
  const [overlayView, setOverlayView] = useState<OverlayView>('raw');
  const [signalQuery, setSignalQuery] = useState('');
  const [priority, setPriority] = useState('all');
  const [signalOrder, setSignalOrder] = useState('source');
  const signalTable = useRef<HTMLDivElement>(null);
  const visibleSignals = useMemo(() => {
    const terms = signalQuery
      .trim()
      .toLocaleLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    const rows = data.signals.filter((row) => {
      const text = [
        row.device,
        row.step,
        row.item,
        signalMember(row),
        signalAxisLabel(row),
        row.equipment,
        row.recipe,
        row.title,
      ]
        .join(' ')
        .toLocaleLowerCase();
      return (
        (priority === 'all' || row.severity === priority) &&
        terms.every((term) => text.includes(term))
      );
    });
    if (signalOrder === 'priority')
      rows.sort(
        (a, b) => Number(b.severity === 'high') - Number(a.severity === 'high'),
      );
    if (signalOrder === 'latest')
      rows.sort((a, b) => Date.parse(b.detectedAt) - Date.parse(a.detectedAt));
    return rows;
  }, [data.signals, signalQuery, priority, signalOrder]);
  const selectedVisible = visibleSignals.some((row) => row.id === signal.id);
  useEffect(() => {
    const container = signalTable.current;
    const row = container?.querySelector<HTMLTableRowElement>('tr.selected');
    if (!container || !row) return;
    const top =
      row.getBoundingClientRect().top - container.getBoundingClientRect().top;
    const bottom = top + row.offsetHeight;
    if (top < 24) container.scrollTop += top - 24;
    else if (bottom > container.clientHeight)
      container.scrollTop += bottom - container.clientHeight;
  }, [signal.id, visibleSignals]);
  const candidates = useMemo(
    () => selectFabRows(data, selection),
    [data, selection],
  );
  const trendWafers = useMemo(
    () => selectTrendFabRows(data, signal.id),
    [data, signal.id],
  );
  const mapCandidates = useMemo(
    () => selectFabRows(data, { ...selection, equipment: '', recipe: '' }),
    [data, selection],
  );
  const [waferPickerOpen, setWaferPickerOpen] = useState(false);
  const waferDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!waferPickerOpen) return;
    const previous = document.activeElement;
    const dialog = waferDialog.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus({ preventScroll: true });
    };
  }, [waferPickerOpen]);
  const from = data.trend[selection.start].timestamp;
  const to = data.trend[selection.end].timestamp;
  const events = changeTiming(data, signal, selection);
  const windowSummary = useMemo(
    () => summarizeTrendSamples(data, selection),
    [data, selection],
  );
  const [productionNotice, setProductionNotice] = useState('');
  const [copyStatus, setCopyStatus] = useState('');
  const [semWafers, setSemWafers] = useState<
    { lot_id: string; wafer_id: string }[]
  >([]);
  const [preview, setPreview] = useState<Attachment | null>(null);
  const previewDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (preview) previewDialog.current?.showModal();
  }, [preview]);
  const wip = data.wip.filter(
    (row) =>
      row.step === signal.step &&
      (!selection.equipment || row.equipment === selection.equipment) &&
      (!selection.recipe || row.recipe === selection.recipe),
  );
  const related = incidents.filter((row) => row.incident_number !== incident);
  const informEquipment =
    signal.legendAxis === 'eqp_id' ? signalMember(signal) : selection.equipment;
  const informNotes = informEquipment
    ? selectInformNotes(makeInformNotes(data), signal.step, informEquipment)
    : makeInformNotes(data)
        .filter((note) => note.step === signal.step)
        .sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
  const scope = JSON.stringify([
    selection.signalId,
    selection.start,
    selection.end,
    selection.equipment,
    selection.recipe,
  ]);
  const allKeys = useMemo(() => new Set(candidates.map(pairKey)), [candidates]);
  const [checkedState, setCheckedState] = useState(() => ({
    scope,
    keys: allKeys,
  }));
  const checked = checkedState.scope === scope ? checkedState.keys : allKeys;
  const mapScope = JSON.stringify([signal.id, mapCandidates.map(pairKey)]);
  const mapKeys = useMemo(() => new Set(mapCandidates.map(pairKey)), [mapCandidates]);
  const [mapSelections, setMapSelections] = useState(() => ({
    scope: mapScope,
    A: mapKeys,
    B: mapKeys,
  }));
  const primaryKeys = mapSelections.scope === mapScope ? mapSelections.A : mapKeys;
  const comparisonKeys = mapSelections.scope === mapScope ? mapSelections.B : mapKeys;
  const setMapKeys = (side: 'A' | 'B', keys: Set<string>) =>
    setMapSelections((previous) => ({
      ...(previous.scope === mapScope ? previous : { A: mapKeys, B: mapKeys }),
      scope: mapScope,
      [side]: keys,
    }));
  const setChecked = (
    update: Set<string> | ((previous: Set<string>) => Set<string>),
  ) =>
    setCheckedState((previous) => ({
      scope,
      keys:
        typeof update === 'function'
          ? update(previous.scope === scope ? previous.keys : allKeys)
          : update,
    }));
  const selectAllWafers = (label: string) => (
    <input
      type="checkbox"
      aria-label={label}
      title={label}
      checked={!!candidates.length && checked.size === candidates.length}
      ref={(node) => {
        if (node)
          node.indeterminate =
            checked.size > 0 && checked.size < candidates.length;
      }}
      disabled={!candidates.length}
      onChange={(event) =>
        setChecked(new Set(event.target.checked ? candidates.map(pairKey) : []))
      }
    />
  );
  const [threshold, setThreshold] = useState(0);
  const [die, setDie] = useState<[number, number] | null>(null);
  const [region, setRegion] = useState<DieRegion | null>(null);
  const selectRegion = (next: DieRegion | null) => {
    setRegion(next);
    setDie(null);
  };
  const selectDie = (next: [number, number] | null) => {
    setDie(next);
    setRegion(null);
  };
  useEffect(() => {
    setCheckedState((previous) =>
      previous.scope === scope ? previous : { scope, keys: allKeys },
    );
  }, [scope, allKeys]);
  useEffect(() => {
    setDie(null);
    setRegion(null);
    setProductionNotice('');
  }, [scope]);
  const focused =
    candidates.find((row) => pairKey(row) === focusedKey) || candidates[0];
  const equipmentOptions =
    signal.legendAxis === 'eqp_id'
      ? availableEquipment(data, signal)
      : [
          ...new Set(
            data.fab
              .filter((row) => row.step === signal.step)
              .map((row) => row.equipment),
          ),
        ];
  const comparisonPrimary =
    signal.legendAxis === 'eqp_id'
      ? signalMember(signal)
      : focused?.equipment || '';
  const [peerState, setPeerState] = useState({
    scope: '',
    equipment: '',
    key: '',
  });
  const peerEquipment =
    peerState.scope === scope
      ? peerState.equipment
      : equipmentOptions.find((value) => value !== comparisonPrimary) ||
        equipmentOptions[0] ||
        '';
  const peerCandidates = selectFabRows(data, {
    ...selection,
    equipment: peerEquipment,
  }).filter((row) => !focused || pairKey(row) !== pairKey(focused));
  const peer =
    peerCandidates.find(
      (row) => peerState.scope === scope && pairKey(row) === peerState.key,
    ) || peerCandidates[0];
  const equipmentComparison = compareEquipment(
    data,
    signal,
    signal.equipment,
    peerEquipment,
    selection.start,
    selection.end,
  );
  const distribution = useMemo(
    () =>
      trendBoxPlotOption(data, selection, peerEquipment, {
        members: [],
        dimOthers: false,
        zoomToSelection: false,
        showChanges: false,
        showLegend: false,
      }),
    [data, selection, peerEquipment],
  );
  const maps = useMemo(
    () =>
      mapCandidates.map((row) => ({
        lotId: row.lotId,
        waferId: row.waferId,
        gridId,
        dies: waferData(waferSeed(incident, row.lotId, row.waferId)),
      })),
    [incident, mapCandidates],
  );
  const selectedMaps = useMemo(
    () => maps.filter((row) => primaryKeys.has(pairKey(row))),
    [maps, primaryKeys],
  );
  const comparisonMaps = useMemo(
    () => maps.filter((row) => comparisonKeys.has(pairKey(row))),
    [maps, comparisonKeys],
  );
  const mapModeControls = (label: string) => (
    <div className="board-map-modes">
      <div role="group" aria-label={label}>
        {(['cd', 'thk', 'overlay', 'bin'] as const).map((mode) => (
          <button
            key={mode}
            aria-pressed={mapMode === mode}
            onClick={() => setMapMode(mode)}
          >
            {mode === 'bin'
              ? 'Bin'
              : mode === 'overlay'
                ? 'Overlay'
                : mode.toUpperCase()}
          </button>
        ))}
      </div>
    </div>
  );
  const dieEvidence = useMemo(() => inspectWaferDie(maps, die), [maps, die]);
  const flaggedDieWafers = dieEvidence.filter((row) => row.flag === true);
  const composite = useMemo(
    () => compositeWaferMaps(selectedMaps),
    [selectedMaps],
  );
  const comparisonComposite = useMemo(
    () => compositeWaferMaps(comparisonMaps),
    [comparisonMaps],
  );
  const regionByWafer = new Map(
    maps.map((map) => {
      const dies = selectDieRegion(map.dies, region);
      return [
        pairKey(map),
        {
          observed: dies.length,
          flags: dies.filter((row) => row.bin >= 3).length,
        },
      ];
    }),
  );
  const flaggedRegionWafers = maps.filter(
    (map) => (regionByWafer.get(pairKey(map))?.flags || 0) > 0,
  );
  const mapBrush = {
    toolbox: [],
    xAxisIndex: 0,
    yAxisIndex: 0,
    brushType: 'rect',
    brushMode: 'single',
    areas: region
      ? [
          {
            brushType: 'rect',
            xAxisIndex: 0,
            yAxisIndex: 0,
            coordRange: region,
          },
        ]
      : [],
    brushStyle: { borderColor: '#477eaa', color: 'rgba(71,126,170,0.12)' },
    outOfBrush: { colorAlpha: 0.35 },
  };
  const mapOption = (
    targets: typeof selectedMaps,
    combinedMap: typeof composite,
  ) => ({
    animation: false,
    brush: mapBrush,
    grid: { left: 1, right: 1, top: 1, bottom: 1 },
    xAxis: { type: 'value', min: -18, max: 18, show: false },
    yAxis: { type: 'value', min: -18, max: 18, show: false },
    tooltip: {
      renderMode: 'richText',
      confine: true,
      formatter: (p: { value: number[] }) =>
        `${waferCoordinateText(p.value[0], p.value[1], workspace.wafer_geometry)}\n` +
        (targets.length > 1
          ? `Flag ${p.value[2]} / ${p.value[3]} (${p.value[4].toFixed(1)}%) · 합성`
          : `Bin ${p.value[2]} · 합성`),
    },
    series: [
      {
        type: 'custom',
        z: 1,
        zlevel: 0,
        clip: true,
        encode: { x: 0, y: 1 },
        renderItem: ((_params, api) => {
          const point = api.coord([api.value(0), api.value(1)]);
          const next = api.coord([
            Number(api.value(0)) + 1,
            Number(api.value(1)) + 1,
          ]);
          const width = Math.max(1, Math.abs(next[0] - point[0]) * 0.86);
          const height = Math.max(1, Math.abs(next[1] - point[1]) * 0.86);
          return {
            type: 'rect',
            z2: 0,
            shape: {
              x: point[0] - width / 2,
              y: point[1] - height / 2,
              width,
              height,
            },
            style: { fill: api.visual('color') as string },
          };
        }) as CustomSeriesRenderItem,
        markPoint: die
          ? {
              silent: true,
              symbol: 'rect',
              symbolSize: 11,
              label: { show: false },
              itemStyle: {
                color: 'transparent',
                borderColor: '#233a32',
                borderWidth: 1.5,
              },
              data: [{ coord: die }],
            }
          : undefined,
        data: targets.length > 1
          ? combinedMap.dies.map((row) => ({
              value: [row.x, row.y, row.flags, row.observed, row.percent],
              itemStyle: {
                color:
                  row.percent < threshold
                    ? '#f3f5f4'
                    : frequencyColor(row.percent),
              },
            }))
          : (targets[0]?.dies || []).map((row) => ({
              value: [row.x, row.y, row.bin],
              itemStyle: { color: bins[row.bin] },
            })),
      },
    ],
  });
  // List filtering must not reset the map renderer or its active brush.
  const primaryMapOption = useMemo(
    () => mapOption(selectedMaps, composite),
    [selectedMaps, composite, die, region, threshold, workspace.wafer_geometry],
  );
  const comparisonMapOption = useMemo(
    () => mapOption(comparisonMaps, comparisonComposite),
    [comparisonMaps, comparisonComposite, die, region, threshold, workspace.wafer_geometry],
  );

  const exportComposite = (
    label: string,
    targets: typeof selectedMaps,
    combinedMap: typeof composite,
  ) =>
    download(
      `${incident}-map-${label}.json`,
      JSON.stringify(
        {
          synthetic: true,
          incident,
          selection,
          gridId,
          selected: targets.map(({ lotId, waferId }) => ({
            lotId,
            waferId,
          })),
          scope: mapCandidates.map(({ lotId, waferId, timestamp }) => ({
            lotId,
            waferId,
            timestamp,
          })),
          flagRule: 'bin >= 3',
          denominator: 'observed wafers per coordinate; missing is not pass',
          physicalAlignmentVerified: false,
          selectedCoordinate: die,
          selectedRegion: region,
          coordinateObservations: dieEvidence,
          displayThresholdPercent: threshold,
          ...combinedMap,
        },
        null,
        2,
      ),
      'application/json',
    );
  const analysisContext = {
    incident_number: incident,
    item: signal.item,
    step: signal.step,
    equipment: selection.equipment,
    recipe: selection.recipe,
    from,
    to,
    trend_selection: analysisTrendSelection(selection),
    sem_wafers: semWafers,
    map_view: { kind: mapMode, overlay: overlayView },
    map_comparison: {
      a: selectedMaps.map((row) => ({ lot_id: row.lotId, wafer_id: row.waferId })),
      b: comparisonMaps.map((row) => ({ lot_id: row.lotId, wafer_id: row.waferId })),
    },
    wafers: candidates
      .filter((row) => checked.has(pairKey(row)))
      .map((row) => ({ lot_id: row.lotId, wafer_id: row.waferId })),
  };
  const expand = (
    label: string,
    tab: Parameters<ViewProps['navigate']>[0],
    mode?: string,
  ) => (
    <button
      className="icon-button"
      title={label}
      onClick={() => navigate(tab, undefined, mode)}
    >
      <ArrowUpRight size={14} />
    </button>
  );
  const pin = (item: Attachment, label: string) => {
    const selected = attachments.some(
      (row) =>
        row.id === item.id &&
        row.kind === item.kind &&
        row.incident_number === incident,
    );
    return (
      <button
        className="icon-button board-pin"
        title={selected ? `${label} 고정 해제` : `${label} 검토에 고정`}
        aria-pressed={selected}
        disabled={!selected && attachments.length >= 8}
        onClick={() =>
          selected
            ? onRemoveAttachment({ ...item, incident_number: incident })
            : attach({ ...item, incident_number: incident })
        }
      >
        {selected ? <Check size={13} /> : <Pin size={13} />}
      </button>
    );
  };
  const number = (value: number | null) =>
    value === null ? '-' : value.toFixed(2);
  const copyWaferTuples = async (rows: typeof candidates, label: string) => {
    try {
      await navigator.clipboard.writeText(
        rows.map((row) => `${row.lotId}\t${row.waferId}`).join('\n'),
      );
      setCopyStatus(`${label} 복사 완료`);
    } catch {
      setCopyStatus(`${label} 복사 실패`);
    }
  };
  const mapPanel = (side: 'A' | 'B') => {
    const primary = side === 'A';
    const targets = primary ? selectedMaps : comparisonMaps;
    const combined = primary ? composite : comparisonComposite;
    const keys = primary ? primaryKeys : comparisonKeys;
    const key = JSON.stringify(targets.map(pairKey));
    return (
      <section
        className={`board-panel ${primary ? 'board-single-map' : 'board-composite'}`}
        data-panel={primary ? 'single-map' : 'composite'}
        aria-label={`Map ${side} 비교`}
      >
        <header>
          <h2>Map {side}</h2>
          <output aria-live="polite" title={targets.map((row) => `${row.lotId} / ${row.waferId}`).join(', ')}>
            {targets.length > 1 ? (mapMode === 'bin' ? 'Flag' : 'Avg') : 'Wafer'}{' '}
            {targets.length}/{maps.length}
          </output>
          {mapMode === 'bin' && (
            <>
              <button
                className="icon-button"
                title={`Map ${side} 데이터 다운로드`}
                disabled={!targets.length}
                onClick={() => exportComposite(side, targets, combined)}
              >
                <ArrowDownToLine size={14} />
              </button>
              <button
                className="icon-button"
                title="Map 영역·Die 선택 해제"
                disabled={!region && !die}
                onClick={() => selectDie(null)}
              >
                <X size={14} />
              </button>
            </>
          )}
        </header>
        <MapWaferSelection
          label={`Map ${side}`}
          rows={mapCandidates}
          axis={signal.legendAxis}
          checked={keys}
          onChange={(next) => setMapKeys(side, next)}
        />
        {mapModeControls(`Map ${side} 종류`)}
        {!targets.length ? (
          <p className="board-empty">선택한 Wafer 없음</p>
        ) : mapMode === 'bin' ? (
          <>
            {targets.length > 1 && (
              <label className="board-frequency">
                Flag ≥
                <input
                  type="range"
                  aria-label={`Map ${side} 최소 Flag 빈도`}
                  min={0}
                  max={100}
                  step={5}
                  value={threshold}
                  onChange={(event) => setThreshold(+event.target.value)}
                />
                <output>{threshold}%</output>
              </label>
            )}
            <div className="board-map-stage">
              <Chart
                option={primary ? primaryMapOption : comparisonMapOption}
                mapNavigation
                areaSelection={region}
                className="board-map-canvas"
                label={`Map ${side} · ${targets.length} Wafers`}
                onSelect={(p) => selectDie([p.value[0], p.value[1]])}
                onArea={selectRegion}
              />
            </div>
          </>
        ) : mapMode === 'overlay' ? (
          <BoardOverlay
            key={key}
            wafers={targets}
            aggregate={targets.length > 1}
            geometry={workspace.wafer_geometry}
            vectorScale={vectorScale}
            onVectorScale={setVectorScale}
            view={overlayView}
            onView={setOverlayView}
          />
        ) : (
          <MetrologyMap
            key={`${mapMode}:${key}`}
            wafers={targets}
            aggregate={targets.length > 1}
            metric={mapMode}
            geometry={workspace.wafer_geometry}
          />
        )}
      </section>
    );
  };
  return (
    <div className="investigation-board">
      <div className="board-status-bar">
        <DetectionFlow
          context={analysisContext}
          a={
            focused
              ? { lot_id: focused.lotId, wafer_id: focused.waferId }
              : undefined
          }
          b={peer ? { lot_id: peer.lotId, wafer_id: peer.waferId } : undefined}
        />
        <div className="board-layout-actions">
          <button
            className="icon-button"
            aria-label="패널 크기 잠금"
            title="패널 크기 잠금"
            aria-pressed={layoutLocked}
            onClick={() => setLayoutLocked((value) => !value)}
          >
            {layoutLocked ? (
              <LockKeyhole size={14} />
            ) : (
              <UnlockKeyhole size={14} />
            )}
          </button>
          <button
            className="icon-button"
            aria-label="기본 패널 배치 복원"
            title={
              layoutStorageError
                ? '배치 저장 실패 · 기본 배치 복원'
                : '기본 패널 배치 복원'
            }
            onClick={() => setLayoutReset((value) => value + 1)}
          >
            <PanelsTopLeft
              size={14}
              className={layoutStorageError ? 'layout-storage-error' : ''}
            />
          </button>
          {layoutStorageError && (
            <span className="sr-only" role="status">
              브라우저 배치 저장 실패
            </span>
          )}
        </div>
      </div>
      <ResizableBoard
        locked={layoutLocked}
        resetKey={layoutReset}
        onStorageError={setLayoutStorageError}
      >
        <section
          data-panel="signals"
          className="board-panel board-signals"
          aria-label="이상감지 선택 목록"
        >
          <header>
            <h2>이상감지</h2>
            <span aria-live="polite">
              {visibleSignals.length} / {data.signals.length} items
            </span>
            {expand('이상감지 상세', 'signals')}
          </header>
          <div className="board-signal-tools">
            <label className="board-signal-search">
              <Search size={13} aria-hidden="true" />
              <input
                aria-label="이상 목록 검색"
                placeholder="Device · Step · Item · Group"
                value={signalQuery}
                onChange={(event) => setSignalQuery(event.target.value)}
              />
              {signalQuery && (
                <button
                  className="icon-button"
                  title="검색 지우기"
                  aria-label="검색 지우기"
                  onClick={() => setSignalQuery('')}
                >
                  <X size={12} />
                </button>
              )}
            </label>
            <select
              aria-label="이상 우선순위 필터"
              value={priority}
              onChange={(event) => setPriority(event.target.value)}
            >
              <option value="all">전체 우선순위</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
            </select>
            <select
              aria-label="이상 목록 정렬"
              value={signalOrder}
              onChange={(event) => setSignalOrder(event.target.value)}
            >
              <option value="source">원본 순서</option>
              <option value="priority">우선순위순</option>
              <option value="latest">최신순</option>
            </select>
            <button
              className="icon-button"
              aria-label="목록 필터 초기화"
              title="목록 필터 초기화"
              disabled={
                !signalQuery && priority === 'all' && signalOrder === 'source'
              }
              onClick={() => {
                setSignalQuery('');
                setPriority('all');
                setSignalOrder('source');
              }}
            >
              <ListRestart size={14} />
            </button>
          </div>
          <div className="board-signal-table" ref={signalTable}>
            <table>
              <thead>
                <tr>
                  <th>Device</th>
                  <th>Step</th>
                  <th>Item</th>
                  <th>비교축 / 대상</th>
                  <th>감지 시각 · UTC</th>
                  <th>우선순위</th>
                </tr>
              </thead>
              <tbody>
                {visibleSignals.map((row, index) => (
                  <tr
                    key={row.id}
                    className={row.id === signal.id ? 'selected' : ''}
                    onClick={() => choose(row)}
                  >
                    <td>{row.device}</td>
                    <td>{row.step}</td>
                    <td>
                      <button
                        aria-pressed={row.id === signal.id}
                        onClick={(event) => {
                          event.stopPropagation();
                          choose(row);
                        }}
                        title={`${row.device} · ${row.step} · ${row.item} · ${row.title}`}
                        onKeyDown={(event) => {
                          if (
                            !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(
                              event.key,
                            )
                          )
                            return;
                          event.preventDefault();
                          const next =
                            event.key === 'Home'
                              ? 0
                              : event.key === 'End'
                                ? visibleSignals.length - 1
                                : Math.max(
                                    0,
                                    Math.min(
                                      visibleSignals.length - 1,
                                      index +
                                        (event.key === 'ArrowDown' ? 1 : -1),
                                    ),
                                  );
                          choose(visibleSignals[next]);
                          signalTable.current
                            ?.querySelectorAll<HTMLButtonElement>(
                              'tbody button',
                            )
                            [next]?.focus({ preventScroll: true });
                        }}
                      >
                        {row.item}
                        <small>{row.title}</small>
                      </button>
                    </td>
                    <td>
                      {signalMember(row)}
                      <small>{signalAxisLabel(row)}</small>
                    </td>
                    <td>{time(row.detectedAt)}</td>
                    <td>
                      <AlertTriangle
                        size={12}
                        className={row.severity}
                        aria-label={row.severity}
                      />{' '}
                      {row.severity === 'high' ? 'High' : 'Medium'}
                    </td>
                  </tr>
                ))}
                {!visibleSignals.length && (
                  <tr>
                    <td colSpan={6} className="board-signal-empty">
                      검색 결과 없음
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <footer>
            <strong>{signal.item}</strong> · {signalAxisLabel(signal)}:{' '}
            {signalMember(signal)}
            {!selectedVisible && (
              <span className="board-filter-hidden">
                {' '}
                · 선택 항목은 필터 밖
              </span>
            )}
            <span className="board-source-caption">
              합성 Raw · 감지 모델 미연결
            </span>
          </footer>
        </section>
        <section
          className="board-panel board-trend"
          data-panel="trend"
          aria-label="선택 이상감지 Trend"
        >
          <header>
            <h2>{signal.item} Trend</h2>
            <button
              className="board-wafer-trigger"
              title="구간 Lot/Wafer 선택 · 복사 · Map · SEM 비교"
              aria-label="Lot/Wafer 선택 목록 열기"
              aria-haspopup="dialog"
              onClick={() => setWaferPickerOpen(true)}
            >
              <ListFilter size={13} />
              Wafer {checked.size}/{candidates.length}
            </button>
            <span>시작 {time(data.trend[signal.onsetIndex].timestamp)}</span>
            {pin(
              {
                kind: 'trend',
                id: engineeringReference('trend', selection),
                label: `${signal.item} ${time(from)}~${time(to)} · 합성`,
              },
              'Trend 구간',
            )}
            <button
              className="icon-button"
              title="감지 구간 복원"
              onClick={() =>
                change({
                  start: signal.startIndex,
                  end: signal.endIndex,
                  valueRange: undefined,
                })
              }
            >
              <RotateCcw size={14} />
            </button>
          </header>
          <div
            className="board-baseline-stats"
            aria-label={
              selection.rangeSelected === false
                ? '전체 Trend 통계'
                : '감지 전과 선택 구간 비교'
            }
            aria-live="polite"
          >
            <span
              title={`${signalAxisLabel(signal)} ${signalMember(signal)} Raw · 감지 전 ${windowSummary.baseline.from || '-'} ~ ${windowSummary.baseline.to || '-'} · 정상 검증 아님`}
            >
              <small>감지 전 · n={windowSummary.baseline.n}</small>
              <b>
                {number(windowSummary.baseline.median)}{' '}
                <em>{metricUnits[signal.metric]}</em>
              </b>
            </span>
            <span
              title={`${signalAxisLabel(signal)} ${signalMember(signal)} Raw · 범위 ${number(windowSummary.selected.min)} ~ ${number(windowSummary.selected.max)}`}
            >
              <small>
                {selection.rangeSelected === false ? '전체' : '선택'} · n=
                {windowSummary.selected.n}
              </small>
              <b>
                {number(windowSummary.selected.median)}{' '}
                <em>{metricUnits[signal.metric]}</em>
              </b>
            </span>
            <span title="선택 중앙값 − 감지 전 중앙값 · 양쪽 최소 3개 표본 · 원인/유의성 판정 아님">
              <small>Δ 중앙값</small>
              <b className="board-delta-value">
                {selection.rangeSelected === false
                  ? '-'
                  : windowSummary.comparable
                    ? `${windowSummary.deltaMedian! > 0 ? '+' : ''}${number(windowSummary.deltaMedian)}`
                    : '표본 부족'}
              </b>
            </span>
            <span
              title={`감지 대상 Raw의 Q3 − Q1 · 감지 전 IQR ${number(windowSummary.baseline.iqr)} · 최소 3개 표본`}
            >
              <small>
                {selection.rangeSelected === false ? '전체' : '선택'} IQR
              </small>
              <b>
                {number(windowSummary.selected.iqr)}{' '}
                <em>{metricUnits[signal.metric]}</em>
              </b>
            </span>
          </div>
          <div
            className="board-equipment-stats"
            aria-live="polite"
            title={
              signal.legendAxis === 'eqp_id'
                ? `시간 집계 중앙값 · Signal A ${signal.equipment} · B ${peerEquipment} · 합성 자료`
                : `감지 비교축: ${signalAxisLabel(signal)} · 설비 원인 확정 아님`
            }
          >
            {signal.legendAxis !== 'eqp_id' ? (
              <span>
                {signalAxisLabel(signal)} · {signalMember(signal)} · 그룹별 Raw
                비교
              </span>
            ) : equipmentComparison.valid ? (
              <>
                <b>
                  시간 집계 A/B {equipmentComparison.medianA?.toFixed(2)} /{' '}
                  {equipmentComparison.medianB?.toFixed(2)}{' '}
                  {metricUnits[signal.metric]}
                </b>
                <span>
                  Δ A−B {equipmentComparison.deltaMedian?.toFixed(2)} ·{' '}
                  {equipmentComparison.count} 시간쌍
                </span>
              </>
            ) : (
              <span>
                {equipmentComparison.reason === 'same-equipment'
                  ? '동일 설비 · Wafer 비교'
                  : '설비 비교 데이터 없음'}
              </span>
            )}
          </div>
          <div className="board-trend-body">{trend(peerEquipment)}</div>
          <div className="board-range">
            <label>
              시작
              <input
                aria-label="Trend 구간 시작"
                type="range"
                min={0}
                max={data.trend.length - 1}
                value={selection.start}
                onChange={(event) =>
                  change({
                    start: Math.min(+event.target.value, selection.end),
                  })
                }
              />
              <output>{time(from)}</output>
            </label>
            <label>
              끝
              <input
                aria-label="Trend 구간 끝"
                type="range"
                min={0}
                max={data.trend.length - 1}
                value={selection.end}
                onChange={(event) =>
                  change({
                    end: Math.max(+event.target.value, selection.start),
                  })
                }
              />
              <output>{time(to)}</output>
            </label>
          </div>
          <div
            className="board-change-strip"
            aria-label="Recipe와 전산 변경 이력"
          >
            {events.map((event) => (
              <span className="board-change-entry" key={event.id}>
                <button
                  className={event.inSelection ? 'in-range' : ''}
                  title={`${event.equipment} · ${event.sourceRef} · ${event.before} → ${event.after} · 원인 미확정`}
                  onClick={() => {
                    const index = data.trend.reduce(
                      (best, row, i) =>
                        Math.abs(
                          Date.parse(row.timestamp) -
                            Date.parse(event.timestamp),
                        ) <
                        Math.abs(
                          Date.parse(data.trend[best].timestamp) -
                            Date.parse(event.timestamp),
                        )
                          ? i
                          : best,
                      0,
                    );
                    change({
                      start: Math.max(0, index - 2),
                      end: Math.min(data.trend.length - 1, index + 2),
                      valueRange: undefined,
                    });
                  }}
                >
                  <time>{time(event.timestamp)}</time>{' '}
                  {event.kind === 'recipe' ? 'Recipe' : 'MES Rule'} ·{' '}
                  {event.before} → {event.after} · 감지{' '}
                  {Math.abs(event.minutesFromOnset / 60).toFixed(1)}h{' '}
                  {event.minutesFromOnset < 0 ? '전' : '후'}
                </button>
                {pin(
                  {
                    kind: 'data',
                    id: `engineering:change:${event.id}`,
                    label: `${event.kind === 'recipe' ? 'Recipe' : 'MES Rule'} ${time(event.timestamp)} · 합성`,
                  },
                  '변경 이력',
                )}
              </span>
            ))}
            {!events.length && <span>Trend 설비의 변경 이력 없음</span>}
          </div>
        </section>
        <section
          className="board-panel board-correlation"
          data-panel="correlation"
          aria-label="과거 완료 이력 상관분석"
        >
          <HistoricalCorrelation
            workspace={workspace}
            data={data}
            selection={selection}
            compact
          />
        </section>
        {mapPanel('A')}
        {mapPanel('B')}
        <section
          className="board-panel board-distribution"
          data-panel="distribution"
          aria-label="Legend별 Box plot"
        >
          <header>
            <h2>Legend별 Box plot</h2>
            <span>
              {signal.item} · {metricUnits[signal.metric]}
            </span>
          </header>
          {distribution.series[0].data.some((group) => group.count > 0) ? (
            <Chart
              option={distribution}
              className="board-distribution-chart"
              label={`${signal.item} Legend별 ${selection.rangeSelected === false ? '전체' : '선택 X·Y 범위'} 분포`}
            />
          ) : (
            <p className="board-empty">선택 범위 표본 없음</p>
          )}
          <footer>
            {selection.rangeSelected === false
              ? '전체 구간'
              : `${time(from)} ~ ${time(to)}`}
            {selection.rangeSelected !== false &&
              selection.valueRange &&
              ` · Y ${selection.valueRange[0].toFixed(2)} ~ ${selection.valueRange[1].toFixed(2)}`}
            {' · '}n=
            {distribution.series[0].data.reduce(
              (sum, group) => sum + group.count,
              0,
            )}
          </footer>
        </section>
        <section
          className="board-panel board-images"
          data-panel="images"
          aria-label="SEM 이미지 비교"
        >
          <BoardSem
            onComparisonChange={setSemWafers}
            currentItem={signal.item}
            workspace={workspace}
            focused={focused}
            compare={peer}
            options={trendWafers}
          />
        </section>
        <section
          className="board-panel board-production"
          data-panel="production"
          aria-label="생산 재공과 다운코드"
        >
          <header>
            <h2>재공 · 설비 상태</h2>
            <span>MES / FDC 미연결</span>
            {expand('생산 상세', 'production')}
          </header>
          <div className="board-production-columns">
            <div className="board-wip">
              {!!wip.length && (
                <Chart
                  className="board-wip-chart"
                  option={wipLayerOption(wip)}
                  label="제품별 재공 Layer · X Layer Y 제품"
                  onSelect={(value) => {
                    const lot = value.data?.lot;
                    if (!lot) return;
                    const matches = candidates.filter(
                      (row) => row.lotId === lot.lotId,
                    );
                    if (matches.length) {
                      onFocus(matches[0]);
                      setProductionNotice(
                        `${lot.lotId} · 구간 내 ${matches.length} Wafers`,
                      );
                    } else
                      setProductionNotice(
                        `${lot.lotId} · 선택 구간에 Wafer 없음`,
                      );
                  }}
                />
              )}
              {!wip.length && <p className="board-empty">일치 재공 없음</p>}
            </div>
            <div>
              <EquipmentStateTimeline
                equipment={selection.equipment || focused?.equipment || ''}
                equipmentStates={data.equipmentStates}
                equipmentOptions={[
                  ...new Set(data.fab.map((row) => row.equipment)),
                ]}
                anchorAt={signal.detectedAt}
                onEquipmentChange={(equipment) => change({ equipment })}
              />
            </div>
          </div>
          <footer>
            {productionNotice && (
              <span className="board-production-notice" role="status">
                {productionNotice}
              </span>
            )}
            <span className="wip-legend run">RUN</span> ·{' '}
            <span className="wip-legend wait">WAIT</span> ·{' '}
            <span className="wip-legend hold">HOLD</span> · {wip.length} Lots ·
            합성
          </footer>
        </section>
        <section
          className="board-panel board-documents"
          data-panel="documents"
          aria-label="Inform Note 회의록과 이전 이력"
        >
          <header>
            <h2>Eng’r Inform · 회의록</h2>
            <span>합성</span>
          </header>
          <div className="board-inform-state">
            {signal.step} / {informEquipment || '전체 설비 · Step 범위'}
          </div>
          <div className="board-doc-list">
            <table className="board-inform-table">
              <thead>
                <tr>
                  <th>날짜/시간 (UTC)</th>
                  <th>EQP</th>
                  <th>Step</th>
                  <th>제목</th>
                </tr>
              </thead>
              <tbody>
                {informNotes.map((note) => (
                  <tr key={note.id}>
                    <td>{formatInformTimestamp(note.date)}</td>
                    <td>{note.equipment}</td>
                    <td>{note.step}</td>
                    <td>
                      <a
                        href={documentUrl(incident, 'inform', note.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`${note.title} · ${note.equipment} · 새 창`}
                      >
                        {note.title}
                        <ArrowUpRight size={11} />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!informNotes.length && (
              <p className="board-empty">해당 Step / 설비 Inform 없음</p>
            )}
            {workspace.meetings.map((meeting) => (
              <div className="board-meeting-row" key={meeting.chunk_id}>
                <a
                  className="board-meeting-link"
                  href={documentUrl(incident, 'meeting', meeting.chunk_id)}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={meeting.title}
                >
                  회의록 · {meeting.title}
                  <ArrowUpRight size={11} />
                </a>
                {pin(
                  {
                    kind: 'inform',
                    id: meeting.chunk_id,
                    label: meeting.title,
                  },
                  '회의록',
                )}
              </div>
            ))}
          </div>
          {!workspace.meetings.length && (
            <p className="board-empty">현재 범위 회의록 없음</p>
          )}
          <footer>
            다른 등록 사고 {related.length}건 · 관련성 미검증 ·{' '}
            {related
              .slice(0, 2)
              .map((row) => row.incident_number)
              .join(' · ') || '등록 없음'}
          </footer>
        </section>
        <section
          className="board-panel board-assessment"
          data-panel="assessment"
          aria-label="설명과 판정"
        >
          <BoardAnalysis
            workspace={workspace}
            roomId={roomId}
            autoKey={`${incident}:${signal.id}`}
            onChange={onConversationChange}
            context={analysisContext}
            attachments={attachments}
            notes={notes}
            onNotes={onNotes}
            onRemoveAttachment={onRemoveAttachment}
            onOpenAttachment={setPreview}
          />
          {storageError && (
            <p className="save-error" role="alert">
              검토 저장 실패 · 내보내기 필요
            </p>
          )}
        </section>
      </ResizableBoard>
      {waferPickerOpen && (
        <dialog
          ref={waferDialog}
          className="analysis-dialog board-wafer-dialog"
          aria-label="선택 구간 Wafer 목록"
          onCancel={() => setWaferPickerOpen(false)}
          onClose={() => setWaferPickerOpen(false)}
        >
          <header>
            <h2>구간 Lot / Wafer</h2>
            <output aria-live="polite">
              {checked.size} / {candidates.length}
            </output>
            <button
              className="icon-button"
              title="체크된 Lot/Wafer 전체 복사"
              aria-label="체크된 Lot/Wafer 전체 복사"
              disabled={!checked.size}
              onClick={() =>
                void copyWaferTuples(
                  candidates.filter((row) => checked.has(pairKey(row))),
                  '체크된 Lot/Wafer',
                )
              }
            >
              {copyStatus === '체크된 Lot/Wafer 복사 완료' ? (
                <Check size={13} />
              ) : (
                <Copy size={13} />
              )}
            </button>
            {selectAllWafers('Wafer 전체 선택')}
            <button
              className="icon-button"
              title="Wafer 목록 닫기"
              aria-label="Wafer 목록 닫기"
              onClick={() => setWaferPickerOpen(false)}
            >
              <X size={16} />
            </button>
          </header>
          <div className="board-scope board-scope-toolbar">
            <div className="board-scope-main">
              <strong>{signal.title}</strong>
              <span>{signal.step}</span>
              <label>
                후속 설비
                <select
                  aria-label="조사 설비"
                  value={selection.equipment}
                  onChange={(event) =>
                    change({ equipment: event.target.value })
                  }
                >
                  <option value="">전체</option>
                  {[...new Set(data.fab.map((row) => row.equipment))].map(
                    (value) => (
                      <option key={value}>{value}</option>
                    ),
                  )}
                </select>
              </label>
              <label>
                Recipe
                <select
                  aria-label="조사 Recipe"
                  value={selection.recipe}
                  onChange={(event) => change({ recipe: event.target.value })}
                >
                  <option value="">전체</option>
                  {[...new Set(data.fab.map((row) => row.recipe))].map(
                    (value) => (
                      <option key={value}>{value}</option>
                    ),
                  )}
                </select>
              </label>
              <span className="board-scope-window">
                {time(from)} ~ {time(to)} UTC
              </span>
              <span className="board-demo">SYNTHETIC · 실측 미연결</span>
            </div>
            <div className="board-comparison-scope">
              <strong>
                A{' '}
                {focused
                  ? `${focused.lotId} / ${focused.waferId} · ${focused.equipment}`
                  : 'Wafer 없음'}
                {focused && !checked.has(pairKey(focused)) && (
                  <span className="board-focus-excluded"> · A 분석 제외</span>
                )}
              </strong>
              <label>
                설비 B
                <select
                  aria-label="비교 설비 B"
                  value={peerEquipment}
                  onChange={(event) =>
                    setPeerState({
                      scope,
                      equipment: event.target.value,
                      key: '',
                    })
                  }
                >
                  {equipmentOptions.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label>
                Wafer B
                <select
                  aria-label="비교 Wafer B"
                  value={peer ? pairKey(peer) : ''}
                  disabled={!peerCandidates.length}
                  onChange={(event) =>
                    setPeerState({
                      scope,
                      equipment: peerEquipment,
                      key: event.target.value,
                    })
                  }
                >
                  {!peerCandidates.length && (
                    <option value="">
                      해당 Step · 구간 · Recipe에 비교 Wafer 없음
                    </option>
                  )}
                  {peerCandidates.map((row) => (
                    <option value={pairKey(row)} key={pairKey(row)}>
                      {row.lotId} / {row.waferId} ·{' '}
                      {row.timestamp.slice(11, 16)}
                      {semRecord(workspace, row.lotId, row.waferId)
                        ? ' · SEM 등록'
                        : ' · SEM 없음'}
                    </option>
                  ))}
                </select>
              </label>
              <span>{signal.item} · 같은 Step / 구간 · 화면 비교</span>
            </div>
          </div>
          {(die || region) && (
            <div className="board-die-scope" aria-live="polite">
              <span>
                {die
                  ? `Die (${die[0]},${die[1]}) · 구간 Flag ${flaggedDieWafers.length}/${dieEvidence.filter((row) => row.bin !== null).length}`
                  : `선택 영역 · Flag Wafer ${flaggedRegionWafers.length}/${maps.length}`}
              </span>
              <button
                className="icon-button"
                title={
                  region
                    ? '선택 영역의 Flag Wafer만 분석에 포함'
                    : '해당 Die의 Flag Wafer만 분석에 포함'
                }
                disabled={
                  !(region ? flaggedRegionWafers : flaggedDieWafers).length
                }
                onClick={() =>
                  setChecked(
                    new Set(
                      (region ? flaggedRegionWafers : flaggedDieWafers).map(
                        pairKey,
                      ),
                    ),
                  )
                }
              >
                <ListFilter size={13} />
              </button>
              <button
                className="icon-button"
                title="Wafer 목록의 Map 선택 해제"
                onClick={() => selectDie(null)}
              >
                <X size={13} />
              </button>
            </div>
          )}
          <div className="board-wafer-list">
            <table>
              <thead>
                <tr>
                  <th aria-label="선택" />
                  <th>Lot</th>
                  <th>Wafer</th>
                  <th>EQP</th>
                  <th>시간 · UTC</th>
                  <th>SEM</th>
                  <th aria-label="복사 및 비교" />
                </tr>
              </thead>
              <tbody>
                {candidates.map((row) => (
                  <tr
                    key={pairKey(row)}
                    className={
                      focused && pairKey(focused) === pairKey(row)
                        ? 'selected'
                        : ''
                    }
                  >
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${row.lotId} / ${row.waferId} 분석 포함`}
                        checked={checked.has(pairKey(row))}
                        onChange={(event) =>
                          setChecked((previous) => {
                            const next = new Set(previous);
                            if (event.target.checked) next.add(pairKey(row));
                            else next.delete(pairKey(row));
                            return next;
                          })
                        }
                      />
                    </td>
                    <td>{row.lotId}</td>
                    <td>
                      <button
                        className="board-wafer-focus"
                        title={`${row.lotId} / ${row.waferId} Map A`}
                        aria-pressed={
                          primaryKeys.size === 1 && primaryKeys.has(pairKey(row))
                        }
                        onClick={() => {
                          onFocus(row);
                          setMapKeys('A', new Set([pairKey(row)]));
                          setWaferPickerOpen(false);
                        }}
                      >
                        {row.waferId}
                      </button>
                    </td>
                    <td>{row.equipment}</td>
                    <td>{time(row.timestamp)}</td>
                    <td>
                      {semRecord(workspace, row.lotId, row.waferId)
                        ? '등록'
                        : '없음'}
                    </td>
                    <td className="board-wafer-actions">
                      <button
                        className="icon-button"
                        title={`${row.lotId}/${row.waferId} Lot/Wafer 복사`}
                        aria-label={`${row.lotId}/${row.waferId} Lot/Wafer 복사`}
                        onClick={() =>
                          void copyWaferTuples(
                            [row],
                            `${row.lotId}/${row.waferId}`,
                          )
                        }
                      >
                        {copyStatus ===
                        `${row.lotId}/${row.waferId} 복사 완료` ? (
                          <Check size={13} />
                        ) : (
                          <Copy size={13} />
                        )}
                      </button>
                      <button
                        className="icon-button board-peer-pick"
                        title={`${row.lotId}/${row.waferId} · ${row.equipment} · ${row.timestamp} · 비교 B 지정`}
                        disabled={
                          !!focused && pairKey(focused) === pairKey(row)
                        }
                        aria-pressed={!!peer && pairKey(peer) === pairKey(row)}
                        onClick={() =>
                          setPeerState({
                            scope,
                            equipment: row.equipment,
                            key: pairKey(row),
                          })
                        }
                      >
                        <Columns2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {copyStatus && (
            <span className="board-copy-status" role="status">
              {copyStatus}
            </span>
          )}
          {!candidates.length && (
            <p className="board-empty">해당 구간 Wafer 없음</p>
          )}
          <footer>
            현재 Fab · EDS 대기
            <br />
            {!fabScope.exact && (
              <>
                <span
                  className="board-scope-warning"
                  title={fabScope.limitation || ''}
                >
                  {signalAxisLabel(signal)}→Fab 매핑 미연결 · Step 범위
                </span>
                <br />
              </>
            )}
            등록 범위 ≠ 사고 영향 범위
          </footer>
        </dialog>
      )}
      {preview && (
        <dialog
          className="analysis-dialog board-reference-dialog"
          ref={previewDialog}
          aria-label="고정 참조 원문"
          onCancel={() => setPreview(null)}
          onClose={() => setPreview(null)}
        >
          <header>
            <h2>고정 참조 원문</h2>
            <button
              className="icon-button"
              title="참조 닫기"
              onClick={() => setPreview(null)}
            >
              <X size={18} />
            </button>
          </header>
          <SourcePreview
            item={preview}
            workspace={workspace}
            open={
              preview.id.startsWith('engineering:change:') ||
              preview.id.startsWith('engineering:down:')
                ? undefined
                : (item) => {
                    setPreview(null);
                    onOpenAttachment(item);
                  }
            }
          />
        </dialog>
      )}
    </div>
  );
}

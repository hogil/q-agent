import type { WaferGeometry } from './api';

export type Die = { x: number; y: number; bin: number };
export type DieRegion = [[number, number], [number, number]];

export function waferCoordinates(
  x: number,
  y: number,
  geometry: WaferGeometry | undefined,
  space: 'chip' | 'normalized' = 'chip',
) {
  if (!geometry) return null;
  const mmPerUnit = geometry.radius_mm / geometry.coordinate_radius;
  const xMm =
    space === 'chip'
      ? x * geometry.chip_pitch_x_mm + geometry.chip_origin_x_mm
      : x * mmPerUnit;
  const yMm =
    space === 'chip'
      ? y * geometry.chip_pitch_y_mm + geometry.chip_origin_y_mm
      : y * mmPerUnit;
  return {
    xMm,
    yMm,
    radiusMm: Math.hypot(xMm, yMm),
    chipX:
      space === 'chip'
        ? x
        : Math.floor(
            (xMm - geometry.chip_origin_x_mm) / geometry.chip_pitch_x_mm + 0.5,
          ),
    chipY:
      space === 'chip'
        ? y
        : Math.floor(
            (yMm - geometry.chip_origin_y_mm) / geometry.chip_pitch_y_mm + 0.5,
          ),
  };
}

export function waferCoordinateText(
  x: number,
  y: number,
  geometry: WaferGeometry | undefined,
  space: 'chip' | 'normalized' = 'chip',
): string {
  const point = waferCoordinates(x, y, geometry, space);
  if (!point)
    return `${space === 'chip' ? 'Chip' : 'XY'} (${x.toFixed(space === 'chip' ? 0 : 1)}, ${y.toFixed(space === 'chip' ? 0 : 1)})\nX / Y / R mm: geometry 미설정`;
  return `X ${point.xMm.toFixed(2)} mm · Y ${point.yMm.toFixed(2)} mm\nR ${point.radiusMm.toFixed(2)} mm / ${geometry!.radius_mm} mm\nChip (${point.chipX}, ${point.chipY})${space === 'normalized' ? ' · pitch 기준' : ''}\n합성 geometry`;
}

export function selectDieRegion<T extends { x: number; y: number }>(
  dies: T[],
  region: DieRegion | null,
): T[] {
  if (!region) return dies;
  if (!region.every((axis) => axis.length === 2 && axis.every(Number.isFinite)))
    throw new Error('Die region bounds must be finite');
  const [[x1, x2], [y1, y2]] = region;
  return dies.filter(
    (die) =>
      die.x >= Math.min(x1, x2) &&
      die.x <= Math.max(x1, x2) &&
      die.y >= Math.min(y1, y2) &&
      die.y <= Math.max(y1, y2),
  );
}

export function waferData(seed: number): Die[] {
  const dice: Die[] = [];
  for (let y = -16; y <= 16; y++)
    for (let x = -16; x <= 16; x++) {
      const radius = Math.hypot(x, y);
      if (radius > 16 || (y < -14 && Math.abs(x) < 1)) continue;
      const random =
        (Math.sin(x * 12.98 + y * 78.23 + seed * 9.12) * 43758.55) % 1;
      const v = Math.abs(random);
      dice.push({
        x,
        y,
        bin:
          radius > 12.2 && x > -8
            ? v > 0.6
              ? 4
              : v > 0.18
                ? 3
                : 2
            : v > 0.965
              ? 2
              : v > 0.85
                ? 1
                : 0,
      });
    }
  return dice;
}

function hashTuple(value: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function waferSeed(
  incident: string,
  lotId: string,
  waferId: string,
): number {
  return hashTuple(JSON.stringify([incident, lotId, waferId]));
}

export type WaferMap = {
  lotId: string;
  waferId: string;
  gridId: string;
  dies: Die[];
};

export type WaferComparisonCategory =
  | 'bothFlag'
  | 'aOnly'
  | 'bOnly'
  | 'neither'
  | 'missingA'
  | 'missingB';

export type WaferComparisonDie = {
  x: number;
  y: number;
  binA: number | null;
  binB: number | null;
  category: WaferComparisonCategory;
};

export type WaferComparisonCounts = Record<WaferComparisonCategory, number>;

export type WaferComparison = {
  gridId: string;
  dies: WaferComparisonDie[];
  counts: WaferComparisonCounts;
  observedA: number;
  observedB: number;
  observedCommon: number;
  validCompared: number;
  flagsA: number;
  flagsB: number;
  jaccard: number | null;
  failRateA: number | null;
  failRateB: number | null;
  commonFailRateA: number | null;
  commonFailRateB: number | null;
  delta: number | null;
};

function validatedDieMap(map: WaferMap): Map<string, Die> {
  const dies = new Map<string, Die>();
  for (const die of map.dies) {
    if (
      !Number.isFinite(die.x) ||
      !Number.isFinite(die.y) ||
      !Number.isFinite(die.bin) ||
      !Number.isInteger(die.x) ||
      !Number.isInteger(die.y) ||
      !Number.isInteger(die.bin) ||
      die.bin < 0
    ) {
      throw new Error(
        'Die coordinates must be finite integers and bin must be a nonnegative integer',
      );
    }
    const coordinate = JSON.stringify([die.x, die.y]);
    if (dies.has(coordinate))
      throw new Error('Duplicate die coordinate within wafer map');
    dies.set(coordinate, die);
  }
  return dies;
}

export function inspectWaferDie(
  maps: WaferMap[],
  coordinate: [number, number] | null,
) {
  if (!coordinate) return [];
  if (!coordinate.every(Number.isInteger))
    throw new Error('Die coordinates must be finite integers');
  const keys = new Set<string>();
  const target = JSON.stringify(coordinate);
  return maps.map((map) => {
    if (!map.gridId.trim() || map.gridId !== maps[0].gridId)
      throw new Error('Mixed or blank wafer gridId values');
    const key = JSON.stringify([map.lotId, map.waferId]);
    if (keys.has(key)) throw new Error('Duplicate lot/wafer tuple');
    keys.add(key);
    const bin = validatedDieMap(map).get(target)?.bin ?? null;
    return {
      lotId: map.lotId,
      waferId: map.waferId,
      bin,
      flag: bin === null ? null : bin >= 3,
    };
  });
}

export function compareWaferMaps(a: WaferMap, b: WaferMap): WaferComparison {
  if (a.gridId.trim().length === 0 || b.gridId.trim().length === 0)
    throw new Error('Wafer gridId must not be blank');
  if (a.gridId !== b.gridId) throw new Error('Mixed wafer gridId values');
  if (
    JSON.stringify([a.lotId, a.waferId]) ===
    JSON.stringify([b.lotId, b.waferId])
  )
    throw new Error('Cannot compare the same lot/wafer tuple');

  const diesA = validatedDieMap(a);
  const diesB = validatedDieMap(b);
  const counts: WaferComparisonCounts = {
    bothFlag: 0,
    aOnly: 0,
    bOnly: 0,
    neither: 0,
    missingA: 0,
    missingB: 0,
  };
  const dies: WaferComparisonDie[] = [];
  let flagsA = 0;
  let flagsB = 0;

  for (const die of diesA.values()) if (die.bin >= 3) flagsA++;
  for (const die of diesB.values()) if (die.bin >= 3) flagsB++;

  const coordinates = new Set([...diesA.keys(), ...diesB.keys()]);
  for (const coordinate of coordinates) {
    const dieA = diesA.get(coordinate);
    const dieB = diesB.get(coordinate);
    const flagA = dieA !== undefined && dieA.bin >= 3;
    const flagB = dieB !== undefined && dieB.bin >= 3;
    let category: WaferComparisonCategory;

    if (dieA === undefined) category = 'missingA';
    else if (dieB === undefined) category = 'missingB';
    else if (flagA && flagB) category = 'bothFlag';
    else if (flagA) category = 'aOnly';
    else if (flagB) category = 'bOnly';
    else category = 'neither';

    counts[category]++;
    dies.push({
      x: (dieA ?? dieB)!.x,
      y: (dieA ?? dieB)!.y,
      binA: dieA?.bin ?? null,
      binB: dieB?.bin ?? null,
      category,
    });
  }

  dies.sort((left, right) => left.y - right.y || left.x - right.x);
  const observedA = diesA.size;
  const observedB = diesB.size;
  const observedCommon =
    counts.bothFlag + counts.aOnly + counts.bOnly + counts.neither;
  const union = counts.bothFlag + counts.aOnly + counts.bOnly;
  const commonFlagsA = counts.bothFlag + counts.aOnly;
  const commonFlagsB = counts.bothFlag + counts.bOnly;
  const commonFailRateA =
    observedCommon === 0 ? null : commonFlagsA / observedCommon;
  const commonFailRateB =
    observedCommon === 0 ? null : commonFlagsB / observedCommon;

  return {
    gridId: a.gridId,
    dies,
    counts,
    observedA,
    observedB,
    observedCommon,
    validCompared: observedCommon,
    flagsA,
    flagsB,
    jaccard: union === 0 ? null : counts.bothFlag / union,
    failRateA: observedA === 0 ? null : flagsA / observedA,
    failRateB: observedB === 0 ? null : flagsB / observedB,
    commonFailRateA,
    commonFailRateB,
    delta:
      commonFailRateA === null || commonFailRateB === null
        ? null
        : commonFailRateA - commonFailRateB,
  };
}

export type CompositeDie = {
  x: number;
  y: number;
  flags: number;
  observed: number;
  percent: number;
};

export function compositeWaferMaps(maps: WaferMap[]): {
  waferCount: number;
  dies: CompositeDie[];
} {
  if (maps.length === 0) return { waferCount: 0, dies: [] };

  const gridId = maps[0].gridId;
  const waferKeys = new Set<string>();
  const aggregate = new Map<
    string,
    { x: number; y: number; flags: number; observed: number }
  >();

  for (const map of maps) {
    if (map.gridId !== gridId) throw new Error('Mixed wafer gridId values');
    const waferKey = JSON.stringify([map.lotId, map.waferId]);
    if (waferKeys.has(waferKey)) throw new Error('Duplicate lot/wafer tuple');
    waferKeys.add(waferKey);

    const mapCoordinates = new Set<string>();
    for (const die of map.dies) {
      if (
        !Number.isFinite(die.x) ||
        !Number.isFinite(die.y) ||
        !Number.isFinite(die.bin) ||
        !Number.isInteger(die.x) ||
        !Number.isInteger(die.y) ||
        !Number.isInteger(die.bin)
      ) {
        throw new Error('Die coordinates and bin must be finite integers');
      }
      const coordinate = JSON.stringify([die.x, die.y]);
      if (mapCoordinates.has(coordinate))
        throw new Error('Duplicate die coordinate within wafer map');
      mapCoordinates.add(coordinate);

      const current = aggregate.get(coordinate) ?? {
        x: die.x,
        y: die.y,
        flags: 0,
        observed: 0,
      };
      current.observed++;
      if (die.bin >= 3) current.flags++;
      aggregate.set(coordinate, current);
    }
  }

  return {
    waferCount: maps.length,
    dies: [...aggregate.values()]
      .map((die) => ({
        ...die,
        percent: (die.flags / die.observed) * 100,
      }))
      .sort((a, b) => a.y - b.y || a.x - b.x),
  };
}

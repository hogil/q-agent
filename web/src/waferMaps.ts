export type Die = { x: number; y: number; bin: number };

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

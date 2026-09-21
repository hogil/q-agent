export const panelRows = [
  ['signals', 'trend', 'correlation'],
  ['cohort', 'single-map', 'composite', 'images'],
  ['distribution', 'documents', 'production'],
] as const;

export type BoardLayout = {
  rows: number[];
  columns: number[][];
  workspace: number[];
};
export const layoutVersion = 3;
export const layoutStorageKey = `qagent:board-layout:v${layoutVersion}`;

export const defaultLayout = (): BoardLayout => ({
  rows: [0.4, 0.33, 0.27],
  workspace: [0.7, 0.3],
  columns: [
    [0.41, 0.37, 0.22],
    [0.21, 0.195, 0.195, 0.4],
    [0.32, 0.35, 0.33],
  ],
});
export const minRows = [260, 230, 190];
export const minWorkspace = [710, 350];
export const minColumns = [
  [360, 380, 250],
  [150, 150, 150, 260],
  [190, 230, 240],
];

export function parseLayout(raw: string | null): BoardLayout | null {
  try {
    const value = JSON.parse(raw || 'null');
    const valid = (sizes: unknown, count: number): sizes is number[] =>
      Array.isArray(sizes) &&
      sizes.length === count &&
      sizes.every(
        (n) => typeof n === 'number' && Number.isFinite(n) && n > 0 && n < 1,
      ) &&
      Math.abs(sizes.reduce((a, b) => a + b, 0) - 1) < 0.0001;
    if (
      value?.version !== layoutVersion ||
      !valid(value.rows, 3) ||
      !valid(value.workspace, 2) ||
      !Array.isArray(value.columns) ||
      value.columns.length !== 3 ||
      !value.columns.every((row: unknown, i: number) =>
        valid(row, panelRows[i].length),
      )
    )
      return null;
    return {
      rows: value.rows,
      columns: value.columns,
      workspace: value.workspace,
    };
  } catch {
    return null;
  }
}

export function minimumFractions(minimums: number[], pixels: number) {
  const total = minimums.reduce((a, b) => a + b, 0);
  return minimums.map((n) => n / Math.max(pixels, total));
}

// Keep the total extent fixed while enforcing readable minimum sizes.
export function fitSizes(sizes: number[], minimums: number[]) {
  const result = [...sizes];
  const fixed = new Set<number>();
  for (let pass = 0; pass < sizes.length; pass++) {
    const remaining = 1 - [...fixed].reduce((sum, i) => sum + result[i], 0);
    const weight = sizes.reduce((sum, n, i) => sum + (fixed.has(i) ? 0 : n), 0);
    let changed = false;
    sizes.forEach((n, i) => {
      if (fixed.has(i)) return;
      result[i] = weight ? (n / weight) * remaining : 0;
      if (result[i] < minimums[i]) {
        result[i] = minimums[i];
        fixed.add(i);
        changed = true;
      }
    });
    if (!changed) break;
  }
  return result;
}

export function moveBoundary(
  sizes: number[],
  index: number,
  delta: number,
  minimums: number[],
) {
  if (index < 0 || index >= sizes.length - 1 || !Number.isFinite(delta))
    return [...sizes];
  const result = [...sizes];
  const pair = sizes[index] + sizes[index + 1];
  result[index] = Math.max(
    minimums[index],
    Math.min(pair - minimums[index + 1], sizes[index] + delta),
  );
  result[index + 1] = pair - result[index];
  return result;
}

export function fitLayout(
  layout: BoardLayout,
  width: number,
  height: number,
): BoardLayout {
  const workspace = fitSizes(
    layout.workspace,
    minimumFractions(minWorkspace, width - 1),
  );
  return {
    workspace,
    rows: fitSizes(layout.rows, minimumFractions(minRows, height - 2)),
    columns: layout.columns.map((sizes, i) =>
      fitSizes(
        sizes,
        minimumFractions(
          minColumns[i],
          (i === 0 ? width : (width - 1) * workspace[0]) - sizes.length + 1,
        ),
      ),
    ),
  };
}

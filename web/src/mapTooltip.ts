export const MAP_TOOLTIP_EXTRA_CSS =
  'pointer-events:none;white-space:pre-line;max-width:min(260px,calc(100vw - 16px));overflow-wrap:anywhere;';

export const escapeMapTooltipText = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[
        character
      ]!,
  );

type TooltipLayoutSize = {
  contentSize?: readonly number[];
  viewSize?: readonly number[];
};

const finiteOr = (value: unknown, fallback: number) =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), Math.max(min, max));

/** Keep map tooltips beside the pointer while choosing an available quadrant. */
export function adaptiveMapTooltipPosition(
  point: readonly number[],
  _params: unknown,
  _dom: unknown,
  _rect: unknown,
  size: TooltipLayoutSize,
): [number, number] {
  const viewWidth = Math.max(0, finiteOr(size.viewSize?.[0], 0));
  const viewHeight = Math.max(0, finiteOr(size.viewSize?.[1], 0));
  const tooltipWidth = Math.max(0, finiteOr(size.contentSize?.[0], 0));
  const tooltipHeight = Math.max(0, finiteOr(size.contentSize?.[1], 0));
  const x = clamp(finiteOr(point[0], 0), 0, viewWidth);
  const y = clamp(finiteOr(point[1], 0), 0, viewHeight);
  const gap = 10;

  const candidates = [
    {
      left: x + gap,
      top: y + gap,
      available:
        Math.max(0, viewWidth - x - gap) * Math.max(0, viewHeight - y - gap),
    },
    {
      left: x - tooltipWidth - gap,
      top: y + gap,
      available: Math.max(0, x - gap) * Math.max(0, viewHeight - y - gap),
    },
    {
      left: x + gap,
      top: y - tooltipHeight - gap,
      available: Math.max(0, viewWidth - x - gap) * Math.max(0, y - gap),
    },
    {
      left: x - tooltipWidth - gap,
      top: y - tooltipHeight - gap,
      available: Math.max(0, x - gap) * Math.max(0, y - gap),
    },
  ];
  const fits = (candidate: (typeof candidates)[number]) =>
    candidate.left >= 0 &&
    candidate.top >= 0 &&
    candidate.left + tooltipWidth <= viewWidth &&
    candidate.top + tooltipHeight <= viewHeight;
  const ordered = candidates
    .map((candidate, index) => ({ candidate, index }))
    .sort(
      (left, right) =>
        right.candidate.available - left.candidate.available ||
        left.index - right.index,
    );
  const selected =
    ordered.find(({ candidate }) => fits(candidate))?.candidate ||
    ordered[0].candidate;

  return [
    clamp(selected.left, 0, viewWidth - tooltipWidth),
    clamp(selected.top, 0, viewHeight - tooltipHeight),
  ];
}

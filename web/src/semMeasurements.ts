export const SYNTHETIC_IMAGE_SIZE_PX = 1254;

export type SemPoint = { x: number; y: number };

export type SemMeasurement = {
  id: string;
  start: SemPoint;
  end: SemPoint;
};

export type SemMeasurementPreset = {
  metricLabel: string;
  measurements: SemMeasurement[];
};

export type SemImageSize = { width: number; height: number };

const measurement = (
  id: string,
  start: SemPoint,
  end: SemPoint,
): SemMeasurement => ({ id, start, end });

const preset = (
  metricLabel: string,
  measurements: SemMeasurement[],
): SemMeasurementPreset => ({ metricLabel, measurements });

// These are manually placed demo ROIs on the visible repeated structures in the
// current 1254 px synthetic assets. They are not automated edge detection.
const PRESETS: Record<string, SemMeasurementPreset> = {
  'synthetic-sem-thin-v2.png': preset('선폭', [
    measurement('m1', { x: 0.0175, y: 0.1994 }, { x: 0.0502, y: 0.1994 }),
    measurement('m2', { x: 0.2153, y: 0.4386 }, { x: 0.2360, y: 0.4386 }),
    measurement('m3', { x: 0.6643, y: 0.4386 }, { x: 0.6794, y: 0.4386 }),
  ]),
  'synthetic-sem-line-reference-v2.png': preset('선폭', [
    measurement('m1', { x: 0.0175, y: 0.1994 }, { x: 0.0502, y: 0.1994 }),
    measurement('m2', { x: 0.2097, y: 0.4386 }, { x: 0.2408, y: 0.4386 }),
    measurement('m3', { x: 0.6563, y: 0.4386 }, { x: 0.6874, y: 0.4386 }),
  ]),
  'synthetic-sem-wavy-v2.png': preset('선폭', [
    measurement('m1', { x: 0.0144, y: 0.1595 }, { x: 0.0486, y: 0.1595 }),
    measurement('m2', { x: 0.4147, y: 0.1595 }, { x: 0.4490, y: 0.1595 }),
    measurement('m3', { x: 0.6986, y: 0.1595 }, { x: 0.7313, y: 0.1595 }),
  ]),
  'synthetic-sem-alternating-v2.png': preset('굵은 선폭', [
    measurement('m1', { x: 0.0287, y: 0.1595 }, { x: 0.0678, y: 0.1595 }),
    measurement('m2', { x: 0.1571, y: 0.1595 }, { x: 0.1962, y: 0.1595 }),
    measurement('m3', { x: 0.2815, y: 0.1595 }, { x: 0.3206, y: 0.1595 }),
  ]),
  'synthetic-sem-contact-v2.png': preset('Contact 직경', [
    measurement('m1', { x: 0.0311, y: 0.0598 }, { x: 0.0821, y: 0.0598 }),
    measurement('m2', { x: 0.1459, y: 0.0598 }, { x: 0.1850, y: 0.0598 }),
    measurement('m3', { x: 0.2408, y: 0.0598 }, { x: 0.3086, y: 0.0598 }),
  ]),
  'synthetic-sem-contact-reference-v2.png': preset('Contact 직경', [
    measurement('m1', { x: 0.0311, y: 0.0598 }, { x: 0.0837, y: 0.0598 }),
    measurement('m2', { x: 0.1411, y: 0.0598 }, { x: 0.1930, y: 0.0598 }),
    measurement('m3', { x: 0.2512, y: 0.0598 }, { x: 0.3043, y: 0.0598 }),
  ]),
  'synthetic-sem-pillars-v2.png': preset('Pillar 직경', [
    measurement('m1', { x: 0.0407, y: 0.0598 }, { x: 0.1013, y: 0.0598 }),
    measurement('m2', { x: 0.1435, y: 0.0598 }, { x: 0.1978, y: 0.0598 }),
    measurement('m3', { x: 0.2424, y: 0.0598 }, { x: 0.3030, y: 0.0598 }),
  ]),
  'synthetic-sem-pillars-reference-v2.png': preset('Pillar 직경', [
    measurement('m1', { x: 0.0415, y: 0.0598 }, { x: 0.0989, y: 0.0598 }),
    measurement('m2', { x: 0.1443, y: 0.0598 }, { x: 0.1986, y: 0.0598 }),
    measurement('m3', { x: 0.2444, y: 0.0598 }, { x: 0.3043, y: 0.0598 }),
  ]),
  'synthetic-sem-lineends-v2.png': preset('Tip-to-tip gap', [
    measurement('m1', { x: 0.2105, y: 0.3158 }, { x: 0.2632, y: 0.3158 }),
    measurement('m2', { x: 0.4418, y: 0.3158 }, { x: 0.5407, y: 0.3158 }),
    measurement('m3', { x: 0.7368, y: 0.3158 }, { x: 0.7807, y: 0.3158 }),
  ]),
  'synthetic-sem-lineends-reference-v2.png': preset('Tip-to-tip gap', [
    measurement('m1', { x: 0.2265, y: 0.3158 }, { x: 0.2863, y: 0.3158 }),
    measurement('m2', { x: 0.4721, y: 0.3158 }, { x: 0.5295, y: 0.3158 }),
    measurement('m3', { x: 0.7177, y: 0.3158 }, { x: 0.7743, y: 0.3158 }),
  ]),
  'synthetic-sem-slots-v2.png': preset('Slot 폭', [
    measurement('m1', { x: 0.0463, y: 0.0797 }, { x: 0.0813, y: 0.0797 }),
    measurement('m2', { x: 0.1627, y: 0.0797 }, { x: 0.1978, y: 0.0797 }),
    measurement('m3', { x: 0.2815, y: 0.0797 }, { x: 0.3118, y: 0.0797 }),
  ]),
  'synthetic-sem-slots-reference-v2.png': preset('Slot 폭', [
    measurement('m1', { x: 0.0486, y: 0.0797 }, { x: 0.0813, y: 0.0797 }),
    measurement('m2', { x: 0.1643, y: 0.0797 }, { x: 0.1978, y: 0.0797 }),
    measurement('m3', { x: 0.2815, y: 0.0797 }, { x: 0.3126, y: 0.0797 }),
  ]),
  'synthetic-sem-serpentine-v2.png': preset('Trace 폭', [
    measurement('m1', { x: 0.1595, y: 0.0694 }, { x: 0.1595, y: 0.0981 }),
    measurement('m2', { x: 0.4785, y: 0.0678 }, { x: 0.4785, y: 0.0949 }),
    measurement('m3', { x: 0.7974, y: 0.0646 }, { x: 0.7974, y: 0.0941 }),
  ]),
  'synthetic-sem-serpentine-reference-v2.png': preset('Trace 폭', [
    measurement('m1', { x: 0.1595, y: 0.0694 }, { x: 0.1595, y: 0.0981 }),
    measurement('m2', { x: 0.4785, y: 0.0686 }, { x: 0.4785, y: 0.0973 }),
    measurement('m3', { x: 0.7974, y: 0.0686 }, { x: 0.7974, y: 0.0965 }),
  ]),
  'synthetic-sem-corners-v2.png': preset('Trace 폭', [
    measurement('m1', { x: 0.4529, y: 0.1994 }, { x: 0.4872, y: 0.1994 }),
    measurement('m2', { x: 0.9553, y: 0.1994 }, { x: 0.9904, y: 0.1994 }),
    measurement('m3', { x: 0.2584, y: 0.5383 }, { x: 0.2935, y: 0.5383 }),
  ]),
  'synthetic-sem-corners-reference-v2.png': preset('Trace 폭', [
    measurement('m1', { x: 0.4522, y: 0.1994 }, { x: 0.4872, y: 0.1994 }),
    measurement('m2', { x: 0.9553, y: 0.1994 }, { x: 0.9888, y: 0.1994 }),
    measurement('m3', { x: 0.2576, y: 0.5383 }, { x: 0.2943, y: 0.5383 }),
  ]),
};

export function semMeasurementPreset(src: string): SemMeasurementPreset | null {
  const filename = src.split('/').pop() || src;
  const found = PRESETS[filename];
  return found
    ? {
        metricLabel: found.metricLabel,
        measurements: found.measurements.map((item) => ({
          ...item,
          start: { ...item.start },
          end: { ...item.end },
        })),
      }
    : null;
}

export function measurementDistancePx(
  measurementValue: SemMeasurement,
  imageSize: SemImageSize | number = SYNTHETIC_IMAGE_SIZE_PX,
) {
  const width = typeof imageSize === 'number' ? imageSize : imageSize.width;
  const height = typeof imageSize === 'number' ? imageSize : imageSize.height;
  return (
    Math.hypot(
      (measurementValue.end.x - measurementValue.start.x) * width,
      (measurementValue.end.y - measurementValue.start.y) * height,
    )
  );
}

export function measurementAveragePx(
  measurements: readonly SemMeasurement[],
  imageSize: SemImageSize | number = SYNTHETIC_IMAGE_SIZE_PX,
) {
  if (!measurements.length) return null;
  return (
    measurements.reduce(
      (sum, item) => sum + measurementDistancePx(item, imageSize),
      0,
    ) / measurements.length
  );
}

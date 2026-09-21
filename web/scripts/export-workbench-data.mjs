#!/usr/bin/env node
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { makeTrendFleet } from '../src/anomalyTrend.ts';
import { makeEquipmentTrace } from '../src/equipmentComparison.ts';
import { makeEngineeringData } from '../src/engineeringData.ts';
import { makeInformNotes, semRecord } from '../src/investigationData.ts';

function fail(message) {
  throw new Error(`workbench export: ${message}`);
}

function parseArgs(argv) {
  const args = { baseUrl: 'http://127.0.0.1:8787', output: null };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--base-url') args.baseUrl = argv[++index];
    else if (value === '--output') args.output = argv[++index];
    else fail(`unknown argument ${value}`);
  }
  if (!args.output || !path.isAbsolute(args.output)) fail('--output must be an absolute path');
  const url = new URL(args.baseUrl);
  if (url.protocol !== 'http:' || url.username || url.password || !['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname)) {
    fail('--base-url must be an unauthenticated loopback HTTP URL');
  }
  return { ...args, baseUrl: url.toString().replace(/\/$/, '') };
}

async function getJson(baseUrl, requestPath) {
  let response;
  try {
    response = await fetch(`${baseUrl}${requestPath}`);
  } catch (error) {
    fail(`cannot reach ${requestPath}`);
  }
  if (!response.ok) fail(`${requestPath} returned HTTP ${response.status}`);
  try {
    return await response.json();
  } catch {
    fail(`${requestPath} returned invalid JSON`);
  }
}

const { baseUrl, output } = parseArgs(process.argv.slice(2));
const bootstrap = await getJson(baseUrl, '/api/bootstrap');
if (!bootstrap.synthetic || !Array.isArray(bootstrap.incidents)) fail('bootstrap is not a synthetic workbench response');
const incidents = {};
for (const incident of bootstrap.incidents) {
  if (!incident?.incident_number) fail('bootstrap incident has no incident_number');
  const workspace = await getJson(baseUrl, `/api/workspace?incident=${encodeURIComponent(incident.incident_number)}`);
  const data = makeEngineeringData(workspace);
  const engineering = Object.fromEntries(
    ['signals', 'trend', 'fab', 'yields', 'wip', 'downtime', 'changes'].map((key) => [key, data[key]]),
  );
  const trendFleets = Object.fromEntries(
    engineering.signals.map((signal) => [signal.id, makeTrendFleet(data, signal)]),
  );
  const comparisonTraces = Object.fromEntries(
    engineering.signals.map((signal) => {
      const usesEquipmentAxis = !signal.legendAxis || signal.legendAxis === 'eqp_id';
      if (!usesEquipmentAxis) return [signal.id, {}];
      const equipment = [...new Set(
        engineering.signals
          .filter((candidate) => candidate.step === signal.step)
          .map((candidate) => candidate.equipment),
      )];
      return [signal.id, Object.fromEntries(
        equipment.map((equipment) => [equipment, makeEquipmentTrace(data, signal, equipment)]),
      )];
    }),
  );
  const informNotes = makeInformNotes(data);
  const semAssets = workspace.wafers
    .map((wafer) => semRecord(workspace, wafer.lot_id, wafer.wafer_id))
    .filter(Boolean);
  incidents[incident.incident_number] = {
    engineering,
    trend_fleets: trendFleets,
    comparison_traces: comparisonTraces,
    inform_notes: informNotes,
    sem_assets: semAssets,
  };
}
const payload = `${JSON.stringify({ version: 1, synthetic: true, incidents }, null, 2)}\n`;
try {
  await writeFile(output, payload, { encoding: 'utf8', flag: 'wx' });
} catch (error) {
  if (error?.code === 'EEXIST') fail('output already exists; refusing overwrite');
  fail('cannot create output file');
}
console.log(`wrote synthetic workbench data: ${output}`);

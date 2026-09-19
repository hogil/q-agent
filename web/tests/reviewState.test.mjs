import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clearReviewDraft,
  loadReviewDraft,
  saveReviewDraft,
} from '../src/reviewState.ts';

function createStorage() {
  const values = new Map();
  return {
    values,
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

function draft(overrides = {}) {
  return {
    text: 'review text',
    notes: 'review notes',
    attachments: [
      {
        kind: 'data',
        label: 'Incident data',
        id: 'data-1',
        incident_number: 'incident-a',
      },
    ],
    ...overrides,
  };
}

test('round trips a draft within its room and incident scope', () => {
  const storage = createStorage();
  const value = draft();

  assert.equal(saveReviewDraft(storage, 'room-a', 'incident-a', value), true);
  assert.deepEqual(loadReviewDraft(storage, 'room-a', 'incident-a'), value);
});

test('isolates drafts by both room and incident', () => {
  const storage = createStorage();
  const value = draft({ text: 'scoped' });

  saveReviewDraft(storage, 'room-a', 'incident-a', value);

  assert.deepEqual(loadReviewDraft(storage, 'room-b', 'incident-a'), {
    text: '',
    attachments: [],
    notes: '',
  });
  assert.deepEqual(loadReviewDraft(storage, 'room-a', 'incident-b'), {
    text: '',
    attachments: [],
    notes: '',
  });
});

test('rejects malformed JSON, invalid shapes, wrong versions, and wrong context', () => {
  const storage = createStorage();
  const key = 'review-draft:v1:room-a:incident-a';
  const empty = { text: '', attachments: [], notes: '' };

  storage.values.set(key, '{not-json');
  assert.deepEqual(loadReviewDraft(storage, 'room-a', 'incident-a'), empty);

  storage.values.set(key, JSON.stringify({ version: 1, roomId: 'room-a' }));
  assert.deepEqual(loadReviewDraft(storage, 'room-a', 'incident-a'), empty);

  storage.values.set(
    key,
    JSON.stringify({
      version: 2,
      roomId: 'room-a',
      incidentNumber: 'incident-a',
      draft: draft(),
    }),
  );
  assert.deepEqual(loadReviewDraft(storage, 'room-a', 'incident-a'), empty);

  storage.values.set(
    key,
    JSON.stringify({
      version: 1,
      roomId: 'room-b',
      incidentNumber: 'incident-a',
      draft: draft(),
    }),
  );
  assert.deepEqual(loadReviewDraft(storage, 'room-a', 'incident-a'), empty);
});

test('returns fallback values when storage throws', () => {
  const throwingStorage = {
    getItem() {
      throw new Error('read failed');
    },
    setItem() {
      throw new Error('write failed');
    },
    removeItem() {
      throw new Error('remove failed');
    },
  };

  assert.deepEqual(loadReviewDraft(throwingStorage, 'room-a', 'incident-a'), {
    text: '',
    attachments: [],
    notes: '',
  });
  assert.equal(
    saveReviewDraft(throwingStorage, 'room-a', 'incident-a', draft()),
    false,
  );
  assert.equal(
    clearReviewDraft(throwingStorage, 'room-a', 'incident-a'),
    false,
  );
});

test('handles null storage without reading, writing, or clearing', () => {
  assert.deepEqual(loadReviewDraft(null, 'room-a', 'incident-a'), {
    text: '',
    attachments: [],
    notes: '',
  });
  assert.equal(saveReviewDraft(null, 'room-a', 'incident-a', draft()), false);
  assert.equal(clearReviewDraft(null, 'room-a', 'incident-a'), false);
});

test('rejects all specified save limits and invalid attachment fields', () => {
  const storage = createStorage();
  const valid = draft();

  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      text: 'x'.repeat(12_001),
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      notes: 'x'.repeat(8_001),
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: Array.from({ length: 9 }, () => valid.attachments[0]),
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [{ ...valid.attachments[0], kind: 'other' }],
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [{ ...valid.attachments[0], label: '' }],
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [{ ...valid.attachments[0], id: 'x'.repeat(257) }],
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [{ ...valid.attachments[0], incident_number: '' }],
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [
        { ...valid.attachments[0], incident_number: 'x'.repeat(101) },
      ],
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [{ ...valid.attachments[0], label: '   ' }],
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [{ ...valid.attachments[0], id: '\t\n' }],
    }),
    false,
  );
  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', {
      ...valid,
      attachments: [{ ...valid.attachments[0], incident_number: '  ' }],
    }),
    false,
  );
});

test('accepts exact field boundaries and sanitizes unknown attachment fields', () => {
  const storage = createStorage();
  const boundary = {
    text: 't'.repeat(12_000),
    notes: 'n'.repeat(8_000),
    attachments: Array.from({ length: 8 }, (_, index) => ({
      kind: 'request',
      label: `l${'x'.repeat(254)}${index}`.slice(0, 256),
      id: `i${'x'.repeat(254)}${index}`.slice(0, 256),
      incident_number: `n${'x'.repeat(98)}${index}`.slice(0, 100),
      unknown: 'must not persist',
    })),
  };

  assert.equal(
    saveReviewDraft(storage, 'room-a', 'incident-a', boundary),
    true,
  );
  const loaded = loadReviewDraft(storage, 'room-a', 'incident-a');
  assert.equal(loaded.text.length, 12_000);
  assert.equal(loaded.notes.length, 8_000);
  assert.equal(loaded.attachments.length, 8);
  assert.equal(Object.hasOwn(loaded.attachments[0], 'unknown'), false);
  assert.deepEqual(loaded.attachments[0], {
    kind: 'request',
    label: `l${'x'.repeat(254)}0`.slice(0, 256),
    id: `i${'x'.repeat(254)}0`.slice(0, 256),
    incident_number: `n${'x'.repeat(98)}0`.slice(0, 100),
  });
});

test('keeps encoded room and incident separators isolated', () => {
  const storage = createStorage();
  saveReviewDraft(
    storage,
    'room:a',
    'incident',
    draft({ text: 'first scope' }),
  );
  saveReviewDraft(
    storage,
    'room',
    'a:incident',
    draft({ text: 'second scope' }),
  );

  assert.equal(
    loadReviewDraft(storage, 'room:a', 'incident').text,
    'first scope',
  );
  assert.equal(
    loadReviewDraft(storage, 'room', 'a:incident').text,
    'second scope',
  );
});

test('clear removes only its own scoped key', () => {
  const storage = createStorage();
  saveReviewDraft(storage, 'room-a', 'incident-a', draft());
  saveReviewDraft(storage, 'room-b', 'incident-a', draft({ text: 'keep me' }));

  assert.equal(clearReviewDraft(storage, 'room-a', 'incident-a'), true);
  assert.deepEqual(loadReviewDraft(storage, 'room-a', 'incident-a'), {
    text: '',
    attachments: [],
    notes: '',
  });
  assert.equal(
    loadReviewDraft(storage, 'room-b', 'incident-a').text,
    'keep me',
  );
  assert.equal(storage.values.size, 1);
});

test('returns independent empty defaults and does not share loaded arrays', () => {
  const storage = createStorage();
  const first = loadReviewDraft(storage, 'room-a', 'incident-a');
  first.attachments.push({ kind: 'data', label: 'local', id: 'local' });
  first.text = 'local';

  const second = loadReviewDraft(storage, 'room-a', 'incident-a');
  assert.deepEqual(second, { text: '', attachments: [], notes: '' });

  saveReviewDraft(storage, 'room-a', 'incident-a', draft());
  const loaded = loadReviewDraft(storage, 'room-a', 'incident-a');
  loaded.attachments[0].label = 'changed locally';
  assert.equal(
    loadReviewDraft(storage, 'room-a', 'incident-a').attachments[0].label,
    'Incident data',
  );
});

import type { Attachment } from './api';

export type ReviewDraft = {
  text: string;
  attachments: Attachment[];
  notes: string;
};

type ReviewDraftEnvelope = {
  version: 1;
  roomId: string;
  incidentNumber: string;
  draft: ReviewDraft;
};

type ReviewStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null;

const STORAGE_VERSION = 1;
const TEXT_LIMIT = 12_000;
const NOTES_LIMIT = 8_000;
const ATTACHMENT_LIMIT = 8;
const ATTACHMENT_TEXT_LIMIT = 256;
const INCIDENT_NUMBER_LIMIT = 100;
const ATTACHMENT_KINDS = new Set([
  'data',
  'inform',
  'map',
  'image',
  'trend',
  'history',
  'request',
]);

function emptyReviewDraft(): ReviewDraft {
  return { text: '', attachments: [], notes: '' };
}

function storageKey(roomId: string, incidentNumber: string): string {
  return `review-draft:v${STORAGE_VERSION}:${encodeURIComponent(roomId)}:${encodeURIComponent(incidentNumber)}`;
}

function isBoundedString(value: unknown, limit: number): value is string {
  return (
    typeof value === 'string' &&
    value.trim().length > 0 &&
    value.length <= limit
  );
}

function isValidAttachment(value: unknown): value is Attachment {
  if (typeof value !== 'object' || value === null) return false;

  const attachment = value as Partial<Attachment>;
  if (
    typeof attachment.kind !== 'string' ||
    !ATTACHMENT_KINDS.has(attachment.kind) ||
    !isBoundedString(attachment.label, ATTACHMENT_TEXT_LIMIT) ||
    !isBoundedString(attachment.id, ATTACHMENT_TEXT_LIMIT)
  ) {
    return false;
  }

  return (
    attachment.incident_number === undefined ||
    isBoundedString(attachment.incident_number, INCIDENT_NUMBER_LIMIT)
  );
}

function isValidReviewDraft(value: unknown): value is ReviewDraft {
  if (typeof value !== 'object' || value === null) return false;

  const draft = value as Partial<ReviewDraft>;
  return (
    typeof draft.text === 'string' &&
    draft.text.length <= TEXT_LIMIT &&
    typeof draft.notes === 'string' &&
    draft.notes.length <= NOTES_LIMIT &&
    Array.isArray(draft.attachments) &&
    draft.attachments.length <= ATTACHMENT_LIMIT &&
    draft.attachments.every(isValidAttachment)
  );
}

function copyDraft(draft: ReviewDraft): ReviewDraft {
  return {
    text: draft.text,
    notes: draft.notes,
    attachments: draft.attachments.map(
      ({ kind, label, id, incident_number }) => ({
        kind,
        label,
        id,
        ...(incident_number === undefined ? {} : { incident_number }),
      }),
    ),
  };
}

function isValidEnvelope(
  value: unknown,
  roomId: string,
  incidentNumber: string,
): value is ReviewDraftEnvelope {
  if (typeof value !== 'object' || value === null) return false;

  const envelope = value as Partial<ReviewDraftEnvelope>;
  return (
    envelope.version === STORAGE_VERSION &&
    envelope.roomId === roomId &&
    envelope.incidentNumber === incidentNumber &&
    isValidReviewDraft(envelope.draft)
  );
}

export function loadReviewDraft(
  storage: ReviewStorage,
  roomId: string,
  incidentNumber: string,
): ReviewDraft {
  try {
    if (storage === null) return emptyReviewDraft();

    const raw = storage.getItem(storageKey(roomId, incidentNumber));
    if (raw === null) return emptyReviewDraft();

    const value: unknown = JSON.parse(raw);
    return isValidEnvelope(value, roomId, incidentNumber)
      ? copyDraft(value.draft)
      : emptyReviewDraft();
  } catch {
    return emptyReviewDraft();
  }
}

export function saveReviewDraft(
  storage: ReviewStorage,
  roomId: string,
  incidentNumber: string,
  draft: ReviewDraft,
): boolean {
  try {
    if (storage === null || !isValidReviewDraft(draft)) return false;

    const value: ReviewDraftEnvelope = {
      version: STORAGE_VERSION,
      roomId,
      incidentNumber,
      draft: copyDraft(draft),
    };
    storage.setItem(storageKey(roomId, incidentNumber), JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function clearReviewDraft(
  storage: ReviewStorage,
  roomId: string,
  incidentNumber: string,
): boolean {
  try {
    if (storage === null) return false;

    storage.removeItem(storageKey(roomId, incidentNumber));
    return true;
  } catch {
    return false;
  }
}

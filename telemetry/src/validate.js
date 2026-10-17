import { schema, allowedFields } from './schema.js';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
const QUOTED = /"[^"\n]{1,200}"|'[^'\n]{2,200}'/g;
const KNOWN_PATH = /(?:\/(?:storage|sdcard|data|mnt|home|root|Users|proc|system|vendor|apex)\/[^\s)"']*|\b[A-Za-z]:\\[^\s)"']*)/g;
const LOOKS_LIKE_PATH = /(?:^|[\s=:(])\/[\w.@-]+\/[\w.@-]+|\b[A-Za-z]:\\|\/(?:storage|sdcard)\b/;
const WEEK_MS = 7 * 24 * 3600 * 1000;
const FUTURE_MS = 5 * 60 * 1000;

export const scrub = (text) =>
  text.replace(EMAIL, '<email>').replace(KNOWN_PATH, '<path>').replace(QUOTED, '<text>');

export function flatten(object, prefix = '', out = {}) {
  for (const [key, value] of Object.entries(object)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) flatten(value, name, out);
    else out[name] = value;
  }
  return out;
}

/** Cleans one value against its field spec. Returns undefined to drop the field, throws {reason} to reject the event. */
function cleanValue(name, spec, value) {
  switch (spec.type) {
    case 'keyword':
    case 'text':
    case 'wildcard': {
      if (typeof value !== 'string') return undefined;
      let text = value;
      if (spec.free_text) text = scrub(text);
      if (LOOKS_LIKE_PATH.test(text)) throw { reason: 'privacy' };
      text = text.slice(0, spec.max ?? 100);
      if (spec.uuid && !UUID.test(text)) throw { reason: 'invalid' };
      if (spec.enum && !spec.enum.includes(text)) return undefined;
      if (spec.pattern && !new RegExp(spec.pattern).test(text)) return undefined;
      return text;
    }
    case 'long':
    case 'integer':
    case 'float': {
      if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
      const clamped = Math.min(Math.max(value, spec.min ?? -Infinity), spec.max ?? Infinity);
      return spec.type === 'float' ? clamped : Math.trunc(clamped);
    }
    case 'boolean':
      return typeof value === 'boolean' ? value : undefined;
    case 'date':
      return typeof value === 'string' && !Number.isNaN(Date.parse(value)) ? value : undefined;
    default:
      return undefined;
  }
}

/**
 * Validates one parsed event. Returns {doc} or {reason} (invalid | privacy | schema).
 * Unknown fields are dropped; out-of-range numbers are clamped; a bad timestamp is replaced by the receive time.
 */
export function validateEvent(raw, now = Date.now(), ingestVersion = '1') {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { reason: 'invalid' };
  const flat = flatten(raw);
  const dataset = flat['event.dataset'];
  if (typeof dataset !== 'string' || !schema.datasets[dataset]) return { reason: 'invalid' };
  const allowed = allowedFields(dataset);

  try {
    const doc = {};
    for (const [name, value] of Object.entries(flat)) {
      if (!allowed.has(name)) continue;
      const cleaned = cleanValue(name, schema.fields[name], value);
      if (cleaned !== undefined) doc[name] = cleaned;
    }
    for (const name of schema.required) if (doc[name] === undefined) return { reason: 'invalid' };

    if (doc['skynet.telemetry.schema'] < schema.minimumVersion) return { reason: 'schema' };
    const actions = schema.datasets[dataset].actions;
    if (actions && !actions.includes(doc['event.action'])) return { reason: 'invalid' };

    const time = Date.parse(doc['@timestamp']);
    if (time < now - WEEK_MS || time > now + FUTURE_MS) {
      doc['skynet.client_timestamp'] = doc['@timestamp'];
      doc['skynet.timestamp_fixed'] = true;
      doc['@timestamp'] = new Date(now).toISOString();
    }
    doc['event.ingested'] = new Date(now).toISOString();
    doc['skynet.ingest.version'] = ingestVersion;
    return { doc };
  } catch (error) {
    if (error && error.reason) return { reason: error.reason };
    throw error;
  }
}

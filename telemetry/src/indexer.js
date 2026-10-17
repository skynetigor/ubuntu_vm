import { appendFileSync, existsSync, renameSync, statSync } from 'node:fs';
import { indexFor } from './schema.js';

const MAX_ATTEMPTS = 5;
const DEAD_LETTER_MAX_BYTES = 50 * 1024 * 1024;

/** In-memory queue flushed to Elasticsearch with _bulk every `flushMs` or `batchSize` documents. */
export class Indexer {
  constructor({ esUrl, headers, queueMax, deadLetterPath, metrics, log, flushMs = 1000, batchSize = 500, fetchImpl = fetch }) {
    Object.assign(this, { esUrl, headers, queueMax, deadLetterPath, metrics, log, flushMs, batchSize, fetchImpl });
    this.queue = [];
    this.flushing = false;
    this.stopped = false;
    this.timer = setInterval(() => this.flush(), flushMs);
    this.timer.unref();
  }

  get depth() { return this.queue.length; }

  /** Returns false when the queue is full. */
  enqueue(docs) {
    if (this.queue.length + docs.length > this.queueMax) return false;
    for (const doc of docs) this.queue.push({ doc, attempts: 0, notBefore: 0 });
    if (this.queue.length >= this.batchSize) this.flush();
    return true;
  }

  deadLetter(entry, reason) {
    this.metrics.inc('dead_letter');
    try {
      if (existsSync(this.deadLetterPath) && statSync(this.deadLetterPath).size > DEAD_LETTER_MAX_BYTES) {
        renameSync(this.deadLetterPath, `${this.deadLetterPath}.1`);
      }
      appendFileSync(this.deadLetterPath, JSON.stringify({ reason, doc: entry.doc }) + '\n');
    } catch (error) {
      this.log('error', 'dead_letter_write_failed', { error: String(error) });
    }
  }

  retryOrDrop(entry, reason) {
    entry.attempts += 1;
    if (entry.attempts >= MAX_ATTEMPTS) return this.deadLetter(entry, reason);
    entry.notBefore = Date.now() + Math.min(30000, 1000 * 2 ** entry.attempts);
    this.queue.push(entry);
  }

  async flush() {
    if (this.flushing || !this.queue.length) return;
    this.flushing = true;
    try {
      const now = Date.now();
      const ready = [];
      const later = [];
      for (const entry of this.queue) (entry.notBefore <= now && ready.length < this.batchSize ? ready : later).push(entry);
      this.queue = later;
      if (!ready.length) return;

      const body = ready.flatMap(({ doc }) => [
        JSON.stringify({ create: { _index: indexFor(doc['event.dataset']), _id: doc['event.id'] } }),
        JSON.stringify(doc),
      ]).join('\n') + '\n';
      const started = Date.now();
      let response;
      try {
        response = await this.fetchImpl(`${this.esUrl}/_bulk`, {
          method: 'POST', headers: { ...this.headers, 'content-type': 'application/x-ndjson' }, body,
          signal: AbortSignal.timeout(30000),
        });
      } catch (error) {
        this.metrics.inc('es_errors');
        ready.forEach((entry) => this.retryOrDrop(entry, `request failed: ${error}`));
        return;
      }
      this.metrics.observe('bulk_ms', Date.now() - started);
      this.metrics.observe('bulk_docs', ready.length);
      if (!response.ok) {
        this.metrics.inc('es_errors');
        ready.forEach((entry) => this.retryOrDrop(entry, `bulk status ${response.status}`));
        return;
      }
      const result = await response.json();
      result.items.forEach((item, index) => {
        const outcome = item.create ?? item.index ?? {};
        const status = outcome.status;
        if (status < 300) this.metrics.inc('indexed');
        else if (status === 409) this.metrics.inc('duplicates'); // a retry after a lost reply: already stored
        else if (status === 429 || status >= 500) { this.metrics.inc('es_errors'); this.retryOrDrop(ready[index], JSON.stringify(outcome.error)); }
        else this.deadLetter(ready[index], JSON.stringify(outcome.error)); // mapping or other permanent error
      });
    } finally {
      this.flushing = false;
    }
  }

  /** Stops accepting and drains the queue for up to `timeoutMs`. */
  async drain(timeoutMs = 10000) {
    this.stopped = true;
    const deadline = Date.now() + timeoutMs;
    while (this.queue.length && Date.now() < deadline) {
      this.queue.forEach((entry) => { entry.notBefore = 0; });
      await this.flush();
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    clearInterval(this.timer);
  }
}

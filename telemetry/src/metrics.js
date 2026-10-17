export class Metrics {
  constructor() { this.counters = {}; this.sums = {}; }

  inc(name, labels = '', by = 1) {
    const key = labels ? `${name}{${labels}}` : name;
    this.counters[key] = (this.counters[key] ?? 0) + by;
  }

  observe(name, value) {
    this.sums[`${name}_sum`] = (this.sums[`${name}_sum`] ?? 0) + value;
    this.sums[`${name}_count`] = (this.sums[`${name}_count`] ?? 0) + 1;
  }

  render(gauges = {}) {
    const lines = [];
    for (const [key, value] of Object.entries({ ...this.counters, ...this.sums, ...gauges })) {
      lines.push(`skynet_ingest_${key} ${value}`);
    }
    return lines.join('\n') + '\n';
  }
}

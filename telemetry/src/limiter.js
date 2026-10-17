import { createHash, randomBytes } from 'node:crypto';

/** Token buckets in memory: `perHour` tokens refill evenly, `burst` is the capacity. */
export class RateLimiter {
  constructor({ perHour, burst, maxKeys = 200000 }) {
    this.rate = perHour / 3600000;
    this.burst = burst ?? perHour;
    this.maxKeys = maxKeys;
    this.buckets = new Map();
  }

  /** Takes up to `count` tokens and returns how many were granted. */
  take(key, count = 1, now = Date.now()) {
    let bucket = this.buckets.get(key);
    if (!bucket) {
      if (this.buckets.size >= this.maxKeys) this.sweep(now);
      bucket = { tokens: this.burst, at: now };
      this.buckets.set(key, bucket);
    }
    bucket.tokens = Math.min(this.burst, bucket.tokens + (now - bucket.at) * this.rate);
    bucket.at = now;
    const granted = Math.min(count, Math.floor(bucket.tokens));
    bucket.tokens -= granted;
    return granted;
  }

  sweep(now) {
    for (const [key, bucket] of this.buckets) {
      if (bucket.tokens + (now - bucket.at) * this.rate >= this.burst) this.buckets.delete(key);
    }
    if (this.buckets.size >= this.maxKeys) this.buckets.clear();
  }
}

/** Source address as a salted hash that exists only in RAM; the salt rotates daily and is never persisted. */
export class AddressHasher {
  constructor() { this.rotate(); }

  rotate() {
    this.salt = randomBytes(16);
    this.at = Date.now();
  }

  hash(address) {
    if (Date.now() - this.at > 24 * 3600 * 1000) this.rotate();
    return createHash('sha256').update(this.salt).update(String(address)).digest('base64url').slice(0, 22);
  }
}

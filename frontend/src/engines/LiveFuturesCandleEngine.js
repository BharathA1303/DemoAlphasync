const INTERVAL_MS = {
  '1m':  60_000,
  '5m':  300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h':  3_600_000,
  '1d':  86_400_000,
};

const IST_OFFSET_MS = 5.5 * 3600 * 1000;

function parseIntervalMs(interval) {
  return INTERVAL_MS[interval] || 300_000;
}

function computeBucketStartSec(tickEpochMs, intervalMs, interval) {
  if (interval === '1d') {
    const istMs = tickEpochMs + IST_OFFSET_MS;
    const dayStartIst = Math.floor(istMs / 86_400_000) * 86_400_000;
    return Math.floor((dayStartIst - IST_OFFSET_MS) / 1000);
  }
  const bucketStartMs = Math.floor(tickEpochMs / intervalMs) * intervalMs;
  return Math.floor(bucketStartMs / 1000);
}

export class LiveFuturesCandleEngine {
  constructor() {
    this._currentCandle = null;
    this._lastClosedCandle = null;
    this._interval = '5m';
    this._intervalMs = 300_000;
    this._historicalCandles = [];
    this._lastTickTime = null;
    this._lastCumulativeVolume = null;
  }

  setInterval(interval) {
    const ms = parseIntervalMs(interval);
    if (interval === this._interval) return;
    this._interval = interval;
    this._intervalMs = ms;
    this._currentCandle = null;
    this._lastClosedCandle = null;
    this._lastCumulativeVolume = null;
    this._lastTickTime = null;
  }

  setHistoricalCandles(candles) {
    this._historicalCandles = candles ? [...candles] : [];
  }

  onTick(tick) {
    const ltp = tick.ltp;
    if (ltp == null || ltp === 0) return null;

    const tickEpochMs =
      typeof tick.timestamp === 'number'
        ? tick.timestamp > 1e12 ? tick.timestamp : tick.timestamp * 1000
        : new Date(tick.timestamp).getTime();

    if (Number.isNaN(tickEpochMs)) return null;

    const bucketStartSec = computeBucketStartSec(
      tickEpochMs,
      this._intervalMs,
      this._interval,
    );

    let volumeDelta = 0;
    if (tick.volume != null) {
      if (this._lastCumulativeVolume != null) {
        const raw = tick.volume - this._lastCumulativeVolume;
        volumeDelta = raw < 0 ? tick.volume : raw;
      }
      this._lastCumulativeVolume = tick.volume;
    }

    let isNew = false;

    if (!this._currentCandle || this._currentCandle.time !== bucketStartSec) {
      if (this._currentCandle) {
        this._lastClosedCandle = { ...this._currentCandle };
      }

      this._currentCandle = {
        time: bucketStartSec,
        open: ltp,
        high: ltp,
        low: ltp,
        close: ltp,
        volume: volumeDelta,
      };
      isNew = true;
    } else {
      this._currentCandle.high = Math.max(this._currentCandle.high, ltp);
      this._currentCandle.low = Math.min(this._currentCandle.low, ltp);
      this._currentCandle.close = ltp;
      this._currentCandle.volume += volumeDelta;
    }

    this._lastTickTime = tickEpochMs;

    return { candle: { ...this._currentCandle }, isNew };
  }

  getAllCandles() {
    if (!this._currentCandle) return [...this._historicalCandles];

    const hist = this._historicalCandles;
    if (
      hist.length > 0 &&
      hist[hist.length - 1].time >= this._currentCandle.time
    ) {
      return [...hist.slice(0, -1), { ...this._currentCandle }];
    }

    return [...hist, { ...this._currentCandle }];
  }

  getLiveCandle() {
    return this._currentCandle ? { ...this._currentCandle } : null;
  }

  getLastClosedCandle() {
    if (this._lastClosedCandle) return { ...this._lastClosedCandle };
    if (this._historicalCandles.length > 0) {
      return { ...this._historicalCandles[this._historicalCandles.length - 1] };
    }
    return null;
  }

  reset() {
    this._currentCandle = null;
    this._lastClosedCandle = null;
    this._historicalCandles = [];
    this._lastTickTime = null;
    this._lastCumulativeVolume = null;
  }
}

export const liveFuturesCandleEngine = new LiveFuturesCandleEngine();

// ── Original strategies ──
export { meta as movingAverageMeta, runStrategy as runMovingAverage } from './movingAverage';
export { meta as rsiMomentumMeta, runStrategy as runRsiMomentum } from './rsiMomentum';
export { meta as vwapMeta, runStrategy as runVwapStrategy } from './vwapStrategy';
export { meta as goldenRsiMeta, runStrategy as runGoldenRsi } from './goldenRsi';
export { meta as trendDetectorMeta, runStrategy as runTrendDetector } from './trendDetector';

// ── Gold ScalpingPro strategies (ported from MQ4 EA) ──
export { meta as emaCrossMeta, runStrategy as runEmaCross } from './emaCross';
export { meta as adxMeta, runStrategy as runAdxStrategy } from './adxStrategy';
export { meta as cciMeta, runStrategy as runCciStrategy } from './cciStrategy';
export { meta as macdHistMeta, runStrategy as runMacdHistogram } from './macdHistogram';
export { meta as stochasticMeta, runStrategy as runStochastic } from './stochasticStrategy';
export { meta as bollingerMeta, runStrategy as runBollinger } from './bollingerStrategy';
export { meta as ichimokuMeta, runStrategy as runIchimoku } from './ichimokuStrategy';
export { meta as hmaMeta, runStrategy as runHma } from './hmaStrategy';
export { meta as supertrendMeta, runStrategy as runSupertrend } from './supertrendStrategy';
export { meta as atrBreakoutMeta, runStrategy as runAtrBreakout } from './atrBreakout';

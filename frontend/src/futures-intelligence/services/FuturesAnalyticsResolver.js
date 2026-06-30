/**
 * Aggregates real Zebu quotes into analytics snapshot — pure, memo-friendly.
 */
import { sortContractsByExpiry, quoteLtp, quoteChangePct } from '../utils/futuresCalculations';
import { aggregateOI } from './FuturesOIEngine';
import { aggregateVolume } from './FuturesVolumeEngine';
import { resolveBasisForContract } from './FuturesBasisEngine';
import { classifyTrendFromQuote } from './FuturesTrendEngine';
import { getFuturesSessionLabel } from '../utils/futuresSessionUtils';

function buildExpiryRow(contract, quote, spotQuote) {
  const sym = contract.contract_symbol;
  const { premium, basis, futureLtp, spotLtp } = resolveBasisForContract(quote, spotQuote);

  return {
    contractSymbol: sym,
    label: contract.expiry_label || '—',
    expiryDate: contract.expiry_date,
    daysToExpiry: contract.days_to_expiry,
    ltp: futureLtp,
    changePct: quoteChangePct(quote),
    premium,
    basis,
    oi: quote?.oi != null ? Number(quote.oi) : null,
    volume: quote?.volume != null ? Number(quote.volume ?? quote.v) : null,
    oiChange: quote?.oi_change != null ? Number(quote.oi_change) : null,
    tier: quote?._tier,
    _illiquid: quote?._illiquid,
    spotLtp,
  };
}

/**
 * @param {object} params
 * @param {string|null} params.underlying
 * @param {string|null} params.selectedContract
 * @param {object} params.bySymbol
 * @param {object} params.byUnderlying
 * @param {object} params.quotes
 * @param {object|null} params.spotQuote — from GET /futures/spot/{underlying}
 */
export function resolveFuturesAnalytics({
  underlying,
  selectedContract,
  bySymbol = {},
  byUnderlying = {},
  quotes = {},
  spotQuote = null,
}) {
  if (!underlying) {
    return {
      underlying: null,
      session: getFuturesSessionLabel(),
      spot: null,
      atmFuture: null,
      premium: null,
      basis: null,
      totalOI: null,
      totalVolume: null,
      trend: 'Neutral',
      expiryRows: [],
    };
  }

  const symbols = byUnderlying[underlying] || [];
  const contracts = sortContractsByExpiry(
    symbols.map((s) => bySymbol[s]).filter(Boolean),
  );

  const expiryRows = contracts.map((c) =>
    buildExpiryRow(c, quotes[c.contract_symbol], spotQuote),
  );

  const totalOI = aggregateOI(quotes, symbols);
  const totalVolume = aggregateVolume(quotes, symbols);

  const atmContract = selectedContract || contracts[0]?.contract_symbol;
  const atmQuote = atmContract ? quotes[atmContract] : null;
  const { premium, basis, futureLtp, spotLtp } = resolveBasisForContract(atmQuote, spotQuote);

  const trend = atmQuote ? classifyTrendFromQuote(atmQuote) : 'Neutral';

  const spotAvailable = spotQuote?.available !== false && Number.isFinite(Number(spotQuote?.ltp));

  return {
    underlying,
    session: getFuturesSessionLabel(),
    spot: spotAvailable
      ? {
          ltp: Number(spotQuote.ltp),
          change: Number(spotQuote.change) || null,
          changePct: Number(spotQuote.change_pct) || null,
        }
      : null,
    atmFuture: futureLtp != null
      ? { symbol: atmContract, ltp: futureLtp, changePct: quoteChangePct(atmQuote) }
      : null,
    premium,
    basis,
    totalOI,
    totalVolume,
    trend,
    expiryRows,
  };
}

import { computePremium, computeBasis } from './FuturesPremiumEngine';
import { quoteLtp } from '../utils/futuresCalculations';

export function resolveBasisForContract(contractQuote, spotQuote) {
  const futureLtp = quoteLtp(contractQuote);
  const spotLtp = spotQuote?.ltp != null ? Number(spotQuote.ltp) : null;
  const spotValid = Number.isFinite(spotLtp) && spotLtp > 0 ? spotLtp : null;

  return {
    premium: computePremium(futureLtp, spotValid),
    basis: computeBasis(futureLtp, spotValid),
    futureLtp,
    spotLtp: spotValid,
  };
}

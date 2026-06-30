import { calcPremium } from '../utils/futuresCalculations';

export function computePremium(futureLtp, spotLtp) {
  return calcPremium(futureLtp, spotLtp);
}

export function computeBasis(futureLtp, spotLtp) {
  return calcPremium(futureLtp, spotLtp);
}

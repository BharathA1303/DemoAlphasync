/**
 * Single source of truth for broker card metadata — shared between the
 * onboarding BrokerSelectPage and the in-app BrokersPage so both stay in
 * sync (e.g. flipping a broker from "Coming Soon" to active only needs
 * one edit here).
 */
export const BROKERS = [
  {
    id: "zebull",
    broker: "zebu",
    name: "Zebull (Mynt)",
    logoText: "ZEBULL",
    logoSub: "MYNT",
    logoSrc: "/brokers/zebu.png",
    color: "#00b894",
    active: true,
    authType: "oauth",
    requiresCredentials: true,
  },
  {
    id: "aliceblue",
    broker: "aliceblue",
    name: "Alice Blue",
    logoText: "ALICE",
    logoSub: "BLUE",
    logoSrc: "/brokers/aliceblue.png",
    color: "#3b82f6",
    active: true,
    authType: "oauth",
    requiresCredentials: true,
  },
  {
    id: "zerodha",
    broker: "zerodha",
    name: "Zerodha",
    logoText: "KITE",
    logoSub: "ZERODHA",
    logoSrc: "/brokers/zerodha.png",
    color: "#387ed1",
    active: false,
    authType: "oauth",
    requiresCredentials: true,
  },
  {
    id: "angelone",
    broker: null,
    name: "Angel One",
    logoText: "ANGEL",
    logoSub: "ONE",
    color: "#ff6b35",
    active: false,
  },
  {
    id: "upstox",
    broker: null,
    name: "Upstox",
    logoText: "UPSTOX",
    logoSub: "",
    color: "#7b2ff7",
    active: false,
  },
  {
    id: "groww",
    broker: null,
    name: "Groww",
    logoText: "GROWW",
    logoSub: "",
    color: "#5367ff",
    active: false,
  },
];

export function getBrokerMeta(broker) {
  return BROKERS.find((b) => b.broker === broker) || null;
}

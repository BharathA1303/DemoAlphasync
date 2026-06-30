import { create } from 'zustand';
import { persist } from 'zustand/middleware';

let _orderId = 1;
let _posId   = 1;

export const useOptionsStore = create(
    persist(
        (set, get) => ({
            positions: [],
            orders:    [],

            /**
             * Place a paper options order.
             * orderData: { symbol, strike, type, side, lots, lotSize, premium, orderType, limitPrice }
             */
            placeOptionOrder: (orderData) => {
                const order = {
                    id:         _orderId++,
                    ...orderData,
                    status:     orderData.orderType === 'MARKET' ? 'FILLED' : 'PENDING',
                    timestamp:  new Date().toISOString(),
                };
                set((s) => ({ orders: [order, ...s.orders] }));

                // Auto-fill market orders as positions
                if (order.status === 'FILLED') {
                    get().addPosition(order);
                }
                return order;
            },

            /**
             * Add a filled order as an open position.
             * Merges into existing position if same symbol+strike+type+side.
             */
            addPosition: (order) => {
                set((s) => {
                    const existing = s.positions.find(
                        (p) =>
                            p.symbol  === order.symbol  &&
                            p.strike  === order.strike  &&
                            p.type    === order.type    &&
                            p.side    === order.side    &&
                            p.expiry  === order.expiry
                    );
                    if (existing) {
                        const totalLots    = existing.lots + order.lots;
                        const avgPremium   =
                            (existing.premium * existing.lots + order.premium * order.lots) / totalLots;
                        return {
                            positions: s.positions.map((p) =>
                                p.id === existing.id
                                    ? { ...p, lots: totalLots, premium: avgPremium }
                                    : p
                            ),
                        };
                    }
                    return {
                        positions: [
                            {
                                id:        _posId++,
                                symbol:    order.symbol,
                                strike:    order.strike,
                                type:      order.type,
                                side:      order.side,
                                lots:      order.lots,
                                lotSize:   order.lotSize,
                                premium:   order.premium,
                                expiry:    order.expiry ?? null,
                                openedAt:  new Date().toISOString(),
                            },
                            ...s.positions,
                        ],
                    };
                });
            },

            /** Close (remove) an open position by id. */
            closePosition: (positionId) => {
                set((s) => ({
                    positions: s.positions.filter((p) => p.id !== positionId),
                }));
            },
        }),
        {
            name: 'alphasync-options',
            partialize: (s) => ({ positions: s.positions, orders: s.orders }),
        }
    )
);

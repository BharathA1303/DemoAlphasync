import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import ZebuLiveChart from '../components/trading/ZebuLiveChart';
import { useMarketData } from '../hooks/useMarketData';
import ErrorBoundary from '../components/ErrorBoundary';

export default function ChartEmbed() {
    const [searchParams] = useSearchParams();
    const symbol = searchParams.get('symbol') || 'RELIANCE.NS';
    const [chartPeriod, setChartPeriod] = useState('1D');
    
    const { candles, isLoading, fetchCandles } = useMarketData(symbol);

    useEffect(() => {
        // Fetch daily candles by default
        fetchCandles('1mo', '1d');
    }, [symbol, fetchCandles]);

    return (
        <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#121212' }}>
            <ErrorBoundary fallback={<div style={{color: 'white', padding: '20px'}}>Chart failed to load</div>}>
                <ZebuLiveChart
                    candles={candles}
                    period={chartPeriod}
                    isLoading={isLoading}
                    symbol={symbol}
                    onPeriodChange={setChartPeriod}
                    onPriceUpdate={() => {}}
                />
            </ErrorBoundary>
        </div>
    );
}

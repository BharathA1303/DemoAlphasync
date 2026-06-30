import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useBrokerStore } from '../stores/useBrokerStore';
import toast from 'react-hot-toast';

/**
 * BrokerCallbackPage — handles OAuth redirect from any broker.
 *
 * URL pattern: /broker/callback?broker=<zebu|aliceblue|zerodha>&...params
 *
 * Zebu params:  susertoken, uid, actid, code/auth_code, state
 * Alice Blue:   code, state
 * Zerodha:      request_token, action=login, status=success, state (via state param)
 */
export default function BrokerCallbackPage() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const [status, setStatus] = useState('processing');
    const handleCallback = useBrokerStore((s) => s.handleCallback);

    useEffect(() => {
        // Normalize query string (Alice Blue redirects can append parameters using '?' instead of '&')
        const rawSearch = window.location.search || '';
        const firstQuestionIndex = rawSearch.indexOf('?');
        let normalizedSearch = rawSearch;
        if (firstQuestionIndex !== -1) {
            const beforeFirst = rawSearch.substring(0, firstQuestionIndex + 1);
            const afterFirst = rawSearch.substring(firstQuestionIndex + 1);
            const sanitizedAfter = afterFirst.replace(/\?/g, '&');
            normalizedSearch = beforeFirst + sanitizedAfter;
        }
        const activeParams = new URLSearchParams(normalizedSearch);

        const brokerParam = activeParams.get('broker');
        const storedBroker = (() => {
            try { return localStorage.getItem('broker_oauth_broker'); } catch { return null; }
        })();
        const broker = brokerParam || storedBroker || 'zebu';

        let params;

        if (broker === 'zerodha') {
            // Zerodha sends: request_token=xxx&action=login&status=success
            const requestToken = activeParams.get('request_token') || '';
            // Zerodha doesn't support state param in redirect — recover from localStorage
            const state = localStorage.getItem('zerodha_oauth_state') || activeParams.get('state') || '';
            const action = activeParams.get('action');
            const statusParam = activeParams.get('status');

            if (!requestToken || statusParam !== 'success') {
                setStatus('error');
                toast.error('Zerodha login failed or was cancelled');
                setTimeout(() => navigate('/select-broker'), 2500);
                return;
            }
            params = { requestToken, state };

        } else if (broker === 'aliceblue') {
            const authCode = activeParams.get('authCode') || activeParams.get('auth_code') || activeParams.get('code') || '';
            const userId = activeParams.get('userId') || activeParams.get('user_id') || '';
            const state = activeParams.get('state') || localStorage.getItem('broker_oauth_state') || '';

            if (!authCode || !userId) {
                setStatus('error');
                toast.error('Invalid Alice Blue callback — missing authCode or userId');
                setTimeout(() => navigate('/select-broker'), 2500);
                return;
            }
            params = { authCode, state, brokerUserId: userId };

        } else {
            // Zebu (MYNT OAuth) — redirect is ?code=... (state may not be echoed)
            const susertoken = activeParams.get('susertoken') || '';
            const uid = activeParams.get('uid') || '';
            const actid = activeParams.get('actid') || '';
            const authCode = activeParams.get('code') || activeParams.get('auth_code') || susertoken;
            const state = activeParams.get('state') || localStorage.getItem('broker_oauth_state') || '';

            if (!authCode) {
                setStatus('error');
                toast.error('Invalid Zebu callback — missing authorization code');
                setTimeout(() => navigate('/select-broker'), 2500);
                return;
            }
            params = { authCode, state, susertoken, uid, actid };
        }

        let cancelled = false;

        (async () => {
            try {
                await handleCallback(broker, params);
                if (cancelled) return;
                setStatus('success');
                const brokerLabel = broker === 'aliceblue' ? 'Alice Blue'
                    : broker === 'zerodha' ? 'Zerodha' : 'Zebu';
                toast.success(`${brokerLabel} connected successfully!`);
                localStorage.setItem('alphasync_onboarded', '1');
                localStorage.removeItem('zerodha_oauth_state');
                useBrokerStore.getState().clearOAuthContext();
                setTimeout(() => navigate('/dashboard'), 1200);
            } catch (err) {
                if (cancelled) return;
                setStatus('error');
                toast.error(err.message || 'Broker connection failed');
                setTimeout(() => navigate('/select-broker'), 2500);
            }
        })();

        return () => { cancelled = true; };
    }, [searchParams, handleCallback, navigate]);

    return (
        <div className="min-h-screen flex items-center justify-center bg-surface-950">
            <div className="text-center space-y-4">
                {status === 'processing' && (
                    <>
                        <div className="w-12 h-12 mx-auto border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                        <p className="text-gray-500 text-sm">Connecting your broker account...</p>
                    </>
                )}
                {status === 'success' && (
                    <>
                        <div className="w-12 h-12 mx-auto rounded-full bg-emerald-500/20 flex items-center justify-center">
                            <svg className="w-6 h-6 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                        </div>
                        <p className="text-heading text-sm font-medium">Broker connected!</p>
                        <p className="text-gray-500 text-xs">Redirecting to dashboard...</p>
                    </>
                )}
                {status === 'error' && (
                    <>
                        <div className="w-12 h-12 mx-auto rounded-full bg-red-500/20 flex items-center justify-center">
                            <svg className="w-6 h-6 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </div>
                        <p className="text-heading text-sm font-medium">Connection failed</p>
                        <p className="text-gray-500 text-xs">Redirecting back...</p>
                    </>
                )}
            </div>
        </div>
    );
}

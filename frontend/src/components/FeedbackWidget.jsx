import { useEffect, useRef, useState } from 'react';
import { DotLottieReact } from '@lottiefiles/dotlottie-react';
import { Star, X } from 'lucide-react';
import api from '../services/api';
import { useFeedbackStore } from '../stores/useFeedbackStore';

const SPARKLE_ANGLES = [0, 60, 120, 180, 240, 300];
const STAR_BURST_VECTORS = [
    [0, -1],
    [0.86, -0.5],
    [0.86, 0.5],
    [0, 1],
    [-0.86, 0.5],
    [-0.86, -0.5],
    [1, 0],
    [-1, 0],
    [0.5, -0.86],
    [-0.5, -0.86],
    [0.5, 0.86],
    [-0.5, 0.86],
];
const CONFETTI_COLORS = ['#FBB724', '#06b6d4', '#22c55e', '#f97316', '#ec4899', '#8b5cf6'];

function launchCanvasConfetti() {
    if (typeof window === 'undefined') return Promise.resolve(false);
    const confetti = window.canvasConfetti || window.confetti;
    if (typeof confetti === 'function') {
        confetti({ particleCount: 90, spread: 80, origin: { y: 0.68 }, colors: CONFETTI_COLORS });
        confetti({ particleCount: 45, spread: 110, origin: { y: 0.7 }, scalar: 0.9, colors: CONFETTI_COLORS });
        return Promise.resolve(true);
    }
    return Promise.resolve(false);
}

function buildFallbackConfetti() {
    return Array.from({ length: 12 }, (_, index) => ({
        id: `${Date.now()}-${index}`,
        color: CONFETTI_COLORS[index % CONFETTI_COLORS.length],
        dx: `${(index % 4 - 1.5) * 34}px`,
        dy: `${110 + (index % 3) * 24}px`,
        delay: `${index * 30}ms`,
    }));
}

function FeedbackWidget() {
    const hasSubmitted = useFeedbackStore((state) => state.hasSubmitted);
    const isOpen = useFeedbackStore((state) => state.isOpen);
    const currentRating = useFeedbackStore((state) => state.currentRating);
    const setHasSubmitted = useFeedbackStore((state) => state.setHasSubmitted);
    const setIsOpen = useFeedbackStore((state) => state.setIsOpen);
    const setCurrentRating = useFeedbackStore((state) => state.setCurrentRating);

    const [checked, setChecked] = useState(false);
    const [isVisible, setIsVisible] = useState(false);
    const [phase, setPhase] = useState('idle');
    const [comment, setComment] = useState('');
    const [burstActive, setBurstActive] = useState(false);
    const [celebration, setCelebration] = useState(null);
    const [confettiPieces, setConfettiPieces] = useState([]);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [cardVisible, setCardVisible] = useState(false);
    const timersRef = useRef([]);
    const mountedRef = useRef(true);

    const clearTimers = () => {
        timersRef.current.forEach((timer) => clearTimeout(timer));
        timersRef.current = [];
    };

    const queueTimer = (fn, delay) => {
        const timer = window.setTimeout(fn, delay);
        timersRef.current.push(timer);
        return timer;
    };

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
            clearTimers();
        };
    }, []);

    useEffect(() => {
        if (hasSubmitted) {
            clearTimers();
            return;
        }

        let cancelled = false;
        let shouldInitialize = true;

        async function checkFeedbackStatus() {
            try {
                const response = await api.get('/feedback/check');
                if (response?.data?.has_submitted) {
                    setHasSubmitted(true);
                    shouldInitialize = false;
                    return;
                }
            } catch {
                // Continue with the widget if the check fails.
            } finally {
                if (cancelled || !shouldInitialize) return;
                setChecked(true);
                clearTimers();
                queueTimer(() => {
                    if (!mountedRef.current) return;
                    setIsVisible(true);
                    setPhase('entrance');
                }, 4000);
                queueTimer(() => {
                    if (!mountedRef.current || hasSubmitted) return;
                    setPhase('open');
                    setCardVisible(true);
                    setIsOpen(true);
                }, 5500);
            }
        }

        checkFeedbackStatus();

        return () => {
            cancelled = true;
            clearTimers();
        };
    }, [hasSubmitted, setHasSubmitted, setIsOpen]);

    useEffect(() => {
        if (!burstActive) return undefined;
        const timer = window.setTimeout(() => setBurstActive(false), 650);
        return () => clearTimeout(timer);
    }, [burstActive]);

    const closeWidget = () => {
        if (!cardVisible || isSubmitting) return;
        clearTimers();
        setPhase('closing');
        setIsOpen(false);
        setCelebration(null);
        queueTimer(() => {
            if (!mountedRef.current) return;
            setComment('');
            setCurrentRating(0);
            setPhase('rest');
            setCardVisible(false);
        }, 850);
    };

    const openWidget = () => {
        if (cardVisible || isSubmitting) return;
        setPhase('open');
        setCardVisible(true);
        setIsOpen(true);
    };

    const triggerCelebration = async (rating) => {
        const trimmedComment = comment.trim();
        const payload = {
            rating,
            comment: trimmedComment || null,
        };

        setIsSubmitting(true);
        clearTimers();

        try {
            await api.post('/feedback', payload);
        } catch (error) {
            if (error?.response?.status !== 409) {
                setIsSubmitting(false);
                setIsOpen(true);
                setPhase('open');
                setCelebration({ kind: 'error', message: 'Could not send feedback. Please try again.' });
                return;
            }
        }

        setIsOpen(false);
        setCardVisible(false);
        setPhase('celebrating');
        setBurstActive(true);
        setCelebration(
            rating <= 2
                ? { kind: 'toast', message: "Thank you, we'll improve 🙏" }
                : rating === 3
                    ? { kind: 'toast', message: 'Thanks for the honest feedback!' }
                    : { kind: 'grand', message: 'You made our day! 🎉' }
        );

        if (rating === 3 || rating >= 4) {
            const launched = await launchCanvasConfetti();
            if (!launched) {
                setConfettiPieces(buildFallbackConfetti());
                queueTimer(() => {
                    if (mountedRef.current) setConfettiPieces([]);
                }, 1700);
            }
        }

        queueTimer(() => {
            if (!mountedRef.current) return;
            setHasSubmitted(true);
        }, 2500);
    };

    const handleSubmit = async () => {
        if (!currentRating || isSubmitting) return;
        await triggerCelebration(currentRating);
    };

    const starSize = phase === 'rest' ? 38 : 52;
    const showWidget = checked && isVisible && !hasSubmitted;
    const showCard = cardVisible;
    const showOverlay = cardVisible || phase === 'celebrating';

    if (!showWidget) return null;

    return (
        <div className="fixed inset-0 z-[9999] pointer-events-none font-inherit">
            <style>{`
                @keyframes floatIn {
                    0% { right: -120px; opacity: 0; transform: translateY(0) scale(0.72); }
                    60% { right: 28px; opacity: 1; transform: translateY(-6px) scale(1.05); }
                    100% { right: 20px; opacity: 1; transform: translateY(0) scale(1); }
                }
                @keyframes bobbing {
                    0% { transform: translateY(0px); }
                    100% { transform: translateY(-6px); }
                }
                @keyframes sparkleRadiate {
                    0% { opacity: 1; transform: scale(0.15); }
                    100% { opacity: 0; transform: scale(2.1); }
                }
                @keyframes glowPulse {
                    0%, 100% { box-shadow: 0 0 10px rgba(251,191,36,0.4), 0 0 24px rgba(251,191,36,0.18); }
                    50% { box-shadow: 0 0 16px rgba(251,191,36,0.9), 0 0 34px rgba(251,191,36,0.45); }
                }
                @keyframes cardPop {
                    0% { opacity: 0; transform: scale(0.3); }
                    100% { opacity: 1; transform: scale(1); }
                }
                @keyframes cardShrink {
                    0% { opacity: 1; transform: scale(1); }
                    100% { opacity: 0; transform: scale(0.35); }
                }
                @keyframes sadWobble {
                    0%, 100% { transform: rotate(0deg); }
                    20% { transform: rotate(-10deg); }
                    40% { transform: rotate(10deg); }
                    60% { transform: rotate(-8deg); }
                    80% { transform: rotate(8deg); }
                }
                @keyframes starExplode {
                    0% { opacity: 1; transform: translate(0, 0) scale(1); }
                    100% { opacity: 0; transform: translate(var(--dx), var(--dy)) scale(0.15); }
                }
                @keyframes confettiPiece {
                    0% { opacity: 1; transform: translate(0, 0) rotate(0deg) scale(1); }
                    100% { opacity: 0; transform: translate(var(--dx), var(--dy)) rotate(720deg) scale(0.7); }
                }
                @keyframes toastSlideUp {
                    0% { opacity: 0; transform: translateY(12px) scale(0.95); }
                    100% { opacity: 1; transform: translateY(0) scale(1); }
                }
                @keyframes bounceInSoft {
                    0% { opacity: 0; transform: translateY(18px) scale(0.8); }
                    70% { opacity: 1; transform: translateY(-4px) scale(1.06); }
                    100% { opacity: 1; transform: translateY(0) scale(1); }
                }
                @keyframes textPulse {
                    0%, 100% { transform: scale(1); }
                    50% { transform: scale(1.05); }
                }
            `}</style>

            {showOverlay && (
                <button
                    type="button"
                    aria-label="Close feedback widget"
                    onClick={closeWidget}
                    className="pointer-events-auto fixed inset-0 bg-black/55 backdrop-blur-[2px]"
                    style={{ zIndex: 9998 }}
                />
            )}

            {confettiPieces.map((piece) => (
                <div
                    key={piece.id}
                    className="pointer-events-none fixed left-1/2 top-[58%] rounded-[2px]"
                    style={{
                        zIndex: 10000,
                        width: '8px',
                        height: '14px',
                        background: piece.color,
                        '--dx': piece.dx,
                        '--dy': piece.dy,
                        animation: `confettiPiece 1.5s ease-out ${piece.delay} forwards`,
                        boxShadow: '0 0 12px rgba(255,255,255,0.12)',
                    }}
                />
            ))}

            <div
                className="fixed bottom-[40vh] pointer-events-auto"
                style={{
                    right: '20px',
                    zIndex: 9999,
                    animation: phase === 'entrance' ? 'floatIn 1.1s cubic-bezier(0.34, 1.56, 0.64, 1) forwards' : 'none',
                }}
            >
                <div
                    className="relative"
                    style={{
                        animation: phase !== 'closing' ? 'bobbing 1.8s ease-in-out infinite alternate' : 'none',
                    }}
                >
                    <button
                        type="button"
                        aria-label="Open feedback widget"
                        onClick={openWidget}
                        className="relative flex items-center justify-center rounded-full select-none transition-transform duration-200"
                        style={{
                            width: `${starSize}px`,
                            height: `${starSize}px`,
                            cursor: isOpen ? 'default' : 'pointer',
                        }}
                        disabled={isOpen || isSubmitting}
                    >
                        <div
                            className="absolute inset-0 rounded-full bg-[#FBB724]/10"
                            style={{ animation: 'glowPulse 2.2s ease-in-out infinite' }}
                        />

                        <div
                            className="absolute inset-0 rounded-full"
                            style={{
                                animation: phase === 'closing' ? 'sadWobble 0.9s ease-in-out 3' : 'none',
                            }}
                        >
                            <span
                                className="absolute inset-0 flex items-center justify-center text-[#FBB724]"
                                style={{
                                    fontSize: `${starSize}px`,
                                    filter: 'drop-shadow(0 0 10px rgba(251,191,36,0.7))',
                                    opacity: phase === 'celebrating' ? 0.35 : 1,
                                }}
                            >
                                ⭐
                            </span>

                            {burstActive && STAR_BURST_VECTORS.map(([dx, dy], index) => (
                                <span
                                    key={`${index}-${burstActive}`}
                                    className="absolute left-1/2 top-1/2 rounded-full bg-[#FBB724]"
                                    style={{
                                        width: '6px',
                                        height: '6px',
                                        marginLeft: '-3px',
                                        marginTop: '-3px',
                                        '--dx': `${dx * 30}px`,
                                        '--dy': `${dy * 30}px`,
                                        animation: `starExplode 650ms ease-out ${index * 12}ms forwards`,
                                    }}
                                />
                            ))}

                            {SPARKLE_ANGLES.map((angle, index) => (
                                <span
                                    key={`${angle}-${index}`}
                                    className="absolute left-1/2 top-1/2 rounded-full bg-[#FBB724]"
                                    style={{
                                        width: '6px',
                                        height: '6px',
                                        marginLeft: '-3px',
                                        marginTop: '-3px',
                                        transform: `rotate(${angle}deg) translateX(24px)`,
                                        transformOrigin: 'center center',
                                        animation: `sparkleRadiate 4s ease-out infinite ${index * 400}ms`,
                                        opacity: phase === 'celebrating' ? 0.9 : 0.75,
                                    }}
                                />
                            ))}
                        </div>
                    </button>
                </div>

                {showCard && (
                    <div
                        className="absolute bottom-full right-0 mb-4 w-[320px] max-w-[90vw] origin-bottom-right rounded-[24px] border shadow-2xl overflow-hidden"
                        style={{
                            background: 'var(--bg-base, #0f172a)',
                            borderColor: 'rgba(6, 182, 212, 0.3)',
                            animation: phase === 'closing'
                                ? 'cardShrink 420ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards'
                                : 'cardPop 420ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards',
                            zIndex: 9999,
                        }}
                    >
                        <div className="relative p-5" style={{ color: 'var(--text-primary)' }}>
                            <button
                                type="button"
                                aria-label="Close"
                                onClick={closeWidget}
                                className="absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full text-slate-300 transition-colors hover:bg-white/5 hover:text-white"
                            >
                                <X className="h-4 w-4" />
                            </button>

                            <div className="pr-10">
                                <div className="flex items-center gap-2 text-[18px] font-semibold" style={{ color: 'var(--text-primary)' }}>
                                    <span>How&apos;s your experience?</span>
                                    <span className="inline-block animate-[textPulse_1.2s_ease-in-out_infinite]">👋</span>
                                </div>
                                <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>Your feedback helps us tune AlphaSync.</p>
                            </div>

                            <div className="mt-5 flex items-center gap-2">
                                {[1, 2, 3, 4, 5].map((value) => {
                                    const active = currentRating >= value;
                                    const selected = currentRating === value && burstActive;
                                    return (
                                        <button
                                            key={value}
                                            type="button"
                                            aria-label={`Rate ${value} star${value > 1 ? 's' : ''}`}
                                            onClick={() => {
                                                setCurrentRating(value);
                                                setBurstActive(true);
                                            }}
                                            className="relative flex h-10 w-10 items-center justify-center rounded-full transition-all duration-200 hover:-translate-y-1 hover:scale-110"
                                            style={{ color: active ? '#FBB724' : 'rgba(148, 163, 184, 0.8)' }}
                                        >
                                            <Star
                                                className="h-7 w-7"
                                                fill={active ? 'currentColor' : 'none'}
                                                strokeWidth={1.8}
                                            />
                                            {selected && (
                                                <span
                                                    className="absolute inset-0 rounded-full bg-[#FBB724]/20"
                                                    style={{ animation: 'sparkleRadiate 600ms ease-out forwards' }}
                                                />
                                            )}
                                        </button>
                                    );
                                })}
                            </div>

                            <textarea
                                value={comment}
                                onChange={(event) => setComment(event.target.value)}
                                placeholder="Tell us more... (optional)"
                                rows={4}
                                className="mt-4 w-full resize-none rounded-2xl border px-4 py-3 text-sm outline-none transition-colors"
                                style={{
                                    borderColor: 'var(--border)',
                                    background: 'var(--bg-muted)',
                                    color: 'var(--text-primary)',
                                }}
                            />

                            {celebration?.kind === 'error' && (
                                <div className="mt-3 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                                    {celebration.message}
                                </div>
                            )}

                            <button
                                type="button"
                                onClick={handleSubmit}
                                disabled={!currentRating || isSubmitting}
                                className="mt-4 inline-flex h-11 w-full items-center justify-center rounded-2xl font-semibold text-white transition-transform duration-200 hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-55"
                                style={{ background: 'linear-gradient(135deg, #06b6d4, #0891b2)' }}
                            >
                                {isSubmitting ? 'Sending...' : 'Submit feedback'}
                            </button>
                        </div>
                    </div>
                )}

                {celebration && phase === 'celebrating' && (
                    <div
                        className="absolute bottom-full right-0 mb-4 w-[320px] max-w-[90vw] rounded-[24px] border px-5 py-5 text-white shadow-2xl"
                        style={{
                            background: 'rgba(15, 23, 42, 0.98)',
                            borderColor: 'rgba(6, 182, 212, 0.3)',
                            zIndex: 10001,
                            animation: 'toastSlideUp 420ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards',
                        }}
                    >
                        {celebration.kind === 'grand' ? (
                            <div className="flex flex-col items-center gap-3 text-center">
                                <div className="h-20 w-20 drop-shadow-[0_8px_20px_rgba(251,191,36,0.35)]">
                                    <DotLottieReact
                                        src="/animations/Trophy.lottie"
                                        autoplay
                                        loop
                                        style={{ width: '100%', height: '100%' }}
                                    />
                                </div>
                                <div className="text-2xl font-extrabold tracking-tight" style={{ animation: 'bounceInSoft 600ms cubic-bezier(0.34, 1.56, 0.64, 1) both' }}>
                                    {celebration.message}
                                </div>
                                <p className="text-sm text-slate-300">Thanks for helping us build a better trading experience.</p>
                            </div>
                        ) : (
                            <div className="flex items-center gap-3">
                                <div className="grid h-11 w-11 place-items-center rounded-full bg-cyan-400/10 text-xl">
                                    {celebration.kind === 'toast' && currentRating <= 2 ? '🙏' : '💬'}
                                </div>
                                <div>
                                    <div className="font-semibold text-white">{celebration.message}</div>
                                    <div className="text-xs text-slate-400">We&apos;ve recorded your feedback.</div>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}

export default FeedbackWidget;
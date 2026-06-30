import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
    Bot,
    Check,
    ChevronsLeft,
    ChevronsRight,
    Clipboard,
    Download,
    Loader2,
    MessageSquarePlus,
    Pencil,
    RefreshCw,
    Search,
    Send,
    Sparkles,
    Star,
    Trash2,
    UserRound,
} from 'lucide-react';
import api from '../services/api';
import { useAuthStore } from '../stores/useAuthStore';
import { useTheme } from '../context/ThemeContext';
import { useIsLgUp } from '../responsive/hooks/useMediaQuery';
import { cn } from '../utils/cn';
import toast from 'react-hot-toast';

const makeConversation = (title = 'New chat') => ({
    id: `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [],
});

const WELCOME_MESSAGE = "Hi, I'm Sarah — your AlphaSync mentor. I can help with product navigation, F&O basics, position risk checks, and safe trade steps. Tell me your question or paste your position details.";

const makeMessage = (type, content) => ({
    id: `${type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type,
    content,
    timestamp: Date.now(),
    starred: false,
});

const makeWelcomeMessage = () => ({
    ...makeMessage('ai', WELCOME_MESSAGE),
    id: 'welcome',
});

const makeFreshConversation = () => ({
    ...makeConversation(),
    messages: [makeWelcomeMessage()],
});

function toRecentMessages(messages, nextUserText = '') {
    const items = [...(messages || [])];
    if (nextUserText) {
        items.push({ type: 'user', content: nextUserText, timestamp: Date.now() });
    }

    return items
        .filter((msg) => (msg.type === 'user' || msg.type === 'ai') && String(msg.content || '').trim())
        .slice(-8)
        .map((msg) => ({
            role: msg.type === 'user' ? 'user' : 'assistant',
            content: String(msg.content || '').slice(0, 2000),
            timestamp: msg.timestamp || Date.now(),
        }));
}

function deriveConversationTitle(text) {
    const compact = String(text || '').replace(/\s+/g, ' ').trim();
    if (!compact) return 'New chat';
    return compact.length > 42 ? `${compact.slice(0, 42)}...` : compact;
}

function formatHistoryTime(ts) {
    if (!ts) return '';
    const date = new Date(ts);
    const now = new Date();
    const isSameDay = date.toDateString() === now.toDateString();
    if (isSameDay) return formatTime(ts);
    return date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function formatTime(ts) {
    return new Date(ts).toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
    });
}

function toUiError(err) {
    const raw = String(err || '').toLowerCase();
    if (raw.includes('timeout')) return 'Model is taking too long to respond. Please retry.';
    if (raw.includes('not configured')) return 'AI provider is not configured on the server.';
    return 'Could not get an AI response right now. Please retry.';
}

export default function AIMentorPage() {
    const user = useAuthStore((s) => s.user);
    const { theme } = useTheme();
    const isDark = theme === 'dark';
    const ui = isDark
        ? {
            shell: 'border-white/20 bg-white/8 backdrop-blur-xl shadow-2xl',
            aside: 'border-white/15 bg-[#0b1438]/80',
            rail: 'border-white/10 bg-black/10',
            headerCard: 'bg-gradient-to-br from-cyan-400/20 via-blue-400/15 to-indigo-500/20 border-cyan-200/20',
            panel: 'bg-gradient-to-br from-[#0f1a4f]/80 via-[#152966]/75 to-[#1c2f73]/70',
            panelHeader: 'border-white/15',
            badge: 'border-cyan-200/30 bg-cyan-200/10 text-cyan-50',
            badgeIcon: 'text-cyan-100',
            title: 'text-white',
            subtitle: 'text-cyan-100/80',
            searchWrap: 'border-white/15 bg-white/5 text-cyan-50 placeholder:text-cyan-100/55 focus:outline-none focus:border-cyan-300/45',
            primaryButton: 'border-cyan-300/30 bg-cyan-300/15 text-cyan-50 hover:bg-cyan-300/25',
            conversationActive: 'border-cyan-300/45 bg-cyan-300/18',
            conversationIdle: 'border-white/10 bg-white/5 hover:bg-white/10',
            conversationTitle: 'text-cyan-50',
            conversationPreview: 'text-cyan-100/70',
            conversationTime: 'text-cyan-100/65',
            conversationEditor: 'bg-black/20 border-cyan-200/25 text-cyan-50',
            contentTitle: 'text-white',
            contentSubtle: 'text-cyan-100/80',
            actionButton: 'border-white/20 text-cyan-100 hover:bg-white/10',
            starredButton: 'border-amber-200/55 bg-amber-300/20 text-amber-100',
            emptyStateTitle: 'text-white',
            emptyStateSub: 'text-cyan-100/80',
            emptyStarred: 'border-white/15 bg-white/5 text-cyan-100/85',
            avatarUser: 'bg-cyan-300/20 border-cyan-200/35 text-cyan-50',
            avatarAi: 'bg-blue-300/20 border-blue-200/35 text-blue-100',
            bubbleUser: 'bg-gradient-to-br from-cyan-400 to-blue-500 text-white border-cyan-200/35 rounded-br-md',
            bubbleAi: 'bg-white/12 text-cyan-50 border-white/20 rounded-bl-md',
            bubbleError: 'bg-red-500/20 text-red-100 border-red-300/35 rounded-bl-md',
            meta: 'text-cyan-100/80',
            typing: 'text-cyan-100/85 border-cyan-100/25 bg-cyan-100/10',
            errorBar: 'text-red-100 bg-red-500/15 border-red-300/35',
            composerBar: 'border-white/15 bg-black/10',
            composerWrap: 'border-white/20 bg-white/10',
            composerText: 'text-white placeholder:text-cyan-100/65',
            composerHint: 'text-cyan-100/75',
            sendButton: 'border-cyan-200/40 bg-gradient-to-r from-cyan-400 to-blue-500 text-white',
            quickPrompt: 'border-cyan-100/25 bg-cyan-100/10 text-cyan-50 hover:bg-cyan-100/20',
            whiteText: 'text-white',
            orbTop: 'bg-cyan-400/30',
            orbBottom: 'bg-blue-500/30',
        }
        : {
            shell: 'border-slate-200/80 bg-white/85 backdrop-blur-xl shadow-2xl shadow-slate-200/60',
            aside: 'border-slate-200/80 bg-white/90',
            rail: 'border-slate-200/80 bg-slate-50/90',
            headerCard: 'bg-gradient-to-br from-sky-50 via-cyan-50 to-blue-100 border-sky-200/80',
            panel: 'bg-gradient-to-br from-[#f7fbff] via-[#edf5ff] to-[#e6f0ff]',
            panelHeader: 'border-slate-200/70',
            badge: 'border-sky-200 bg-sky-50 text-sky-700',
            badgeIcon: 'text-sky-500',
            title: 'text-slate-900',
            subtitle: 'text-slate-600',
            searchWrap: 'border-slate-200 bg-white text-slate-700 placeholder:text-slate-400 focus:outline-none focus:border-sky-400',
            primaryButton: 'border-sky-200 bg-sky-50 text-sky-700 hover:bg-sky-100',
            conversationActive: 'border-sky-300 bg-sky-50',
            conversationIdle: 'border-slate-200 bg-white hover:bg-slate-50',
            conversationTitle: 'text-slate-900',
            conversationPreview: 'text-slate-600',
            conversationTime: 'text-slate-500',
            conversationEditor: 'bg-white border-slate-200 text-slate-800',
            contentTitle: 'text-slate-900',
            contentSubtle: 'text-slate-600',
            actionButton: 'border-slate-200 text-slate-700 hover:bg-slate-50',
            starredButton: 'border-amber-200 bg-amber-50 text-amber-700',
            emptyStateTitle: 'text-slate-900',
            emptyStateSub: 'text-slate-600',
            emptyStarred: 'border-slate-200 bg-white text-slate-700',
            avatarUser: 'bg-sky-100 border-sky-200 text-sky-700',
            avatarAi: 'bg-blue-100 border-blue-200 text-blue-700',
            bubbleUser: 'bg-gradient-to-br from-sky-500 to-blue-600 text-white border-sky-200/60 rounded-br-md',
            bubbleAi: 'bg-white text-slate-800 border-slate-200 rounded-bl-md',
            bubbleError: 'bg-rose-50 text-rose-700 border-rose-200 rounded-bl-md',
            meta: 'text-slate-500',
            typing: 'text-sky-700 border-sky-200 bg-sky-50',
            errorBar: 'text-rose-700 bg-rose-50 border-rose-200',
            composerBar: 'border-slate-200 bg-white/90',
            composerWrap: 'border-slate-200 bg-white',
            composerText: 'text-slate-800 placeholder:text-slate-400',
            composerHint: 'text-slate-500',
            sendButton: 'border-sky-200 bg-gradient-to-r from-sky-500 to-blue-600 text-white',
            quickPrompt: 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50',
            whiteText: 'text-slate-900',
            orbTop: 'bg-sky-300/35',
            orbBottom: 'bg-blue-300/35',
        };
    const storageKey = useMemo(() => `mentor-history:${user?.id || 'anon'}`, [user?.id]);
    const historyCollapsedKey = useMemo(() => `mentor-history-collapsed:${user?.id || 'anon'}`, [user?.id]);

    const [conversations, setConversations] = useState([]);
    const [activeConversationId, setActiveConversationId] = useState('');
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [error, setError] = useState('');
    const [editingConversationId, setEditingConversationId] = useState('');
    const isDesktopLayout = useIsLgUp(true);
    const isMobileLayout = !isDesktopLayout;
    const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
    const [editingTitle, setEditingTitle] = useState('');
    const [historyQuery, setHistoryQuery] = useState('');
    const [showStarredOnly, setShowStarredOnly] = useState(false);
    const [historyCollapsed, setHistoryCollapsed] = useState(() => {
        try {
            return localStorage.getItem('mentor-history-collapsed') === '1';
        } catch {
            return false;
        }
    });

    const hasInitialized = useRef('');
    const messageListRef = useRef(null);

    useLayoutEffect(() => {
        window.dispatchEvent(new Event('resize'));
    }, []);

    const activeConversation = useMemo(
        () => conversations.find((conv) => conv.id === activeConversationId) || null,
        [conversations, activeConversationId],
    );

    const messages = useMemo(() => {
        const all = activeConversation?.messages || [];
        if (!showStarredOnly) return all;
        return all.filter((msg) => msg.starred && msg.type === 'ai');
    }, [activeConversation, showStarredOnly]);

    const filteredConversations = useMemo(() => {
        const q = historyQuery.trim().toLowerCase();
        if (!q) return conversations;
        return conversations.filter((conv) => {
            const inTitle = String(conv.title || '').toLowerCase().includes(q);
            const inMessage = conv.messages?.some((msg) => String(msg.content || '').toLowerCase().includes(q));
            return inTitle || inMessage;
        });
    }, [conversations, historyQuery]);

    useEffect(() => {
        if (hasInitialized.current === storageKey) return;
        hasInitialized.current = storageKey;

        try {
            const saved = localStorage.getItem(storageKey);
            const parsed = saved ? JSON.parse(saved) : [];
            const safeParsed = Array.isArray(parsed) ? parsed : [];

            const normalized = safeParsed.map((conv) => {
                const messages = Array.isArray(conv.messages)
                    ? conv.messages.map((msg) => ({ ...msg, starred: Boolean(msg.starred) }))
                    : [];
                return {
                    ...conv,
                    messages: messages.length ? messages : [makeWelcomeMessage()],
                };
            });

            let initialConversations = normalized;
            const firstHasUserMessages = initialConversations[0]?.messages?.some((msg) => msg.type === 'user');
            if (initialConversations.length === 0 || firstHasUserMessages) {
                initialConversations = [makeFreshConversation(), ...initialConversations];
            }

            setConversations(initialConversations);
            setActiveConversationId(initialConversations[0]?.id || '');
        } catch {
            const fresh = makeFreshConversation();
            setConversations([fresh]);
            setActiveConversationId(fresh.id);
        }
    }, [storageKey]);

    useEffect(() => {
        if (!conversations.length) return;
        localStorage.setItem(storageKey, JSON.stringify(conversations));
    }, [conversations, storageKey]);

    useEffect(() => {
        try {
            const saved = localStorage.getItem(historyCollapsedKey);
            setHistoryCollapsed(saved === '1');
        } catch {
            setHistoryCollapsed(false);
        }
    }, [historyCollapsedKey]);

    useEffect(() => {
        try {
            localStorage.setItem(historyCollapsedKey, historyCollapsed ? '1' : '0');
            // Backward-compatible fallback key for users with old sessions.
            localStorage.setItem('mentor-history-collapsed', historyCollapsed ? '1' : '0');
        } catch {
            // ignore storage errors
        }
    }, [historyCollapsed, historyCollapsedKey]);

    useEffect(() => {
        const el = messageListRef.current;
        if (!el) return;

        const raf = window.requestAnimationFrame(() => {
            el.scrollTop = el.scrollHeight;
        });

        return () => window.cancelAnimationFrame(raf);
    }, [activeConversationId, messages.length, sending]);

    const createNewConversation = () => {
        const fresh = makeFreshConversation();
        setConversations((prev) => [fresh, ...prev]);
        setActiveConversationId(fresh.id);
        setInput('');
        setError('');
        setEditingConversationId('');
        setEditingTitle('');
        setShowStarredOnly(false);
    };

    const updateConversation = (conversationId, updater) => {
        setConversations((prev) => prev.map((conv) => (conv.id === conversationId ? updater(conv) : conv)));
    };

    const askMentor = async (messageText, { appendUser = true } = {}) => {
        const text = String(messageText || '').trim();
        if (!text || sending) return;

        let conversationId = activeConversationId;
        let sourceMessages = activeConversation?.messages || [];
        if (!conversationId) {
            const fresh = makeFreshConversation();
            setConversations((prev) => [fresh, ...prev]);
            setActiveConversationId(fresh.id);
            conversationId = fresh.id;
            sourceMessages = fresh.messages;
        }

        setError('');
        if (appendUser) {
            const userMsg = makeMessage('user', text);
            updateConversation(conversationId, (conv) => ({
                ...conv,
                title: conv.title === 'New chat' ? deriveConversationTitle(text) : conv.title,
                updatedAt: Date.now(),
                messages: [...conv.messages, userMsg],
            }));
        }

        setInput('');
        setSending(true);

        try {
            const res = await api.post('/mentor', {
                message: text,
                recent_messages: toRecentMessages(sourceMessages, appendUser ? text : ''),
                client_time: new Date().toISOString(),
                session_id: conversationId,
            });
            const aiMsg = makeMessage('ai', res.data?.reply || 'No response from model.');
            updateConversation(conversationId, (conv) => ({
                ...conv,
                updatedAt: Date.now(),
                messages: [...conv.messages, aiMsg],
            }));
        } catch (e) {
            const msg = toUiError(e?.response?.data?.detail || e?.message);
            setError(msg);
            const errorMsg = makeMessage('error', msg);
            updateConversation(conversationId, (conv) => ({
                ...conv,
                updatedAt: Date.now(),
                messages: [...conv.messages, errorMsg],
            }));
        } finally {
            setSending(false);
        }
    };

    const sendMessage = () => askMentor(input, { appendUser: true });

    const retryLastPrompt = async () => {
        const lastUser = [...(activeConversation?.messages || [])].reverse().find((m) => m.type === 'user');
        if (!lastUser || sending) return;
        await askMentor(lastUser.content, { appendUser: false });
    };

    const clearConversation = () => {
        if (!activeConversationId) return;
        updateConversation(activeConversationId, (conv) => ({
            ...conv,
            title: 'New chat',
            updatedAt: Date.now(),
            messages: [makeWelcomeMessage()],
        }));
        setError('');
        setShowStarredOnly(false);
    };

    const deleteConversation = (conversationId) => {
        setConversations((prev) => {
            const next = prev.filter((conv) => conv.id !== conversationId);
            if (!next.length) {
                const fresh = makeFreshConversation();
                setActiveConversationId(fresh.id);
                return [fresh];
            }
            if (conversationId === activeConversationId) {
                setActiveConversationId(next[0].id);
            }
            return next;
        });
        setError('');
        if (editingConversationId === conversationId) {
            setEditingConversationId('');
            setEditingTitle('');
        }
    };

    const startRenameConversation = (conversation) => {
        setEditingConversationId(conversation.id);
        setEditingTitle(conversation.title || 'New chat');
    };

    const saveRenameConversation = () => {
        const title = editingTitle.trim() || 'New chat';
        if (!editingConversationId) return;

        updateConversation(editingConversationId, (conv) => ({
            ...conv,
            title,
            updatedAt: Date.now(),
        }));

        setEditingConversationId('');
        setEditingTitle('');
    };

    const cancelRenameConversation = () => {
        setEditingConversationId('');
        setEditingTitle('');
    };

    const exportConversation = () => {
        const sourceMessages = activeConversation?.messages || [];
        if (!sourceMessages.length) {
            toast.error('No messages to export');
            return;
        }

        const lines = sourceMessages.map((msg) => {
            const who = msg.type === 'user' ? 'You' : msg.type === 'error' ? 'System' : 'AI Mentor';
            return `[${formatTime(msg.timestamp)}] ${who}: ${msg.content}`;
        });
        const data = [`AlphaSync AI Mentor Chat`, `Date: ${new Date().toLocaleString('en-IN')}`, '', ...lines].join('\n');
        const blob = new Blob([data], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `mentor-chat-${new Date().toISOString().slice(0, 10)}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    };

    const copyMessage = async (content) => {
        try {
            await navigator.clipboard.writeText(content);
            toast.success('Message copied');
        } catch {
            toast.error('Could not copy message');
        }
    };

    const toggleStarMessage = (messageId) => {
        if (!activeConversationId) return;
        updateConversation(activeConversationId, (conv) => ({
            ...conv,
            messages: conv.messages.map((msg) =>
                msg.id === messageId ? { ...msg, starred: !msg.starred } : msg,
            ),
        }));
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        sendMessage();
    };

    const handleComposerKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    const starCount = (activeConversation?.messages || []).filter((msg) => msg.starred && msg.type === 'ai').length;

    const openConversation = (id) => {
        setActiveConversationId(id);
        setError('');
        setShowStarredOnly(false);
        if (isMobileLayout) setMobileHistoryOpen(false);
    };

    const handleNewChat = () => {
        createNewConversation();
        if (isMobileLayout) setMobileHistoryOpen(false);
    };

    const toggleHistoryPanel = () => {
        if (isMobileLayout) {
            setMobileHistoryOpen((prev) => !prev);
            return;
        }
        setHistoryCollapsed((prev) => !prev);
    };

    return (
        <div className={cn(
            'mentor-page responsive-page responsive-page--mentor relative h-full min-h-0 overflow-hidden flex flex-col w-full max-w-full',
            isDesktopLayout && 'mentor-layout--desktop',
            isMobileLayout && 'mentor-layout--mobile',
            isDesktopLayout && historyCollapsed && 'mentor-history-collapsed',
            theme === 'dark'
                ? 'bg-[linear-gradient(120deg,#091036_0%,#121f54_35%,#0f1843_100%)]'
                : 'bg-[linear-gradient(135deg,#dbebff_0%,#ebf5ff_45%,#f8fbff_100%)]'
        )}>
            {!isMobileLayout && (
                <>
                    <div className={cn('pointer-events-none absolute -top-28 left-[28%] h-72 w-72 rounded-full blur-3xl', ui.orbTop)} />
                    <div className={cn('pointer-events-none absolute bottom-[-90px] right-[-80px] h-80 w-80 rounded-full blur-3xl', ui.orbBottom)} />
                </>
            )}

            <section className={cn(
                'relative z-10 flex-1 min-h-0 flex flex-col w-full',
                isMobileLayout ? 'p-0' : 'p-2 md:p-3 lg:p-4',
            )}>
                {isMobileLayout && mobileHistoryOpen && (
                    <button
                        type="button"
                        className="fixed inset-0 z-40 bg-black/50 lg:hidden"
                        aria-label="Close chat history"
                        onClick={() => setMobileHistoryOpen(false)}
                    />
                )}

                <div className={cn(
                    'flex-1 min-h-0 w-full min-w-0 overflow-hidden flex flex-col',
                    isDesktopLayout && 'flex-row rounded-[22px]',
                    ui.shell,
                )}>
                    <aside className={cn(
                        'min-h-0 min-w-0 shrink-0 overflow-hidden flex transition-[width,transform] duration-300',
                        ui.aside,
                        isMobileLayout
                            ? cn(
                                'fixed left-0 top-0 bottom-0 z-50 flex-col w-[min(300px,88vw)] border-r shadow-2xl',
                                mobileHistoryOpen ? 'translate-x-0' : '-translate-x-full pointer-events-none',
                            )
                            : cn(
                                'flex-row items-stretch border-r h-full',
                                historyCollapsed ? 'w-[52px] max-w-[52px]' : 'w-[300px] max-w-[300px]',
                            ),
                    )}>
                        <div className={cn(
                            'flex w-14 shrink-0 flex-col items-center justify-between py-3 border-r border-transparent',
                            ui.rail,
                        )}>
                            <div className="flex flex-col items-center gap-2">
                                <button
                                    type="button"
                                    onClick={toggleHistoryPanel}
                                    className={cn('h-9 w-9 rounded-xl border inline-flex items-center justify-center', ui.actionButton)}
                                    title={historyCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                                >
                                    {historyCollapsed ? <ChevronsRight className="w-4 h-4" /> : <ChevronsLeft className="w-4 h-4" />}
                                </button>
                                <button
                                    onClick={createNewConversation}
                                    disabled={sending}
                                    className={cn('h-9 w-9 rounded-xl border disabled:opacity-50 inline-flex items-center justify-center', ui.primaryButton)}
                                    title="New chat"
                                >
                                    <MessageSquarePlus className="w-4 h-4" />
                                </button>
                                <button
                                    onClick={() => setShowStarredOnly((prev) => !prev)}
                                    className={cn(
                                        'h-9 w-9 rounded-xl border inline-flex items-center justify-center',
                                        showStarredOnly
                                            ? ui.starredButton
                                            : ui.actionButton,
                                    )}
                                    title="Toggle starred"
                                >
                                    <Star className={cn('w-4 h-4', showStarredOnly && 'fill-current')} />
                                </button>
                            </div>

                            <button
                                onClick={clearConversation}
                                className={cn('h-9 w-9 rounded-xl border inline-flex items-center justify-center', ui.actionButton)}
                                title="Clear chat"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        </div>

                        <div className={cn(
                            'min-h-0 min-w-0 flex-1 flex flex-col overflow-hidden transition-all duration-300',
                            historyCollapsed && !isMobileLayout && 'hidden',
                        )}>
                            <div className={cn(
                                'shrink-0 min-w-0 border-b border-transparent overflow-hidden',
                                isMobileLayout ? 'p-3' : 'p-4',
                            )}>
                                {!isMobileLayout && (
                                    <div className={cn('rounded-2xl p-4 border min-w-0', ui.headerCard)}>
                                        <div className="flex items-center gap-3 min-w-0">
                                            <div className="h-11 w-11 rounded-2xl bg-gradient-to-br from-cyan-300 to-blue-500 shadow-lg shadow-cyan-500/25 flex items-center justify-center">
                                                <Bot className="w-5 h-5 text-white" />
                                            </div>
                                            <div>
                                                <p className={cn('text-base font-semibold', ui.whiteText)}>AI MENTOR</p>
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {isMobileLayout && (
                                    <div className="flex items-center justify-between gap-2 mb-3">
                                        <p className={cn('text-sm font-semibold', ui.whiteText)}>Chats</p>
                                        <button
                                            type="button"
                                            onClick={() => setMobileHistoryOpen(false)}
                                            className={cn('h-8 px-2.5 rounded-lg border text-xs', ui.actionButton)}
                                        >
                                            Close
                                        </button>
                                    </div>
                                )}

                                <div className={cn('relative min-w-0', !isMobileLayout && 'mt-3')}>
                                    <Search className={cn('w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none', isDark ? 'text-cyan-100/60' : 'text-slate-400')} />
                                    <input
                                        value={historyQuery}
                                        onChange={(e) => setHistoryQuery(e.target.value)}
                                        placeholder="Search conversation"
                                        className={cn('w-full min-w-0 max-w-full box-border h-9 pl-9 pr-3 rounded-xl border text-xs', ui.searchWrap)}
                                    />
                                </div>

                                <button
                                    onClick={handleNewChat}
                                    disabled={sending}
                                    className={cn('mt-3 w-full max-w-full min-w-0 box-border h-10 rounded-xl border disabled:opacity-50 inline-flex items-center justify-center gap-2 text-sm font-medium', ui.primaryButton)}
                                >
                                    <MessageSquarePlus className="w-4 h-4" /> New chat
                                </button>
                            </div>

                            <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-2.5 space-y-2">
                                {filteredConversations.map((conv) => {
                                    const isActive = conv.id === activeConversationId;

                                    return (
                                        <div
                                            key={conv.id}
                                            className={cn(
                                                'group rounded-xl border px-2.5 py-2 transition-colors',
                                                isActive ? ui.conversationActive : ui.conversationIdle,
                                            )}
                                        >
                                            <button
                                                onClick={() => openConversation(conv.id)}
                                                className="w-full text-left"
                                            >
                                                <div className="flex items-start justify-between gap-2">
                                                    <div className="min-w-0 flex-1">
                                                        {editingConversationId === conv.id ? (
                                                            <input
                                                                autoFocus
                                                                value={editingTitle}
                                                                onChange={(e) => setEditingTitle(e.target.value)}
                                                                onClick={(e) => e.stopPropagation()}
                                                                onKeyDown={(e) => {
                                                                    if (e.key === 'Enter') {
                                                                        e.preventDefault();
                                                                        saveRenameConversation();
                                                                    }
                                                                    if (e.key === 'Escape') {
                                                                        e.preventDefault();
                                                                        cancelRenameConversation();
                                                                    }
                                                                }}
                                                                onBlur={saveRenameConversation}
                                                                className={cn('w-full h-7 px-2 rounded-md border text-xs focus:outline-none', ui.conversationEditor)}
                                                            />
                                                        ) : (
                                                            <p className={cn('text-xs font-semibold truncate', ui.conversationTitle)}>{conv.title || 'New chat'}</p>
                                                        )}
                                                    </div>
                                                    <span className={cn('text-[10px] flex-shrink-0', ui.conversationTime)}>{formatHistoryTime(conv.updatedAt)}</span>
                                                </div>
                                            </button>
                                            <div className="mt-1.5 flex justify-end gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                                {editingConversationId !== conv.id && (
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            startRenameConversation(conv);
                                                        }}
                                                        disabled={sending}
                                                        className={cn('h-6 px-2 rounded-md border text-[10px] disabled:opacity-40 inline-flex items-center gap-1', ui.actionButton)}
                                                    >
                                                        <Pencil className="w-3 h-3" /> Rename
                                                    </button>
                                                )}
                                                <button
                                                    onClick={() => deleteConversation(conv.id)}
                                                    disabled={sending}
                                                    className="h-6 px-2 rounded-md border border-red-300/35 text-[10px] text-red-200 hover:bg-red-400/15 disabled:opacity-40 inline-flex items-center gap-1"
                                                >
                                                    <Trash2 className="w-3 h-3" /> Delete
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}

                                {!filteredConversations.length && (
                                    <div className={cn('rounded-xl border p-3 text-xs', ui.emptyStarred)}>
                                        No conversation matched your search.
                                    </div>
                                )}
                            </div>
                        </div>
                    </aside>

                    <div className={cn('min-h-0 min-w-0 flex-1 flex flex-col overflow-hidden w-full', ui.panel)}>
                        {isMobileLayout && (
                            <div className={cn('shrink-0 flex items-center gap-2 px-3 py-2.5 border-b safe-area-top-pad', ui.panelHeader)}>
                                <button
                                    type="button"
                                    onClick={() => setMobileHistoryOpen(true)}
                                    className={cn('h-10 w-10 shrink-0 rounded-xl border inline-flex items-center justify-center', ui.actionButton)}
                                    aria-label="Open chats"
                                >
                                    <MessageSquarePlus className="w-4 h-4" />
                                </button>
                                <div className="flex-1 min-w-0">
                                    <p className={cn('text-sm font-semibold truncate', ui.contentTitle)}>
                                        {activeConversation?.title || 'AI Mentor'}
                                    </p>
                                    <p className={cn('text-[10px] truncate', ui.contentSubtle)}>
                                        {(activeConversation?.messages || []).length} msgs • {starCount} starred
                                    </p>
                                </div>
                                <button
                                    type="button"
                                    onClick={handleNewChat}
                                    disabled={sending}
                                    className={cn('h-10 px-3 shrink-0 rounded-xl border text-xs font-medium disabled:opacity-50', ui.primaryButton)}
                                >
                                    New
                                </button>
                            </div>
                        )}

                        {isMobileLayout && (
                            <div className={cn('shrink-0 flex items-center gap-2 px-3 py-2 overflow-x-auto border-b', ui.panelHeader)}>
                                <button
                                    type="button"
                                    onClick={() => setShowStarredOnly((prev) => !prev)}
                                    className={cn(
                                        'h-9 px-3 shrink-0 rounded-lg border text-xs inline-flex items-center gap-1.5',
                                        showStarredOnly ? ui.starredButton : ui.actionButton,
                                    )}
                                >
                                    <Star className="w-3.5 h-3.5" /> Starred
                                </button>
                                <button
                                    type="button"
                                    onClick={retryLastPrompt}
                                    disabled={sending}
                                    className={cn('h-9 px-3 shrink-0 rounded-lg border text-xs disabled:opacity-50 inline-flex items-center gap-1.5', ui.actionButton)}
                                >
                                    <RefreshCw className="w-3.5 h-3.5" /> Retry
                                </button>
                                <button
                                    type="button"
                                    onClick={exportConversation}
                                    className={cn('h-9 px-3 shrink-0 rounded-lg border text-xs inline-flex items-center gap-1.5', ui.actionButton)}
                                >
                                    <Download className="w-3.5 h-3.5" /> Export
                                </button>
                            </div>
                        )}

                        {!isMobileLayout && (
                            <div className={cn('shrink-0 px-4 md:px-6 py-4 border-b', ui.panelHeader)}>
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div className="min-w-0">
                                        <div className={cn('inline-flex items-center gap-2 rounded-full border px-2.5 py-1', ui.badge)}>
                                            <Sparkles className={cn('w-3.5 h-3.5', ui.badgeIcon)} />
                                            <span className="text-[11px] font-medium">AI Mentor Studio</span>
                                        </div>
                                        <p className={cn('mt-2 text-lg md:text-xl font-semibold truncate', ui.contentTitle)}>Conversations that feel personal and actionable</p>
                                        <p className={cn('mt-0.5 text-xs truncate', ui.contentSubtle)}>{(activeConversation?.messages || []).length} msgs • {starCount} starred • last update {formatHistoryTime(activeConversation?.updatedAt)}</p>
                                    </div>

                                    <div className="flex flex-wrap items-center gap-1.5">
                                        <button
                                            type="button"
                                            onClick={toggleHistoryPanel}
                                            className={cn('h-8 px-2.5 rounded-lg border text-xs inline-flex items-center gap-1', ui.actionButton)}
                                            title={historyCollapsed ? 'Show chat history' : 'Hide chat history'}
                                        >
                                            {historyCollapsed ? <ChevronsRight className="w-3.5 h-3.5" /> : <ChevronsLeft className="w-3.5 h-3.5" />} Chats
                                        </button>
                                        <button
                                            onClick={() => setShowStarredOnly((prev) => !prev)}
                                            className={cn(
                                                'h-8 px-2.5 rounded-lg border text-xs inline-flex items-center gap-1',
                                                showStarredOnly ? ui.starredButton : ui.actionButton,
                                            )}
                                            title="Toggle starred replies"
                                        >
                                            <Star className="w-3.5 h-3.5" /> Starred
                                        </button>
                                        <button
                                            onClick={retryLastPrompt}
                                            disabled={sending}
                                            className={cn('h-8 px-2.5 rounded-lg border text-xs disabled:opacity-50 inline-flex items-center gap-1', ui.actionButton)}
                                            title="Retry last question"
                                        >
                                            <RefreshCw className="w-3.5 h-3.5" /> Retry
                                        </button>
                                        <button
                                            onClick={exportConversation}
                                            className={cn('h-8 px-2.5 rounded-lg border text-xs inline-flex items-center gap-1', ui.actionButton)}
                                            title="Export chat"
                                        >
                                            <Download className="w-3.5 h-3.5" /> Export
                                        </button>
                                        <button
                                            onClick={clearConversation}
                                            className="h-8 px-2.5 rounded-lg border border-red-300/35 text-xs text-red-200 hover:bg-red-400/15 inline-flex items-center gap-1"
                                            title="Clear this chat"
                                        >
                                            <Trash2 className="w-3.5 h-3.5" /> New
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}

                        <div className="flex-1 min-h-0 flex flex-col">
                            <div ref={messageListRef} className={cn(
                                'flex-1 min-h-0 overflow-y-auto overflow-x-hidden space-y-4',
                                isMobileLayout ? 'px-3 py-3' : 'px-4 md:px-6 py-5',
                            )}>
                                {!messages.length && !sending && !showStarredOnly && (
                                    <div className="h-full flex items-center justify-center py-8">
                                        <div className="text-center max-w-md px-4">
                                            <div className="mx-auto h-14 w-14 rounded-2xl bg-gradient-to-br from-cyan-300 to-blue-500 shadow-lg shadow-cyan-500/35 flex items-center justify-center">
                                                <Bot className="w-7 h-7 text-white" />
                                            </div>
                                            <p className={cn('mt-4 text-base font-semibold', ui.emptyStateTitle)}>Start a new conversation</p>
                                            <p className={cn('mt-1 text-sm', ui.emptyStateSub)}>Ask your own trading question to get started.</p>
                                        </div>
                                    </div>
                                )}

                                {!messages.length && showStarredOnly && (
                                    <div className={cn('rounded-2xl border p-4 text-sm', ui.emptyStarred)}>
                                        No starred mentor replies yet in this conversation.
                                    </div>
                                )}

                                {messages.map((msg) => (
                                    <div key={msg.id} className={cn('flex', msg.type === 'user' ? 'justify-end' : 'justify-start')}>
                                        <div className={cn('group', isMobileLayout ? 'max-w-[92%]' : 'max-w-[94%] md:max-w-[84%] lg:max-w-[74%]')}>
                                            <div className={cn('flex items-end gap-2', msg.type === 'user' && 'flex-row-reverse')}>
                                                <div className={cn(
                                                    'h-8 w-8 rounded-xl border flex items-center justify-center shrink-0',
                                                    msg.type === 'user' ? ui.avatarUser : ui.avatarAi,
                                                )}>
                                                    {msg.type === 'user' ? <UserRound className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                                                </div>

                                                <div className={cn(
                                                    'rounded-2xl px-4 py-3 text-sm shadow-lg border',
                                                    msg.type === 'user' && ui.bubbleUser,
                                                    msg.type === 'ai' && ui.bubbleAi,
                                                    msg.type === 'error' && ui.bubbleError,
                                                )}>
                                                    <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                                                    <div className={cn('mt-1.5 flex items-center justify-end gap-1.5 text-[10px] opacity-80', ui.meta)}>
                                                        <span>{formatTime(msg.timestamp)}</span>
                                                        {msg.type === 'user' && <Check className="w-3 h-3" />}
                                                    </div>
                                                </div>
                                            </div>

                                            {msg.type === 'ai' && msg.content && (
                                                <div className={cn(
                                                    'mt-1.5 ml-10 flex items-center gap-2 transition-opacity',
                                                    isMobileLayout ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
                                                )}>
                                                    <button
                                                        onClick={() => copyMessage(msg.content)}
                                                        className={cn('text-[11px] inline-flex items-center gap-1', isDark ? 'text-cyan-100/85 hover:text-white' : 'text-sky-700 hover:text-sky-900')}
                                                    >
                                                        <Clipboard className="w-3 h-3" /> Copy
                                                    </button>
                                                    <button
                                                        onClick={() => toggleStarMessage(msg.id)}
                                                        className={cn(
                                                            'text-[11px] inline-flex items-center gap-1',
                                                            msg.starred ? (isDark ? 'text-amber-200' : 'text-amber-600') : (isDark ? 'text-cyan-100/85 hover:text-white' : 'text-sky-700 hover:text-sky-900'),
                                                        )}
                                                    >
                                                        <Star className={cn('w-3 h-3', msg.starred && 'fill-current')} />
                                                        {msg.starred ? 'Starred' : 'Star'}
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}

                                {sending && (
                                    <div className={cn('inline-flex items-center gap-2 text-xs rounded-full border px-3 py-1.5 animate-fadeIn', ui.typing)}>
                                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Mentor is typing...
                                    </div>
                                )}
                            </div>

                            {error && <div className={cn('shrink-0 px-4 py-2 text-xs border-t', ui.errorBar)}>{error}</div>}

                            <form onSubmit={handleSubmit} className={cn('shrink-0 px-3 py-2 md:px-4 md:py-2.5 border-t', ui.composerBar)}>
                                <div className={cn('flex items-end gap-2 rounded-xl border px-2.5 py-2', ui.composerWrap)}>
                                    <textarea
                                        value={input}
                                        onChange={(e) => setInput(e.target.value)}
                                        onKeyDown={handleComposerKeyDown}
                                        placeholder={isMobileLayout
                                            ? 'Ask Sarah about AlphaSync, risk, or strategy...'
                                            : 'Ask Sarah anything about AlphaSync, risk, strategy, or market basics...'}
                                        disabled={sending}
                                        rows={1}
                                        maxLength={2000}
                                        className={cn(
                                            'flex-1 min-h-[36px] max-h-24 resize-none bg-transparent border-0 px-1 py-1.5 text-sm leading-snug focus:outline-none focus:ring-0',
                                            ui.composerText,
                                        )}
                                    />
                                    <button
                                        type="submit"
                                        disabled={sending || !input.trim()}
                                        className={cn(
                                            'h-9 shrink-0 px-3 rounded-lg border hover:brightness-110 disabled:opacity-50 inline-flex items-center gap-1.5 text-sm',
                                            ui.sendButton,
                                        )}
                                    >
                                        <Send className="w-4 h-4" /> Send
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
            </section>
        </div>
    );
}

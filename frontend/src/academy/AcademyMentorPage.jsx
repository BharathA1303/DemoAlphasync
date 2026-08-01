// AcademyMentorPage.jsx - AlphaSync Academy full-page AI Mentor chat.
// Distinct from the trading-focused /mentor page ("Sarah") — this is a
// general tutoring assistant backed by routes/academy.py's /mentor endpoint.
// Chat history is kept locally per browser session only (stateless backend),
// same design as the existing AIMentorPage.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
    Bot, Send, Loader2, MessageSquarePlus, Trash2, Sparkles,
    BookOpen, Code2, Calculator, LineChart, Lightbulb, FileQuestion,
    UserRound, Search,
} from 'lucide-react';
import { useAuthStore } from '../stores/useAuthStore';
import { cn } from '../utils/cn';
import academyApi from './api';

const WELCOME_MESSAGE = "Hi! I'm your AI Mentor. Ask me anything about your courses — Python, data analysis, statistics, trading basics, technical analysis, options, or risk management.";

const AI_TOOLS = [
    { icon: Code2, label: 'Explain Code', prompt: 'Can you explain how a for loop works in Python with an example?' },
    { icon: Calculator, label: 'Solve a Problem', prompt: 'Help me calculate the mean and standard deviation of a small dataset.' },
    { icon: LineChart, label: 'Trading Concept', prompt: 'Explain what RSI is and how it is used in technical analysis.' },
    { icon: FileQuestion, label: 'Quiz Me', prompt: 'Ask me 3 practice questions about options Greeks.' },
];

const SUGGESTED_PROMPTS = [
    'What is the difference between a list and a tuple in Python?',
    'Explain moving averages in simple terms.',
    'What are the Greeks in options trading?',
    'How do I calculate risk-reward ratio on a trade?',
];

const KNOWLEDGE_SOURCES = [
    'Python Basics', 'Data Analysis with Pandas', 'Trading Basics',
    'Statistics for Traders', 'Technical Analysis', 'Options Trading Masterclass', 'Risk Management Strategies',
];

const makeMessage = (type, content) => ({
    id: `${type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type,
    content,
    timestamp: Date.now(),
});

const makeWelcomeMessage = () => ({ ...makeMessage('ai', WELCOME_MESSAGE), id: 'welcome' });

const makeConversation = (title = 'New chat') => ({
    id: `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [makeWelcomeMessage()],
});

function toRecentMessages(messages, nextUserText = '') {
    const items = [...(messages || [])];
    if (nextUserText) items.push({ type: 'user', content: nextUserText, timestamp: Date.now() });
    return items
        .filter((m) => (m.type === 'user' || m.type === 'ai') && String(m.content || '').trim())
        .slice(-8)
        .map((m) => ({ role: m.type === 'user' ? 'user' : 'assistant', content: String(m.content || '').slice(0, 2000) }));
}

function deriveTitle(text) {
    const compact = String(text || '').replace(/\s+/g, ' ').trim();
    if (!compact) return 'New chat';
    return compact.length > 40 ? `${compact.slice(0, 40)}...` : compact;
}

function formatTime(ts) {
    return new Date(ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
}

export default function AcademyMentorPage() {
    const user = useAuthStore((s) => s.user);
    const storageKey = useMemo(() => `academy-mentor-history:${user?.id || 'anon'}`, [user?.id]);

    const [conversations, setConversations] = useState([]);
    const [activeId, setActiveId] = useState('');
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const [query, setQuery] = useState('');
    const hasInitialized = useRef('');
    const listRef = useRef(null);

    useLayoutEffect(() => { window.dispatchEvent(new Event('resize')); }, []);

    useEffect(() => {
        if (hasInitialized.current === storageKey) return;
        hasInitialized.current = storageKey;
        try {
            const saved = localStorage.getItem(storageKey);
            const parsed = saved ? JSON.parse(saved) : [];
            const list = Array.isArray(parsed) && parsed.length ? parsed : [makeConversation()];
            setConversations(list);
            setActiveId(list[0].id);
        } catch {
            const fresh = makeConversation();
            setConversations([fresh]);
            setActiveId(fresh.id);
        }
    }, [storageKey]);

    useEffect(() => {
        if (!conversations.length) return;
        localStorage.setItem(storageKey, JSON.stringify(conversations));
    }, [conversations, storageKey]);

    const active = useMemo(() => conversations.find((c) => c.id === activeId) || null, [conversations, activeId]);
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return conversations;
        return conversations.filter((c) => c.title.toLowerCase().includes(q));
    }, [conversations, query]);

    useEffect(() => {
        const el = listRef.current;
        if (!el) return;
        const raf = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
        return () => cancelAnimationFrame(raf);
    }, [activeId, active?.messages?.length, sending]);

    const updateConversation = (id, updater) => {
        setConversations((prev) => prev.map((c) => (c.id === id ? updater(c) : c)));
    };

    const newChat = () => {
        const fresh = makeConversation();
        setConversations((prev) => [fresh, ...prev]);
        setActiveId(fresh.id);
        setInput('');
    };

    const deleteChat = (id) => {
        setConversations((prev) => {
            const next = prev.filter((c) => c.id !== id);
            if (!next.length) {
                const fresh = makeConversation();
                setActiveId(fresh.id);
                return [fresh];
            }
            if (id === activeId) setActiveId(next[0].id);
            return next;
        });
    };

    const send = async (text) => {
        const trimmed = String(text || '').trim();
        if (!trimmed || sending) return;

        let id = activeId;
        let sourceMessages = active?.messages || [];
        if (!id) {
            const fresh = makeConversation();
            setConversations((prev) => [fresh, ...prev]);
            id = fresh.id;
            setActiveId(id);
            sourceMessages = fresh.messages;
        }

        const userMsg = makeMessage('user', trimmed);
        updateConversation(id, (c) => ({
            ...c,
            title: c.title === 'New chat' ? deriveTitle(trimmed) : c.title,
            updatedAt: Date.now(),
            messages: [...c.messages, userMsg],
        }));
        setInput('');
        setSending(true);

        try {
            const res = await academyApi.sendMentorMessage({
                message: trimmed,
                recent_messages: toRecentMessages(sourceMessages),
                client_time: new Date().toISOString(),
                session_id: id,
            });
            const aiMsg = makeMessage('ai', res?.reply || 'No response from model.');
            updateConversation(id, (c) => ({ ...c, updatedAt: Date.now(), messages: [...c.messages, aiMsg] }));
        } catch {
            const errMsg = makeMessage('error', 'Could not get an AI response right now. Please retry.');
            updateConversation(id, (c) => ({ ...c, updatedAt: Date.now(), messages: [...c.messages, errMsg] }));
        } finally {
            setSending(false);
        }
    };

    const messages = active?.messages || [];

    return (
        <div className="h-full min-h-0 flex overflow-hidden">
            {/* History sidebar */}
            <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-edge/5 bg-surface-900/40">
                <div className="p-3 border-b border-edge/5">
                    <button
                        onClick={newChat}
                        className="w-full h-9 rounded-lg border border-edge/10 bg-brand-primary/10 text-brand-primary text-sm font-medium inline-flex items-center justify-center gap-2 hover:bg-brand-primary/20"
                    >
                        <MessageSquarePlus className="h-4 w-4" /> New chat
                    </button>
                    <div className="relative mt-2">
                        <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search chats"
                            className="w-full h-8 pl-8 pr-2 rounded-lg border border-edge/10 bg-surface-950/40 text-xs text-heading placeholder:text-text-muted focus:outline-none"
                        />
                    </div>
                </div>
                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {filtered.map((c) => (
                        <div
                            key={c.id}
                            className={cn(
                                'group flex items-center justify-between gap-1 rounded-lg px-2.5 py-2 text-xs cursor-pointer',
                                c.id === activeId ? 'bg-brand-primary/15 text-heading' : 'text-text-secondary hover:bg-surface-950/50',
                            )}
                            onClick={() => setActiveId(c.id)}
                        >
                            <span className="truncate">{c.title}</span>
                            <button
                                onClick={(e) => { e.stopPropagation(); deleteChat(c.id); }}
                                className="opacity-0 group-hover:opacity-100 text-text-muted hover:text-danger flex-shrink-0"
                            >
                                <Trash2 className="h-3 w-3" />
                            </button>
                        </div>
                    ))}
                </div>
                <div className="p-3 border-t border-edge/5">
                    <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Knowledge Sources</p>
                    <div className="flex flex-wrap gap-1.5">
                        {KNOWLEDGE_SOURCES.map((k) => (
                            <span key={k} className="rounded-full border border-edge/10 bg-surface-950/40 px-2 py-0.5 text-[10px] text-text-secondary">{k}</span>
                        ))}
                    </div>
                </div>
            </aside>

            {/* Main chat panel */}
            <div className="flex-1 min-w-0 flex flex-col">
                <div className="shrink-0 px-4 md:px-6 py-4 border-b border-edge/5 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-cyan-400 to-blue-500 flex items-center justify-center">
                            <Bot className="h-4.5 w-4.5 text-white" />
                        </div>
                        <div>
                            <p className="text-sm font-semibold text-heading">AI Mentor</p>
                            <p className="text-[11px] text-text-secondary">Your personal learning companion</p>
                        </div>
                    </div>
                    <button onClick={newChat} className="lg:hidden h-8 px-3 rounded-lg border border-edge/10 text-xs text-text-secondary">New</button>
                </div>

                {/* AI Tools quick actions */}
                <div className="shrink-0 px-4 md:px-6 py-3 border-b border-edge/5 flex flex-wrap gap-2">
                    {AI_TOOLS.map((tool) => (
                        <button
                            key={tool.label}
                            onClick={() => send(tool.prompt)}
                            disabled={sending}
                            className="flex items-center gap-1.5 rounded-lg border border-edge/10 bg-surface-900/60 px-3 py-1.5 text-xs text-text-secondary hover:text-heading hover:border-brand-primary/30 disabled:opacity-50"
                        >
                            <tool.icon className="h-3.5 w-3.5 text-brand-primary" /> {tool.label}
                        </button>
                    ))}
                </div>

                <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-4 md:px-6 py-5 space-y-4">
                    {messages.map((msg) => (
                        <div key={msg.id} className={cn('flex', msg.type === 'user' ? 'justify-end' : 'justify-start')}>
                            <div className="flex items-end gap-2 max-w-[85%] md:max-w-[70%]">
                                {msg.type !== 'user' && (
                                    <div className="h-7 w-7 rounded-lg bg-brand-primary/15 flex items-center justify-center flex-shrink-0">
                                        <Bot className="h-3.5 w-3.5 text-brand-primary" />
                                    </div>
                                )}
                                <div className={cn(
                                    'rounded-2xl px-4 py-2.5 text-sm shadow-card',
                                    msg.type === 'user' && 'bg-brand-primary text-white rounded-br-md',
                                    msg.type === 'ai' && 'bg-surface-900/80 text-heading border border-edge/10 rounded-bl-md',
                                    msg.type === 'error' && 'bg-danger/10 text-danger border border-danger/20 rounded-bl-md',
                                )}>
                                    <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                                    <span className="mt-1 block text-[10px] opacity-70">{formatTime(msg.timestamp)}</span>
                                </div>
                                {msg.type === 'user' && (
                                    <div className="h-7 w-7 rounded-lg bg-surface-900 flex items-center justify-center flex-shrink-0">
                                        <UserRound className="h-3.5 w-3.5 text-text-secondary" />
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                    {sending && (
                        <div className="inline-flex items-center gap-2 text-xs rounded-full border border-edge/10 bg-surface-900/60 px-3 py-1.5 text-text-secondary">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Mentor is typing...
                        </div>
                    )}
                    {messages.length <= 1 && !sending && (
                        <div className="mt-4">
                            <p className="text-xs text-text-muted mb-2 flex items-center gap-1"><Lightbulb className="h-3.5 w-3.5" /> Suggested prompts</p>
                            <div className="flex flex-wrap gap-2">
                                {SUGGESTED_PROMPTS.map((p) => (
                                    <button
                                        key={p}
                                        onClick={() => send(p)}
                                        className="rounded-full border border-edge/10 bg-surface-900/50 px-3 py-1.5 text-xs text-text-secondary hover:text-heading hover:border-brand-primary/30"
                                    >
                                        {p}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                <form
                    onSubmit={(e) => { e.preventDefault(); send(input); }}
                    className="shrink-0 px-4 md:px-6 py-3 border-t border-edge/5"
                >
                    <div className="flex items-end gap-2 rounded-xl border border-edge/10 bg-surface-900/60 px-3 py-2">
                        <textarea
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); }
                            }}
                            placeholder="Ask your AI Mentor anything about your courses..."
                            disabled={sending}
                            rows={1}
                            maxLength={2000}
                            className="flex-1 min-h-[36px] max-h-24 resize-none bg-transparent border-0 px-1 py-1.5 text-sm text-heading placeholder:text-text-muted focus:outline-none focus:ring-0"
                        />
                        <button
                            type="submit"
                            disabled={sending || !input.trim()}
                            className="h-9 shrink-0 px-3 rounded-lg bg-brand-primary text-white text-sm inline-flex items-center gap-1.5 disabled:opacity-50"
                        >
                            <Send className="h-4 w-4" /> Send
                        </button>
                    </div>
                    <p className="mt-1.5 text-[10px] text-text-muted flex items-center gap-1">
                        <Sparkles className="h-3 w-3" /> AI Mentor can make mistakes. Please verify important information.
                    </p>
                </form>
            </div>
        </div>
    );
}

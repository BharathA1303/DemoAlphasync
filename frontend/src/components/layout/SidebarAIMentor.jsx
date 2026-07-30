import React, { useState, useRef, useEffect } from 'react';
import { Bot, Clipboard, Loader2, MessageSquarePlus, Send, Sparkles, Star, Trash2, UserRound, X } from 'lucide-react';
import api from '../../services/api';
import { cn } from '../../utils/cn';
import toast from 'react-hot-toast';

const QUICK_PROMPTS = [
  'Give me a low-risk intraday checklist.',
  'Explain stop-loss vs trailing stop in simple words.',
  'Help me build a morning market routine.',
];

const WELCOME_MESSAGE = "Hi, I'm Sarah — your AlphaSync mentor. I can help with product navigation, F&O basics, position risk checks, and safe trade steps. Tell me your question or paste your position details.";

const toRecentMessages = (items, nextUserText = '') => {
  const next = [...(items || [])];
  if (nextUserText) next.push({ type: 'user', content: nextUserText, timestamp: Date.now() });
  return next
    .filter((msg) => (msg.type === 'user' || msg.type === 'ai') && String(msg.content || '').trim())
    .slice(-8)
    .map((msg) => ({
      role: msg.type === 'user' ? 'user' : 'assistant',
      content: String(msg.content || '').slice(0, 2000),
      timestamp: msg.timestamp || Date.now(),
    }));
};

const SidebarAIMentor = ({ onClose }) => {
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      type: 'ai',
      content: WELCOME_MESSAGE,
      timestamp: new Date(),
      starred: false,
    }
  ]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [showStarredOnly, setShowStarredOnly] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const toUiError = (value) => {
    if (!value) return 'Something went wrong. Please try again.';
    const msg = String(value).toLowerCase();
    if (msg.includes('not configured')) {
      return 'AI Mentor is currently unavailable. Please try again shortly.';
    }
    return 'Something went wrong. Please try again.';
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 100);
  }, []);

  const handleSendMessage = async (e) => {
    e.preventDefault();
    
    if (!inputValue.trim()) return;
    
    const userMessage = inputValue.trim();
    setInputValue('');
    setError('');
    
    const userMsgId = `user-${Date.now()}`;
    setMessages(prev => [...prev, {
      id: userMsgId,
      type: 'user',
      content: userMessage,
      timestamp: new Date(),
      starred: false,
    }]);
    
    // Show loading state
    setIsLoading(true);
    
    try {
      const response = await api.post('/mentor', {
        message: userMessage,
        recent_messages: toRecentMessages(messages, userMessage),
        client_time: new Date().toISOString(),
        session_id: 'sidebar-mentor',
      });
      
      if (response.data.success) {
        setMessages(prev => [...prev, {
          id: `ai-${Date.now()}`,
          type: 'ai',
          content: response.data.reply,
          timestamp: new Date(),
          starred: false,
        }]);
      } else {
        setError(toUiError(response.data.error));
        setMessages(prev => [...prev, {
          id: `error-${Date.now()}`,
          type: 'error',
          content: response.data.reply || 'Something went wrong. Please try again.',
          timestamp: new Date(),
          starred: false,
        }]);
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail
        ? toUiError(err.response.data.detail)
        : 'Network error. Please try again.';
      setError(errorMsg);
      setMessages(prev => [...prev, {
        id: `error-${Date.now()}`,
        type: 'error',
        content: errorMsg,
        timestamp: new Date(),
        starred: false,
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearChat = () => {
    setMessages([
      {
        id: 'welcome',
        type: 'ai',
        content: WELCOME_MESSAGE,
        timestamp: new Date(),
        starred: false,
      }
    ]);
    setInputValue('');
    setError('');
    setShowStarredOnly(false);
    inputRef.current?.focus();
  };

  const formatTime = (date) => {
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  };

  const filteredMessages = showStarredOnly
    ? messages.filter((msg) => msg.type === 'ai' && msg.starred)
    : messages;

  const starredCount = messages.filter((msg) => msg.type === 'ai' && msg.starred).length;

  const handleInputKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && inputValue.trim()) {
        handleSendMessage(e);
      }
    }
  };

  const copyMessage = async (content) => {
    try {
      await navigator.clipboard.writeText(content);
      toast.success('Message copied');
    } catch {
      toast.error('Could not copy message');
    }
  };

  const toggleStar = (messageId) => {
    setMessages((prev) => prev.map((msg) => (
      msg.id === messageId ? { ...msg, starred: !msg.starred } : msg
    )));
  };

  const startFreshChat = () => {
    handleClearChat();
  };

  return (
    <div className="w-full sm:w-[430px] h-full max-h-screen sm:max-h-[700px] flex flex-col rounded-t-2xl sm:rounded-2xl border border-cyan-200/20 bg-[linear-gradient(140deg,#0a1236_0%,#13285f_45%,#183478_100%)] shadow-2xl overflow-hidden">
      <div className="pointer-events-none absolute right-0 top-0 h-40 w-40 rounded-full bg-cyan-300/20 blur-3xl" />

      <div className="relative flex items-start justify-between gap-3 p-4 border-b border-white/15 bg-black/10 backdrop-blur rounded-t-2xl flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-10 w-10 rounded-2xl bg-gradient-to-br from-cyan-300 to-blue-500 shadow-lg shadow-cyan-500/35 flex items-center justify-center shrink-0">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div className="min-w-0">
            <h3 className="text-white font-semibold text-sm truncate">AI MENTOR</h3>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowStarredOnly((prev) => !prev)}
            className={cn(
              'h-7 px-2 rounded-lg border text-[11px] inline-flex items-center gap-1',
              showStarredOnly
                ? 'border-amber-200/55 bg-amber-300/20 text-amber-100'
                : 'border-white/20 text-cyan-100 hover:bg-white/10'
            )}
            title="Show starred only"
          >
            <Star className="w-3 h-3" /> {starredCount}
          </button>
          <button
            onClick={handleClearChat}
            className="p-1.5 rounded-lg border border-white/20 text-cyan-100 hover:bg-white/10 transition-colors"
            title="Clear chat"
          >
            <Trash2 size={16} />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg border border-white/20 text-cyan-100 hover:bg-white/10 transition-colors"
            title="Close"
          >
            <X size={18} />
          </button>
        </div>
      </div>

      <div className="px-3 pt-2 pb-1 border-b border-white/10 flex flex-wrap gap-1.5">
        {QUICK_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => setInputValue(prompt)}
            className="rounded-full border border-cyan-100/25 bg-cyan-100/10 px-2.5 py-1 text-[10px] text-cyan-50 hover:bg-cyan-100/20"
          >
            {prompt}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 flex">
        <aside className="hidden sm:flex w-14 border-r border-white/10 bg-black/10 flex-col items-center gap-2 py-3">
          <button
            onClick={startFreshChat}
            className="h-9 w-9 rounded-xl border border-cyan-200/35 bg-cyan-200/10 text-cyan-100 hover:bg-cyan-200/20 inline-flex items-center justify-center"
            title="New chat"
          >
            <MessageSquarePlus className="w-4 h-4" />
          </button>
          <button
            onClick={() => setShowStarredOnly((prev) => !prev)}
            className={cn(
              'h-9 w-9 rounded-xl border inline-flex items-center justify-center',
              showStarredOnly
                ? 'border-amber-200/55 bg-amber-300/20 text-amber-100'
                : 'border-white/20 text-cyan-100 hover:bg-white/10'
            )}
            title="Toggle starred"
          >
            <Star className={cn('w-4 h-4', showStarredOnly && 'fill-current')} />
          </button>
          <button
            onClick={handleClearChat}
            className="h-9 w-9 rounded-xl border border-white/20 text-cyan-100 hover:bg-white/10 inline-flex items-center justify-center"
            title="Clear chat"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </aside>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 scroll-smooth">
          {filteredMessages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'flex gap-3 animate-fadeIn',
                msg.type === 'user' ? 'flex-row-reverse' : 'flex-row'
              )}
            >
              <div className={cn(
                'h-8 w-8 rounded-xl border flex items-center justify-center shrink-0',
                msg.type === 'user'
                  ? 'bg-cyan-300/20 border-cyan-200/35 text-cyan-50'
                  : 'bg-blue-300/20 border-blue-200/35 text-blue-100'
              )}>
                {msg.type === 'user' ? <UserRound className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
              </div>

              <div className="group max-w-xs sm:max-w-sm">
                <div
                  className={cn(
                    'p-3 rounded-2xl break-words text-sm leading-relaxed border shadow-lg',
                    msg.type === 'user'
                      ? 'bg-gradient-to-br from-cyan-400 to-blue-500 text-white border-cyan-200/40 rounded-br-md'
                      : msg.type === 'error'
                        ? 'bg-red-500/20 text-red-100 border-red-300/40 rounded-bl-md'
                        : 'bg-white/12 text-cyan-50 border-white/20 rounded-bl-md'
                  )}
                >
                  {msg.content}
                  <span className="block text-[10px] mt-1.5 opacity-80">
                    {formatTime(msg.timestamp)}
                  </span>
                </div>

                {msg.type === 'ai' && (
                  <div className="mt-1 ml-1 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => copyMessage(msg.content)}
                      className="text-[11px] text-cyan-100/85 hover:text-white inline-flex items-center gap-1"
                    >
                      <Clipboard className="w-3 h-3" /> Copy
                    </button>
                    <button
                      onClick={() => toggleStar(msg.id)}
                      className={cn(
                        'text-[11px] inline-flex items-center gap-1',
                        msg.starred ? 'text-amber-200' : 'text-cyan-100/85 hover:text-white'
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

          {isLoading && (
            <div className="inline-flex items-center gap-2 text-xs text-cyan-100/85 rounded-full border border-cyan-100/25 bg-cyan-100/10 px-3 py-1.5 animate-fadeIn">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Sarah is typing...
            </div>
          )}

          {!filteredMessages.length && showStarredOnly && (
            <div className="rounded-xl border border-white/15 bg-white/8 p-3 text-xs text-cyan-100/80">
              No starred replies in this chat yet.
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 bg-red-500/20 border-t border-red-300/40 text-red-100 text-xs">
          {error}
        </div>
      )}

      <form
        onSubmit={handleSendMessage}
        className="flex-shrink-0 p-3 border-t border-white/15 bg-black/15 rounded-b-2xl"
      >
        <div className="rounded-2xl border border-white/20 bg-white/10 p-2">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Ask Sarah about risk, options, or strategy..."
            disabled={isLoading}
            rows={2}
            className={cn(
              'w-full resize-none px-2 py-1.5 rounded-lg bg-transparent border border-transparent',
              'text-sm text-white placeholder:text-cyan-100/65',
              'focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          />

          <div className="mt-1 flex items-center justify-between">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-cyan-100/20 bg-cyan-100/10 px-2 py-1 text-[10px] text-cyan-100/80">
              <Sparkles className="w-3 h-3" /> Enter to send
            </div>

            <button
              type="submit"
              disabled={isLoading || !inputValue.trim()}
              className={cn(
                'h-9 px-3 rounded-xl border border-cyan-200/40 bg-gradient-to-r from-cyan-400 to-blue-500 text-white inline-flex items-center gap-1.5',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
              title="Send message"
            >
              <Send size={15} /> Send
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

export default SidebarAIMentor;

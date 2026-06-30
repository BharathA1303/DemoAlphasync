import React, { useState, useRef, useEffect } from 'react';
import { Bot, ChevronDown, Clipboard, Loader2, Send, Sparkles, Star, Trash2, UserRound } from 'lucide-react';
import api from '../services/api';
import { cn } from '../utils/cn';
import toast from 'react-hot-toast';

const QUICK_PROMPTS = [
  'How do I avoid revenge trading?',
  'Create a basic options learning roadmap.',
  'Give me a risk checklist before entry.',
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

const AIMentor = () => {
  const [isOpen, setIsOpen] = useState(false);
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
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

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
    
    setIsLoading(true);
    
    try {
      const response = await api.post('/mentor', {
        message: userMessage,
        recent_messages: toRecentMessages(messages, userMessage),
        client_time: new Date().toISOString(),
        session_id: 'floating-mentor',
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

  return (
    <div className="fixed bottom-4 right-4 z-50 sm:bottom-6 sm:right-6 font-sans">

      <div
        className={cn(
          'border border-cyan-200/20 rounded-2xl shadow-2xl transition-all duration-300 ease-out overflow-hidden',
          'bg-[linear-gradient(140deg,#0a1236_0%,#13285f_45%,#183478_100%)]',
          isOpen
            ? 'w-[calc(100vw-1.5rem)] sm:w-[420px] h-[80vh] sm:h-[680px] flex flex-col'
            : 'w-14 h-14 cursor-pointer hover:brightness-110'
        )}
      >
        <div
          className={cn(
            'flex items-center justify-between p-3.5 border-b border-white/15 bg-black/10 backdrop-blur rounded-t-2xl',
            !isOpen && 'border-none rounded-2xl h-full'
          )}
          onClick={() => !isOpen && setIsOpen(true)}
        >
          {isOpen ? (
            <>
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="w-9 h-9 bg-gradient-to-br from-cyan-300 to-blue-500 rounded-xl flex items-center justify-center flex-shrink-0 shadow-lg shadow-cyan-500/35">
                  <Bot size={16} className="text-white" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-white font-semibold text-sm">AI MENTOR</h3>
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
                  <Star className="w-3 h-3" />
                </button>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1.5 rounded-lg border border-white/20 hover:bg-white/10 transition-colors text-cyan-100"
                  title="Close"
                >
                  <ChevronDown size={18} className="rotate-180" />
                </button>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center w-full h-full">
              <Bot size={22} className="text-cyan-100" />
            </div>
          )}
        </div>

        {isOpen && (
          <>
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
                        'p-3 rounded-2xl text-sm leading-relaxed border shadow-lg',
                        msg.type === 'user'
                          ? 'bg-gradient-to-br from-cyan-400 to-blue-500 text-white border-cyan-200/40 rounded-br-md'
                          : msg.type === 'error'
                            ? 'bg-red-500/20 text-red-100 border-red-300/40 rounded-bl-md'
                            : 'bg-white/12 text-cyan-50 border-white/20 rounded-bl-md'
                      )}
                    >
                      {msg.content}
                      <span className="block text-[10px] mt-1.5 opacity-80">{formatTime(msg.timestamp)}</span>
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

            <div className="border-t border-white/15 p-3 bg-black/15 rounded-b-2xl space-y-2">
              {messages.length > 1 && (
                <button
                  onClick={handleClearChat}
                  className="w-full text-xs text-cyan-100/85 hover:text-white flex items-center justify-center gap-1 py-1 px-2 rounded-lg hover:bg-white/10 transition-colors"
                  title="Clear conversation"
                >
                  <Trash2 size={14} />
                  Clear Chat
                </button>
              )}

              {error && (
                <div className="text-xs text-red-100 bg-red-500/20 rounded p-2 border border-red-300/40">
                  {error}
                </div>
              )}

              <form onSubmit={handleSendMessage} className="rounded-2xl border border-white/20 bg-white/10 p-2">
                <textarea
                  ref={inputRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleInputKeyDown}
                  placeholder="Ask Sarah anything about trading..."
                  disabled={isLoading}
                  rows={2}
                  className={cn(
                    'w-full resize-none bg-transparent border border-transparent',
                    'px-2 py-1.5 rounded-lg text-sm text-white placeholder:text-cyan-100/65 outline-none transition-colors',
                    'disabled:opacity-50 disabled:cursor-not-allowed'
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
              </form>

              <p className="text-xs text-cyan-100/75 text-center">
                Powered by AlphaSync Mentor AI
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default AIMentor;

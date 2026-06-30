import React from 'react';
import { ShieldCheck, TrendingUp, ArrowUp, ArrowDown, Award, CheckCircle2 } from 'lucide-react';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { cn } from '../../utils/cn';

// Simple WhatsApp logo SVG
function WhatsAppIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946C.06 5.348 5.397.01 12.008.01c3.202.001 6.212 1.246 8.477 3.514 2.266 2.268 3.507 5.28 3.505 8.484-.004 6.657-5.34 11.997-11.953 11.997-2.005-.001-3.973-.502-5.724-1.455L0 24zm6.59-4.846c1.6.95 3.197 1.489 4.85 1.49 5.489 0 9.961-4.412 9.964-9.831.002-2.624-1.018-5.093-2.875-6.953C16.88 1.999 14.43 1.002 12.01 1.002c-5.495 0-9.968 4.414-9.972 9.835-.001 1.776.475 3.51 1.378 5.042l-.999 3.648 3.73-.979zm11.215-7.638c-.3-.149-1.77-.864-2.046-.963-.274-.1-.474-.15-.674.15-.2.3-.77.962-.946 1.16-.174.2-.35.225-.65.075-.3-.15-1.263-.46-2.407-1.472-.89-.785-1.49-1.756-1.666-2.053-.176-.3-.02-.462.13-.611.135-.134.3-.349.45-.523.15-.174.2-.3.3-.498.1-.2.05-.374-.025-.524-.075-.15-.675-1.609-.925-2.204-.243-.584-.49-.504-.674-.514-.174-.01-.374-.01-.574-.01s-.524.075-.798.374c-.275.3-1.05 1.017-1.05 2.482s1.07 2.872 1.219 3.071c.149.199 2.105 3.178 5.099 4.453.712.303 1.27.484 1.703.62.716.226 1.368.194 1.882.118.573-.085 1.77-.714 2.02-1.403.25-.688.25-1.278.175-1.403-.075-.124-.275-.199-.575-.349z"/>
    </svg>
  );
}

function UserAvatar({ entry, rank }) {
  const avatarUrl = entry?.avatar_url;
  const displayName = entry?.full_name || entry?.username || '';
  const initials = displayName
    ? displayName
        .split(' ')
        .map((n) => n[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : '?';

  if (avatarUrl) {
    return (
      <div className="relative">
        <img
          src={avatarUrl}
          alt={displayName}
          className="w-14 h-14 rounded-full object-cover ring-2 ring-white shadow-md"
        />
        {rank === 1 && (
          <svg className="w-6 h-6 absolute -top-3.5 left-1/2 -translate-x-1/2 text-amber-400 drop-shadow-[0_1.5px_3px_rgba(0,0,0,0.15)]" viewBox="0 0 24 24" fill="currentColor">
            <path d="M5 16h14a1 1 0 00.9-.55l3-6a1 1 0 00-1.42-1.3l-3.23 2.42-3.8-5.7a1 1 0 00-1.7 0l-3.8 5.7L5.75 8.15a1 1 0 00-1.42 1.3l3 6A1 1 0 005 16z" />
          </svg>
        )}
      </div>
    );
  }

  const colors = [
    'bg-emerald-50 text-emerald-500 border border-emerald-100',
    'bg-blue-50 text-blue-500 border border-blue-100',
    'bg-purple-50 text-purple-500 border border-purple-100',
    'bg-amber-50 text-amber-500 border border-amber-100',
    'bg-rose-50 text-rose-500 border border-rose-100',
  ];
  const charCodeSum = displayName.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const colorClass = colors[charCodeSum % colors.length];

  return (
    <div className="relative">
      <div
        className={cn(
          "w-14 h-14 rounded-full flex items-center justify-center font-display font-extrabold text-base ring-2 ring-white shadow-md",
          colorClass
        )}
      >
        {initials}
      </div>
      {rank === 1 && (
        <svg className="w-6 h-6 absolute -top-3.5 left-1/2 -translate-x-1/2 text-amber-400 drop-shadow-[0_1.5px_3px_rgba(0,0,0,0.15)]" viewBox="0 0 24 24" fill="currentColor">
          <path d="M5 16h14a1 1 0 00.9-.55l3-6a1 1 0 00-1.42-1.3l-3.23 2.42-3.8-5.7a1 1 0 00-1.7 0l-3.8 5.7L5.75 8.15a1 1 0 00-1.42 1.3l3 6A1 1 0 005 16z" />
        </svg>
      )}
    </div>
  );
}

export default function TraderCard({ entry, displayName, displayHandle }) {
  if (!entry) return null;

  const rank = entry.rank;
  const isPositive = (entry.pnl ?? 0) >= 0;
  const isZero = (entry.pnl ?? 0) === 0;

  // Rank badge styling (Top-left)
  let rankBadgeClass = "bg-gray-100 text-gray-500 border border-gray-200/60";
  if (rank === 1) rankBadgeClass = "bg-gradient-to-br from-[#FBBF24] to-[#F59E0B] text-white border-none shadow-[0_4px_12px_rgba(245,158,11,0.2)] font-black";
  else if (rank === 2) rankBadgeClass = "bg-slate-200 text-slate-700 border-none font-bold";
  else if (rank === 3) rankBadgeClass = "bg-amber-100 text-amber-800 border-none font-bold";

  // Status Badge (Top-right)
  let statusBadge = null;
  
  if (entry.status) {
    statusBadge = (
      <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50/80 px-2.5 py-0.5 rounded-full border border-emerald-100/50 flex items-center gap-1 shadow-sm">
        {entry.status}
      </span>
    );
  } else if (rank === 1) {
    statusBadge = (
      <span className="text-[10px] font-bold text-amber-600 bg-amber-50/90 px-2.5 py-0.5 rounded-full border border-amber-100/50 flex items-center gap-1 shadow-sm">
        <Award className="w-3 h-3 text-amber-500 fill-amber-500/20" />
        Champion
      </span>
    );
  } else if (rank > 1 && rank <= 5) {
    statusBadge = (
      <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50/80 px-2.5 py-0.5 rounded-full border border-emerald-100/50 flex items-center gap-1 shadow-sm">
        <TrendingUp className="w-3 h-3 text-emerald-500" />
        Top Trader
      </span>
    );
  } else {
    statusBadge = (
      <span className="text-[10px] font-bold text-blue-600 bg-blue-50/80 px-2.5 py-0.5 rounded-full border border-blue-100/50 flex items-center gap-1 shadow-sm">
        <CheckCircle2 className="w-3 h-3 text-blue-500 fill-blue-500/10" />
        Verified
      </span>
    );
  }

  return (
    <div
      className={cn(
        "relative rounded-[24px] p-5 flex flex-col items-center justify-center text-center h-[260px] select-none transition-all duration-200 ease-in-out hover:-translate-y-[6px] hover:scale-[1.02]",
        "bg-white/85 backdrop-blur-[16px] border border-white/50 shadow-[0_10px_40px_rgba(15,23,42,0.06)] hover:shadow-[0_20px_45px_rgba(15,23,42,0.08)]",
        rank === 1 && "border-emerald-400/60 shadow-[0_12px_44px_rgba(16,185,129,0.08)]"
      )}
    >
      {/* Top row */}
      <div className="absolute top-4 left-4 right-4 flex items-center justify-between w-[calc(100%-2rem)]">
        {/* Rank Badge */}
        <div className={cn("w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold font-display", rankBadgeClass)}>
          {rank}
        </div>

        {/* Top-Right Status Badge */}
        {statusBadge}
      </div>

      {/* Centered Avatar */}
      <div className="mt-3 mb-2 flex items-center justify-center">
        <UserAvatar entry={entry} rank={rank} />
      </div>

      {/* Name and Handle */}
      <div className="space-y-0.5 max-w-full">
        <h4 className="font-display font-bold text-base text-gray-800 truncate px-2 leading-snug">
          {displayName(entry)}
        </h4>
        <p className="text-[11px] font-medium text-gray-400 truncate">
          {displayHandle(entry)}
        </p>
      </div>

      {/* P&L */}
      <div className="mt-4 w-full">
        <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400 block mb-0.5">
          P&L
        </span>
        <div
          className={cn(
            "font-price font-extrabold text-base tracking-tight tabular-nums leading-none",
            isZero ? "text-gray-500" : isPositive ? "text-[#10B981]" : "text-[#EF4444]"
          )}
        >
          {isZero ? '' : isPositive ? '+' : ''}
          {formatCurrency(entry.pnl ?? 0)}
        </div>
      </div>

      {/* Percentage Pill */}
      <div className="mt-2.5">
        <span
          className={cn(
            "inline-flex items-center gap-0.5 px-2.5 py-0.5 rounded-full text-[10px] font-bold shadow-sm",
            isZero 
              ? "bg-gray-50 text-gray-400 border border-gray-100"
              : isPositive
                ? "bg-emerald-50/80 text-emerald-600 border border-emerald-100"
                : "bg-red-50/80 text-red-600 border border-red-100"
          )}
        >
          {isZero ? (
            <span className="w-1.5 h-1.5 bg-gray-400 rounded-sm inline-block mr-0.5"></span>
          ) : isPositive ? (
            <ArrowUp className="w-2.5 h-2.5 text-emerald-500 fill-emerald-500 stroke-[3]" />
          ) : (
            <ArrowDown className="w-2.5 h-2.5 text-red-500 fill-red-500 stroke-[3]" />
          )}
          {formatPercent(entry.pnl_percent ?? 0, 2, false)}
        </span>
      </div>
    </div>
  );
}

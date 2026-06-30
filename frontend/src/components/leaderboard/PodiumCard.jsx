import React from 'react';
import { motion } from 'framer-motion';
import { Crown, ArrowUp, ArrowDown } from 'lucide-react';
import { formatCurrency, formatPercent } from '../../utils/formatters';
import { cn } from '../../utils/cn';

// Laurels flanking the avatar (flaps left or right)
function LaurelBranch({ rank, isRight }) {
  let color, glowStyle, sizeClass;
  if (rank === 1) {
    color = "text-emerald-500/90";
    sizeClass = "w-12 h-28"; // ~110px height
    glowStyle = { filter: 'drop-shadow(0 0 20px rgba(16,185,129,.35))' };
  } else if (rank === 2) {
    color = "text-slate-400/80";
    sizeClass = "w-10 h-22"; // ~80px height
    glowStyle = { filter: 'drop-shadow(0 0 10px rgba(148,163,184,.20))' };
  } else {
    color = "text-amber-700/80"; // Bronze styling
    sizeClass = "w-10 h-22"; // ~80px height
    glowStyle = { filter: 'drop-shadow(0 0 10px rgba(217,119,6,.15))' };
  }

  // Centering managed completely by CSS, float drift managed by Framer Motion.
  // This prevents transform properties from overwriting each other.
  const positionClass = isRight 
    ? "absolute top-1/2 left-full ml-3 -translate-y-1/2 z-10" 
    : "absolute top-1/2 right-full mr-3 -translate-y-1/2 z-10";

  return (
    <div className={cn("select-none pointer-events-none", positionClass)}>
      <motion.div
        animate={{ y: [-4, 4, -4] }}
        transition={{
          duration: 4,
          repeat: Infinity,
          ease: "easeInOut",
          delay: isRight ? 0.6 : 0
        }}
        style={glowStyle}
      >
        <svg className={cn(sizeClass, color, isRight && "scale-x-[-1]")} viewBox="0 0 80 120" fill="currentColor">
          {/* Branch stem */}
          <path d="M70,110 C50,100 40,80 40,55 C40,30 50,15 65,5" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          {/* Leaf pairs */}
          <path d="M42,90 C25,88 15,80 20,70 C30,72 38,82 42,90 Z" />
          <path d="M40,70 C20,66 12,56 18,48 C28,48 36,60 40,70 Z" />
          <path d="M42,50 C24,44 18,32 25,24 C34,26 40,40 42,50 Z" />
          <path d="M48,30 C34,22 30,10 38,4 C45,8 48,22 48,30 Z" />
          <path d="M58,15 C48,7 48,0 54,-4 C58,-2 58,10 58,15 Z" />
        </svg>
      </motion.div>
    </div>
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

  // Champion card avatar size = w-32 h-32; others = w-24 h-24
  const sizeClass = rank === 1 ? 'w-32 h-32 text-3xl' : 'w-24 h-24 text-2xl';

  const avatarGlow = rank === 1 ? {
    boxShadow: '0 0 40px rgba(16,185,129,0.35)',
    border: '4px solid #10B981',
  } : {
    border: '2px solid rgba(255,255,255,0.8)',
    boxShadow: '0 8px 24px rgba(0,0,0,0.08)'
  };

  const crownSvg = (
    <svg className="w-10 h-10 absolute -top-8 left-1/2 -translate-x-1/2 text-[#FBBF24] drop-shadow-[0_4px_8px_rgba(245,158,11,0.45)]" viewBox="0 0 24 24" fill="currentColor">
      <path d="M5 16h14a1 1 0 00.9-.55l3-6a1 1 0 00-1.42-1.3l-3.23 2.42-3.8-5.7a1 1 0 00-1.7 0l-3.8 5.7L5.75 8.15a1 1 0 00-1.42 1.3l3 6A1 1 0 005 16z" />
    </svg>
  );

  if (avatarUrl) {
    return (
      <div className="relative">
        <motion.div
          animate={rank === 1 ? {
            boxShadow: [
              '0 0 24px rgba(16,185,129,0.2)',
              '0 0 44px rgba(16,185,129,0.5)',
              '0 0 24px rgba(16,185,129,0.2)'
            ],
            borderColor: ['#10B981', '#34d399', '#10B981']
          } : {}}
          transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
          style={avatarGlow}
          className="rounded-full overflow-hidden"
        >
          <img
            src={avatarUrl}
            alt={displayName}
            className={cn("object-cover", sizeClass)}
          />
        </motion.div>
        {rank === 1 && crownSvg}
      </div>
    );
  }

  // Fallback colors
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
      <motion.div
        animate={rank === 1 ? {
          boxShadow: [
            '0 0 24px rgba(16,185,129,0.2)',
            '0 0 44px rgba(16,185,129,0.5)',
            '0 0 24px rgba(16,185,129,0.2)'
          ],
          borderColor: ['#10B981', '#34d399', '#10B981']
        } : {}}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
        style={avatarGlow}
        className={cn(
          "rounded-full flex items-center justify-center font-display font-black",
          colorClass,
          sizeClass
        )}
      >
        {initials}
      </motion.div>
      {rank === 1 && crownSvg}
    </div>
  );
}

export function PodiumBase({ rank }) {
  let topGradient, frontGradient, glowColor, num;

  if (rank === 1) {
    topGradient = "from-[#059669] via-[#10B981] to-[#059669]"; // Premium emerald metallic
    frontGradient = "from-[#047857] via-[#065f46] to-[#064e3b]";
    glowColor = "rgba(16,185,129,0.35)";
    num = "1";
  } else if (rank === 2) {
    topGradient = "from-[#64748b] via-[#94a3b8] to-[#64748b]"; // Premium slate metallic
    frontGradient = "from-[#475569] via-[#334155] to-[#1e293b]";
    glowColor = "rgba(148,163,184,0.25)";
    num = "2";
  } else {
    topGradient = "from-[#b45309] via-[#d97706] to-[#b45309]"; // Premium bronze metallic
    frontGradient = "from-[#92400e] via-[#78350f] to-[#451a03]";
    glowColor = "rgba(217,119,6,0.25)";
    num = "3";
  }

  return (
    <div className="relative w-full flex flex-col items-center mt-[-10px] z-10 select-none">
      {/* 3D Platform container */}
      <div className="relative w-full h-[80px]">
        {/* Shadow Layer */}
        <div 
          className="absolute -bottom-6 left-[5%] right-[5%] h-12 bg-black/45 blur-[16px] rounded-full z-0 pointer-events-none shadow-[0_30px_80px_rgba(0,0,0,0.15)]"
          style={{ transform: 'scale(1.08)' }}
        />
        
        {/* Reflection / Glow Layer */}
        <div 
          className="absolute -bottom-8 left-1/4 right-1/4 h-8 blur-[24px] z-0 rounded-full opacity-30 animate-pulse-subtle"
          style={{ backgroundColor: glowColor }}
        />

        {/* Tilted top surface */}
        <div 
          className={cn(
            "absolute top-0 left-0 right-0 h-12 rounded-[50%] bg-gradient-to-r border-t border-white/40 shadow-[inset_0_2px_4px_rgba(255,255,255,0.3)] z-10",
            topGradient
          )}
          style={{ transform: 'perspective(1200px) rotateX(20deg)' }}
        />

        {/* Front Face */}
        <div 
          className={cn(
            "absolute top-5 left-0 right-0 h-14 bg-gradient-to-b rounded-b-[50%_16px] shadow-[0_12px_24px_rgba(0,0,0,0.25)] flex items-center justify-center z-0 border-b border-black/40 overflow-hidden",
            frontGradient
          )}
        >
          {/* Stage Shine Reflection Layer */}
          <div className="absolute inset-0 bg-gradient-to-tr from-white/0 via-white/5 to-white/10 opacity-20 filter blur-[8px]" />

          {/* Badge on front face */}
          <div 
            className="w-10 h-10 rounded-full bg-gradient-to-br flex items-center justify-center font-display font-black text-xl border-2 border-white/80 shadow-[0_8px_20px_rgba(0,0,0,0.3)] mt-2 z-10"
            style={{
              background: rank === 1 ? 'linear-gradient(135deg, #FBBF24, #F59E0B)' : rank === 2 ? 'linear-gradient(135deg, #cbd5e1, #64748b)' : 'linear-gradient(135deg, #f59e0b, #92400e)',
              boxShadow: rank === 1 ? '0 8px 20px rgba(245,158,11,0.45)' : rank === 2 ? '0 8px 20px rgba(148,163,184,0.35)' : '0 8px 20px rgba(217,119,6,0.35)',
              color: '#fff'
            }}
          >
            {num}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PodiumCard({ entry, rank, displayName, displayHandle }) {
  if (!entry) return null;

  const isRank1 = rank === 1;
  const isPositive = (entry.pnl ?? 0) >= 0;

  // Background, dimensions, and typography settings
  let cardClass, badgeGradient, badgeShadow, badgeContent, phaseOffset;
  
  if (rank === 1) {
    cardClass = "bg-white/85 backdrop-blur-[16px] border border-white/50 shadow-[0_20px_50px_rgba(16,185,129,0.12)] w-full md:w-[520px] md:h-[480px] min-h-[480px] py-8";
    badgeGradient = "from-[#FBBF24] to-[#F59E0B]";
    badgeShadow = "shadow-[0_12px_30px_rgba(245,158,11,0.35)]";
    badgeContent = <Crown className="w-7 h-7 text-white" fill="currentColor" />;
    phaseOffset = 0;
  } else if (rank === 2) {
    cardClass = "bg-white/85 backdrop-blur-[16px] border border-white/50 shadow-[0_16px_36px_rgba(148,163,184,0.08)] w-full md:w-[340px] md:h-[390px] min-h-[390px] py-6";
    badgeGradient = "from-slate-300 to-slate-500";
    badgeShadow = "shadow-[0_12px_30px_rgba(148,163,184,0.35)]";
    badgeContent = <span className="font-display font-extrabold text-lg text-white">2</span>;
    phaseOffset = 1.3;
  } else {
    cardClass = "bg-white/85 backdrop-blur-[16px] border border-white/50 shadow-[0_16px_36px_rgba(217,119,6,0.08)] w-full md:w-[340px] md:h-[390px] min-h-[390px] py-6";
    badgeGradient = "from-amber-500 to-[#D97706]";
    badgeShadow = "shadow-[0_12px_30px_rgba(217,119,6,0.35)]";
    badgeContent = <span className="font-display font-extrabold text-lg text-white">3</span>;
    phaseOffset = 2.6;
  }

  return (
    <div className="flex flex-col items-center flex-shrink-0 w-full sm:w-auto overflow-visible select-none">
      {/* Animated Card Shell */}
      <motion.div
        animate={{ translateY: [0, -8, 0] }}
        transition={{
          duration: 4,
          repeat: Infinity,
          ease: "easeInOut",
          delay: phaseOffset
        }}
        className={cn(
          "relative rounded-[32px] px-8 flex flex-col items-center justify-center text-center z-20",
          cardClass
        )}
      >
        {/* Floating Crown/Rank Badge centered horizontally above the card.
            Absolute horizontal centering managed by parent wrapper; floating translation managed by child motion.div.
            This avoids transform conflicts with -translate-x-1/2. */}
        <div className="absolute -top-7 left-1/2 -translate-x-1/2 z-30 select-none pointer-events-none">
          <motion.div
            animate={{ y: [-4, 4, -4] }}
            transition={{
              duration: 3,
              repeat: Infinity,
              ease: "easeInOut",
              delay: phaseOffset
            }}
            className={cn(
              "rounded-full bg-gradient-to-br flex items-center justify-center border-2 border-white/90 shadow-md",
              badgeGradient,
              badgeShadow,
              isRank1 ? "w-14 h-14" : "w-12 h-12"
            )}
          >
            {badgeContent}
          </motion.div>
        </div>

        {/* Profile Avatar section */}
        <div className="relative mt-4 mb-3 flex items-center justify-center">
          {/* Laurels left and right */}
          <LaurelBranch rank={rank} isRight={false} />
          <LaurelBranch rank={rank} isRight={true} />
          
          <UserAvatar entry={entry} rank={rank} />
        </div>

        {/* Username Details */}
        <div className="space-y-0.5 max-w-full">
          <h3 className={cn("font-display font-bold text-gray-800 truncate px-2", isRank1 ? "text-2xl" : "text-lg")}>
            {displayName(entry)}
          </h3>
          <p className="text-xs font-semibold text-emerald-500/80 bg-emerald-50/50 px-2.5 py-0.5 rounded-full inline-block">
            {displayHandle(entry)}
          </p>
        </div>

        {/* P&L Section */}
        <div className="mt-3 w-full">
          <span className="text-[11px] font-bold uppercase tracking-wider text-gray-400 block mb-0.5">
            P&L
          </span>
          <div
            className={cn(
              "font-price font-extrabold tracking-tight tabular-nums leading-none",
              isPositive ? "text-[#10B981]" : "text-[#EF4444]"
            )}
            style={{
              fontSize: isRank1 ? '48px' : '28px',
              fontWeight: 800
            }}
          >
            {isPositive ? '+' : ''}
            {formatCurrency(entry.pnl ?? 0)}
          </div>
        </div>

        {/* Percentage Badge */}
        <div className="mt-2.5">
          <span
            className={cn(
              "inline-flex items-center gap-1 px-3.5 py-1 rounded-full text-xs font-bold shadow-sm",
              isPositive
                ? "bg-emerald-50 text-emerald-600 border border-emerald-100"
                : "bg-red-50 text-red-600 border border-red-100"
            )}
          >
            {isPositive ? (
              <ArrowUp className="w-3.5 h-3.5 text-emerald-500 fill-emerald-500 stroke-[3]" />
            ) : (
              <ArrowDown className="w-3.5 h-3.5 text-red-500 fill-red-500 stroke-[3]" />
            )}
            {formatPercent(entry.pnl_percent ?? 0, 2, false)}
          </span>
        </div>
      </motion.div>

      {/* 3D Base Platform */}
      <PodiumBase rank={rank} />
    </div>
  );
}

import React from 'react';
import PodiumCard from './PodiumCard';

function ConfettiSystem() {
  // Generate 24 slow-drifting premium particles
  const particles = Array.from({ length: 24 }).map((_, i) => {
    const left = `${Math.random() * 80 + 10}%`;
    const bottom = `${Math.random() * 60 + 10}%`;
    const size = `${Math.random() * 10 + 8}px`; // 8px to 18px
    const duration = `${Math.random() * 20 + 20}s`; // very slow: 20s to 40s
    const delay = `${Math.random() * -20}s`;
    
    // Shapes
    const shapes = ['circle', 'square', 'diamond', 'triangle'];
    const shape = shapes[i % shapes.length];

    // Colors: elegant slate, gold, emerald, white, transparent with low opacity (0.15)
    const colors = [
      'rgba(16, 185, 129, 0.15)', // emerald
      'rgba(245, 158, 11, 0.15)', // gold
      'rgba(148, 163, 184, 0.15)', // slate
      'rgba(255, 255, 255, 0.15)', // white
    ];
    const color = colors[i % colors.length];

    return {
      id: i,
      left,
      bottom,
      size,
      duration,
      delay,
      color,
      shape,
    };
  });

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none z-0">
      <style>{`
        @keyframes floatSlow {
          0% {
            transform: translateY(0px) rotate(0deg) translateX(0px);
          }
          50% {
            transform: translateY(-80px) rotate(180deg) translateX(25px);
          }
          100% {
            transform: translateY(0px) rotate(360deg) translateX(0px);
          }
        }
        .slow-particle {
          animation: floatSlow linear/ease-in-out infinite;
        }
      `}</style>
      {particles.map((p) => {
        let borderRadius = '0px';
        let clipPath = undefined;
        let transform = undefined;

        if (p.shape === 'circle') {
          borderRadius = '50%';
        } else if (p.shape === 'diamond') {
          transform = 'rotate(45deg)';
        } else if (p.shape === 'triangle') {
          clipPath = 'polygon(50% 0%, 0% 100%, 100% 100%)';
        }

        return (
          <div
            key={p.id}
            className="absolute slow-particle"
            style={{
              left: p.left,
              bottom: p.bottom,
              width: p.size,
              height: p.size,
              backgroundColor: clipPath ? undefined : p.color,
              background: clipPath ? p.color : undefined,
              borderRadius,
              clipPath,
              transform,
              animationDuration: p.duration,
              animationDelay: p.delay,
            }}
          />
        );
      })}
    </div>
  );
}

export default function PodiumHero({ topThree, displayName, displayHandle }) {
  const winner1 = topThree[0];
  const winner2 = topThree[1];
  const winner3 = topThree[2];

  return (
    <div className="relative min-h-[580px] lg:min-h-[640px] w-full flex items-center justify-center py-12 px-4 select-none overflow-visible">
      {/* Confetti celebration system */}
      <ConfettiSystem />

      {/* Main podium alignment container */}
      <div className="relative z-10 w-full max-w-[1500px] flex flex-col md:flex-row md:items-end justify-center gap-12 md:gap-6 lg:gap-10">
        
        {/* Mobile View: Render Ranks in order (1, 2, 3) */}
        {/* Desktop View: Render Ranks side-by-side (2, 1, 3) */}
        
        {/* Desktop/Tablet Layout */}
        <div className="hidden md:flex md:flex-row md:items-end justify-center w-full gap-6 lg:gap-10">
          {/* Rank 2 (Left) */}
          {winner2 && (
            <div className="flex justify-center relative origin-bottom translate-y-3">
              {/* Silver Glow */}
              <div 
                className="absolute top-[10%] w-[380px] h-[380px] rounded-full blur-[80px] pointer-events-none -z-10" 
                style={{ background: 'radial-gradient(circle, rgba(148, 163, 184, 0.15), transparent 70%)' }} 
              />
              <PodiumCard
                entry={winner2}
                rank={2}
                displayName={displayName}
                displayHandle={displayHandle}
              />
            </div>
          )}

          {/* Rank 1 (Center) */}
          {winner1 && (
            <div className="flex justify-center relative z-25">
              {/* Champion Emerald Glow */}
              <div 
                className="absolute top-[5%] w-[700px] h-[700px] rounded-full blur-[100px] pointer-events-none -z-10" 
                style={{ background: 'radial-gradient(circle, rgba(16, 185, 129, 0.18), transparent 70%)' }} 
              />
              <PodiumCard
                entry={winner1}
                rank={1}
                displayName={displayName}
                displayHandle={displayHandle}
              />
            </div>
          )}

          {/* Rank 3 (Right) */}
          {winner3 && (
            <div className="flex justify-center relative origin-bottom translate-y-6">
              {/* Bronze Glow */}
              <div 
                className="absolute top-[10%] w-[380px] h-[380px] rounded-full blur-[80px] pointer-events-none -z-10" 
                style={{ background: 'radial-gradient(circle, rgba(217, 119, 6, 0.12), transparent 70%)' }} 
              />
              <PodiumCard
                entry={winner3}
                rank={3}
                displayName={displayName}
                displayHandle={displayHandle}
              />
            </div>
          )}
        </div>

        {/* Mobile Layout (Stacked Ranks: 1 on top, then 2, then 3) */}
        <div className="flex flex-col md:hidden gap-10 w-full items-center">
          {winner1 && (
            <div className="w-full max-w-[340px]">
              <PodiumCard
                entry={winner1}
                rank={1}
                displayName={displayName}
                displayHandle={displayHandle}
              />
            </div>
          )}
          {winner2 && (
            <div className="w-full max-w-[300px]">
              <PodiumCard
                entry={winner2}
                rank={2}
                displayName={displayName}
                displayHandle={displayHandle}
              />
            </div>
          )}
          {winner3 && (
            <div className="w-full max-w-[300px]">
              <PodiumCard
                entry={winner3}
                rank={3}
                displayName={displayName}
                displayHandle={displayHandle}
              />
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

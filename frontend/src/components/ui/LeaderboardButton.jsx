import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { DotLottieReact } from '@lottiefiles/dotlottie-react';
import { cn } from '../../utils/cn';

export default function LeaderboardButton() {
  const lottieRef = useRef(null);
  const [hovered, setHovered] = useState(false);

  const handleMouseEnter = () => {
    setHovered(true);
    if (lottieRef.current) {
      lottieRef.current.setFrame(0);
      lottieRef.current.play();
    }
  };

  const handleMouseLeave = () => {
    setHovered(false);
    if (lottieRef.current) {
      lottieRef.current.stop();
    }
  };

  return (
    <div style={{ position: 'relative', display: 'inline-flex' }}>

      {/* ── Trophy animation — floats above button on hover ── */}
      <div
        style={{
          position: 'absolute',
          top: hovered ? '-52px' : '0px',
          left: '50%',
          transform: hovered
            ? 'translateX(-50%) translateZ(0) rotateY(360deg) scale(1)'
            : 'translateX(-50%) translateZ(-80px) rotateY(0deg) scale(0.3)',
          width: '44px',
          height: '44px',
          opacity: hovered ? 1 : 0,
          pointerEvents: 'none',
          transition: hovered
            ? 'top 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s ease 0.05s, transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)'
            : 'top 0.3s ease, opacity 0.2s ease, transform 0.3s ease',
          zIndex: 20,
          filter: 'drop-shadow(0 4px 12px rgba(255, 179, 63, 0.5))',
        }}
      >
        <DotLottieReact
          src="/animations/Trophy.lottie"
          autoplay={hovered}
          loop={true}
          dotLottieRefCallback={(ref) => { lottieRef.current = ref; }}
          style={{ width: '100%', height: '100%' }}
        />
      </div>

      {/* ── The button itself ── */}
      <Link
        to="/leaderboard"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        aria-label="Open leaderboard"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          height: '40px',
          padding: '0 16px',
          borderRadius: '12px',
          textDecoration: 'none',
          position: 'relative',
          overflow: 'hidden',
          transition: 'all 0.3s ease',
          /* Light mode */
          background: hovered
            ? 'rgba(255, 179, 63, 0.08)'
            : 'rgba(0, 0, 0, 0.04)',
          border: hovered
            ? '1px solid rgba(255, 179, 63, 0.35)'
            : '1px solid rgba(0, 0, 0, 0.1)',
          color: hovered ? '#92610a' : '#4a4a5a',
          boxShadow: hovered
            ? '0 0 20px rgba(255, 179, 63, 0.15), 0 2px 8px rgba(0,0,0,0.08)'
            : '0 1px 3px rgba(0,0,0,0.06)',
          transform: hovered ? 'translateY(-1px)' : 'translateY(0)',
        }}
      >
        {/* Shimmer sweep — only visible on hover */}
        <span
          style={{
            position: 'absolute',
            inset: 0,
            background: 'linear-gradient(90deg, transparent, rgba(255,179,63,0.08), transparent)',
            transform: hovered ? 'translateX(100%)' : 'translateX(-100%)',
            transition: 'transform 0.7s ease-in-out',
            pointerEvents: 'none',
          }}
        />

        {/* Small trophy placeholder icon — visible when NOT hovered */}
        <span
          style={{
            width: '20px',
            height: '20px',
            flexShrink: 0,
            opacity: hovered ? 0 : 1,
            transition: 'opacity 0.2s ease',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M6 3h12v7a6 6 0 01-12 0V3z" fill="currentColor" opacity="0.7"/>
            <path d="M6 3H3a2 2 0 000 4c0 1.5 1 3 3 4V3z" fill="currentColor" opacity="0.4"/>
            <path d="M18 3h3a2 2 0 010 4c0 1.5-1 3-3 4V3z" fill="currentColor" opacity="0.4"/>
            <rect x="10" y="15" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.6"/>
            <rect x="7.5" y="19" width="9" height="2.5" rx="1.25" fill="currentColor" opacity="0.5"/>
          </svg>
        </span>

        {/* Label */}
        <span
          style={{
            fontSize: '13px',
            fontWeight: 600,
            letterSpacing: '0.02em',
            position: 'relative',
            whiteSpace: 'nowrap',
          }}
        >
          Leaderboard
        </span>
      </Link>
    </div>
  );
}
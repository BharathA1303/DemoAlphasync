

const SOCIAL_PROOF = [
  "500+ Active Traders",
  "₹50 Cr+ Simulated",
  "200+ NSE Stocks",
];

export default function AuthPanelLeft({ children }) {
  return (
    <div
      className="hidden lg:flex w-[52%] h-full border-r border-white/5 flex-col"
      style={{
        background:
          "linear-gradient(135deg, #1A2B4A 0%, #152340 50%, #0F1A30 100%)",
      }}
    >
      <div className="relative w-full h-full flex flex-col overflow-hidden">
        <div className="relative z-10 px-9 pt-9 flex-shrink-0">
          <a href="https://www.alphasync.app/">
            <img src="/logo.svg" alt="AlphaSync" className="h-16 object-contain logo-dark-bg" />
          </a>
        </div>

        <div className="relative z-10 flex-1 flex flex-col justify-center px-7 py-3 overflow-hidden">
          {children}
        </div>

        <div className="relative z-10 px-9 pb-9 flex-shrink-0">
          <div className="flex gap-2 mb-3 justify-start flex-wrap">
            {SOCIAL_PROOF.map((label, index) => (
              <div
                key={label}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[10px] font-semibold"
                style={{
                  background:
                    index === 0
                      ? 'rgba(14,165,233,0.10)'
                      : index === 1
                        ? 'rgba(46,158,107,0.10)'
                        : 'rgba(30,111,168,0.10)',
                  border:
                    index === 0
                      ? '1px solid rgba(14,165,233,0.25)'
                      : index === 1
                        ? '1px solid rgba(46,158,107,0.25)'
                        : '1px solid rgba(30,111,168,0.25)',
                  color: index === 0 ? '#00bcd4' : index === 1 ? '#2E9E6B' : '#1E6FA8',
                }}
              >
                {label}
              </div>
            ))}
          </div>

          <h2 className="text-[22px] font-black text-white leading-tight tracking-tight">
            Trade smarter.
            <br />
            <span style={{ color: '#00bcd4' }}>Risk nothing.</span>
          </h2>
          <p className="text-[12px] text-gray-400 mt-1.5 leading-relaxed">
            Practice with real NSE &amp; BSE data. ₹10,00,000 virtual capital.
          </p>
        </div>
      </div>
    </div>
  );
}

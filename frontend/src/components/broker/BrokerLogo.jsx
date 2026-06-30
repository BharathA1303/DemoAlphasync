import { useState } from "react";

/**
 * Broker brand mark — image from /public/brokers/ with text fallback.
 */
export default function BrokerLogo({
  broker,
  size = "md",
  className = "",
}) {
  const [imgFailed, setImgFailed] = useState(false);

  const sizeMap = {
    sm: { box: "w-10 h-10 rounded-lg", text: "text-[8px]", sub: "text-[5px]" },
    md: { box: "w-11 h-11 rounded-xl", text: "text-[9px]", sub: "text-[6px]" },
    lg: { box: "w-[52px] h-[52px] rounded-[10px]", text: "text-[9px]", sub: "text-[6px]" },
  };
  const s = sizeMap[size] || sizeMap.md;
  const showImage = broker?.logoSrc && !imgFailed;

  return (
    <div
      className={`${s.box} flex items-center justify-center flex-shrink-0 overflow-hidden ${className}`}
      style={{
        background: showImage ? "#fff" : `${broker?.color || "#64748b"}12`,
        border: showImage ? "1px solid rgba(0,0,0,0.06)" : `1.5px solid ${broker?.color || "#64748b"}30`,
      }}
    >
      {showImage ? (
        <img
          src={broker.logoSrc}
          alt={broker.name || "Broker"}
          className="w-full h-full object-contain p-1"
          onError={() => setImgFailed(true)}
        />
      ) : (
        <div className="flex flex-col items-center justify-center leading-none">
          <span
            className={`${s.text} font-black tracking-wider`}
            style={{ color: broker?.color || "#64748b" }}
          >
            {broker?.logoText || "?"}
          </span>
          {broker?.logoSub ? (
            <span
              className={`${s.sub} font-bold tracking-widest mt-0.5 opacity-60`}
              style={{ color: broker?.color || "#64748b" }}
            >
              {broker.logoSub}
            </span>
          ) : null}
        </div>
      )}
    </div>
  );
}

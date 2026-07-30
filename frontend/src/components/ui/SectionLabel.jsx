export function SectionLabel({ children, className = "" }) {
  return (
    <div className={`flex items-center justify-center gap-1.5 mb-3 ${className}`.trim()}>
      <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 inline-block" />
      <span className="text-xs font-semibold tracking-widest uppercase text-gray-500 dark:text-gray-400">
        {children}
      </span>
    </div>
  );
}

import React from 'react';
import { cn } from '../../utils/cn';

export default function LeaderboardFilters({ activePeriod, onPeriodChange, loading }) {
  const tabs = [
    { key: 'today', label: 'Today' },
    { key: 'weekly', label: 'Weekly' },
    { key: 'monthly', label: 'Monthly' },
    { key: 'yearly', label: 'Yearly' },
    { key: 'all_time', label: 'All Time' },
  ];

  return (
    <div className="flex flex-wrap gap-3 py-2">
      {tabs.map((tab) => {
        const isActive = activePeriod === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            disabled={loading}
            onClick={() => onPeriodChange(tab.key)}
            className={cn(
              "px-5 py-2 text-xs font-semibold tracking-wide transition-all duration-200 rounded-[16px]",
              isActive
                ? "bg-emerald-50 text-emerald-600 border border-emerald-500/30 font-bold shadow-sm"
                : "bg-gray-100 text-gray-500 hover:bg-emerald-50/50 hover:text-emerald-600 border border-transparent"
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

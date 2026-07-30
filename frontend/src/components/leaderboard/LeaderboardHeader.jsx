import React from 'react';
import { Trophy, RefreshCw } from 'lucide-react';
import { cn } from '../../utils/cn';

export default function LeaderboardHeader({ loading, onRefresh }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 py-6">
      <div className="flex items-center gap-4">
        {/* Trophy icon container */}
        <div className="w-16 h-16 rounded-full bg-emerald-50 text-emerald-500 flex items-center justify-center shadow-sm border border-emerald-100 flex-shrink-0">
          <Trophy className="w-8 h-8" strokeWidth={2} />
        </div>
        <div>
          <h1 className="text-3xl sm:text-4xl font-display font-bold text-gray-900 tracking-tight">
            Leaderboard
          </h1>
          <p className="text-sm font-medium text-gray-500 mt-1 flex items-center gap-1.5 flex-wrap">
            <span>Real-time rankings</span>
            <span className="text-emerald-500 font-bold">•</span>
            <span>Compete. Trade. Win.</span>
          </p>
        </div>
      </div>
      
      {/* Refresh Button */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="h-11 px-5 rounded-full border border-gray-200 bg-white text-gray-700 font-semibold text-sm hover:bg-gray-50 hover:border-gray-300 transition-all duration-150 inline-flex items-center gap-2 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RefreshCw className={cn('w-4 h-4 text-gray-500', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>
    </div>
  );
}

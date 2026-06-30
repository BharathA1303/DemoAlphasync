import React from 'react';
import { Search, ChevronDown } from 'lucide-react';

export default function SearchControls({ searchQuery, onSearchChange, sortBy, onSortChange }) {
  const sortOptions = [
    { key: 'rank', label: 'Rank' },
    { key: 'pnl', label: 'P&L' },
    { key: 'percent', label: 'Return %' },
    { key: 'alphabetical', label: 'Alphabetical' },
  ];

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-4 py-4 w-full">
      {/* Top Traders Section Header */}
      <div className="flex items-center gap-3 self-start sm:self-center">
        <div className="w-10 h-10 rounded-full bg-emerald-50 text-emerald-500 flex items-center justify-center flex-shrink-0 border border-emerald-100/50 shadow-sm">
          <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
          </svg>
        </div>
        <div>
          <h2 className="text-lg font-bold text-gray-800 leading-none">Top Traders</h2>
          <p className="text-xs text-gray-400 mt-1 font-medium">Rankings are based on All Time P&L</p>
        </div>
      </div>

      {/* Search & Sort Controls */}
      <div className="flex flex-col sm:flex-row items-center gap-3 w-full sm:w-auto">
        {/* Search Box */}
        <div className="relative w-full sm:w-72">
          <input
            type="text"
            placeholder="Search traders..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full h-[52px] pl-5 pr-12 rounded-[16px] border border-gray-200 bg-white/90 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 transition-all duration-200"
          />
          <Search className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
        </div>

        {/* Sort Dropdown */}
        <div className="relative w-full sm:w-auto flex-shrink-0">
          <div className="flex items-center h-[52px] px-5 rounded-[16px] border border-gray-200 bg-white shadow-sm cursor-pointer hover:bg-gray-50 hover:border-gray-300 transition-all duration-150">
            <span className="text-xs font-semibold text-gray-500 mr-2 whitespace-nowrap">Sort by:</span>
            <select
              value={sortBy}
              onChange={(e) => onSortChange(e.target.value)}
              className="appearance-none bg-transparent pr-6 text-xs font-bold text-gray-800 focus:outline-none cursor-pointer w-full h-full"
            >
              {sortOptions.map((opt) => (
                <option key={opt.key} value={opt.key} className="bg-white text-gray-800">
                  {opt.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
          </div>
        </div>
      </div>
    </div>
  );
}

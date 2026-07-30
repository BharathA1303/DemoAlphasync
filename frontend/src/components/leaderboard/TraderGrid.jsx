import React from 'react';
import TraderCard from './TraderCard';

export default function TraderGrid({ entries, displayName, displayHandle }) {
  if (!entries || entries.length === 0) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 py-4">
      {entries.map((entry) => (
        <TraderCard
          key={entry.user_id}
          entry={entry}
          displayName={displayName}
          displayHandle={displayHandle}
        />
      ))}
    </div>
  );
}

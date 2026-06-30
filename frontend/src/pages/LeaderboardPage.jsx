import { useEffect, useMemo, useState } from 'react';
import api from '../services/api';
import { useAuthStore } from '../stores/useAuthStore';

// Import newly created modular subcomponents
import LeaderboardHeader from '../components/leaderboard/LeaderboardHeader';
import LeaderboardFilters from '../components/leaderboard/LeaderboardFilters';
import PodiumHero from '../components/leaderboard/PodiumHero';
import SearchControls from '../components/leaderboard/SearchControls';
import TraderGrid from '../components/leaderboard/TraderGrid';
import LeaderboardFooter from '../components/leaderboard/LeaderboardFooter';

export default function LeaderboardPage() {
    const user = useAuthStore((s) => s.user);
    const [period, setPeriod] = useState('all_time');
    const [leaderboard, setLeaderboard] = useState({ winners: [] });
    const [loading, setLoading] = useState(false);
    
    // Search and Sort State
    const [searchQuery, setSearchQuery] = useState('');
    const [sortBy, setSortBy] = useState('rank');

    const currentUserId = String(user?.id || user?.user_id || '').toLowerCase();
    const currentUsername = String(user?.username || '').toLowerCase();

    // Check if the entry belongs to the logged-in user
    const isCurrentUser = (entry) => {
        const entryUserId = String(entry?.user_id || '').toLowerCase();
        const entryUsername = String(entry?.username || '').toLowerCase();
        return Boolean(
            (currentUserId && entryUserId && currentUserId === entryUserId)
            || (currentUsername && entryUsername && currentUsername === entryUsername)
        );
    };

    // Helper formatting methods matching original API data accessors
    const displayName = (entry) => (isCurrentUser(entry) ? 'You' : (entry.full_name || entry.username || entry.user_id));
    const displayHandle = (entry) => (isCurrentUser(entry) ? '@you' : `@${entry.username || entry.user_id}`);

    const entries = useMemo(() => leaderboard.winners || [], [leaderboard]);
    
    // Top 3 for the Hero Podium Section (always based on actual period rank, unaffected by grid search/sort)
    const topThree = useMemo(() => entries.slice(0, 3), [entries]);

    // Fetch winners from the portfolio leaderboard API
    async function loadLeaderboard(selectedPeriod = period) {
        setLoading(true);
        try {
            const { data } = await api.get('/portfolio/leaderboard', {
                params: { period: selectedPeriod, limit: 50 },
            });
            setLeaderboard({
                winners: Array.isArray(data?.winners) ? data.winners : [],
            });
        } catch {
            setLeaderboard({ winners: [] });
        } finally {
            setLoading(false);
        }
    }

    // Refresh function linked to the header button
    const handleRefresh = () => {
        loadLeaderboard(period);
    };

    // Period tab selection change
    const handlePeriodChange = (newPeriod) => {
        setPeriod(newPeriod);
    };

    // Polling setup: fetch leaderboard data every 15 seconds
    useEffect(() => {
        loadLeaderboard(period);

        const timer = window.setInterval(() => {
            loadLeaderboard(period);
        }, 15000);

        return () => window.clearInterval(timer);
    }, [period]);

    // Local filtering based on search input
    const filteredEntries = useMemo(() => {
        if (!searchQuery.trim()) return entries;
        const query = searchQuery.toLowerCase();
        return entries.filter((entry) => {
            const name = String(entry.full_name || entry.username || entry.user_id).toLowerCase();
            const handle = String(entry.username || entry.user_id).toLowerCase();
            return name.includes(query) || handle.includes(query);
        });
    }, [entries, searchQuery]);

    // Local sorting based on dropdown selection
    const sortedAndFilteredEntries = useMemo(() => {
        const list = [...filteredEntries];
        if (sortBy === 'rank') {
            list.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
        } else if (sortBy === 'pnl') {
            list.sort((a, b) => (b.pnl ?? 0) - (a.pnl ?? 0));
        } else if (sortBy === 'percent') {
            // API field is pnl_percent
            list.sort((a, b) => (b.pnl_percent ?? 0) - (a.pnl_percent ?? 0));
        } else if (sortBy === 'alphabetical') {
            list.sort((a, b) => {
                const nameA = String(a.full_name || a.username || a.user_id).toLowerCase();
                const nameB = String(b.full_name || b.username || b.user_id).toLowerCase();
                return nameA.localeCompare(nameB);
            });
        }
        return list;
    }, [filteredEntries, sortBy]);

    return (
        <div 
            className="p-6 lg:p-8 max-w-[1700px] px-10 mx-auto space-y-6 select-none bg-gray-50/15 rounded-3xl"
            style={{
                backgroundImage: 'radial-gradient(circle at center, rgba(16,185,129,0.05), transparent 60%)',
            }}
        >
            {/* Header Section */}
            <LeaderboardHeader 
                loading={loading} 
                onRefresh={handleRefresh} 
            />

            {/* Time Period Filters */}
            <LeaderboardFilters 
                activePeriod={period} 
                onPeriodChange={handlePeriodChange} 
                loading={loading}
            />

            {/* Hero Podium Section */}
            {topThree.length > 0 ? (
                <PodiumHero
                    topThree={topThree}
                    displayName={displayName}
                    displayHandle={displayHandle}
                />
            ) : (
                <div className="h-64 flex items-center justify-center border border-dashed border-gray-200 rounded-[28px] bg-white shadow-[0_4px_12px_rgba(0,0,0,0.02)]">
                    <p className="text-sm font-medium text-gray-400">
                        {loading ? 'Loading top traders...' : 'No data available for this period.'}
                    </p>
                </div>
            )}

            {/* Grid Header and Controls */}
            <SearchControls
                searchQuery={searchQuery}
                onSearchChange={setSearchQuery}
                sortBy={sortBy}
                onSortChange={setSortBy}
            />

            {/* Trader Card Grid */}
            {sortedAndFilteredEntries.length > 0 ? (
                <TraderGrid
                    entries={sortedAndFilteredEntries}
                    displayName={displayName}
                    displayHandle={displayHandle}
                />
            ) : (
                <div className="h-48 flex items-center justify-center border border-dashed border-gray-200 rounded-[24px] bg-white shadow-[0_4px_12px_rgba(0,0,0,0.02)]">
                    <p className="text-sm font-medium text-gray-400">
                        {loading ? 'Searching leaderboard...' : 'No matching traders found.'}
                    </p>
                </div>
            )}

            {/* Live Status Footer */}
            <LeaderboardFooter />
        </div>
    );
}

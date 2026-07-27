import { useCallback } from 'react';
import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';

import { ErrorState, LoadingState } from '@/components/screen-state';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';
import { useApi } from '@/hooks/use-api';
import { fetchLeaderboard, type LeaderboardEntry } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';

// Gold, silver, bronze for the top three; everyone else gets the muted treatment.
const RANK_COLORS = ['#fbbf24', '#cbd5e1', '#b45309'];

export default function LeaderboardScreen() {
  const { session } = useAuth();
  const token = session?.access_token;

  // Public, but the token makes the API flag which row is yours
  const fetcher = useCallback(() => fetchLeaderboard(token), [token]);
  const { data, error, loading, reload } = useApi(fetcher);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;

  return (
    <ThemedView style={styles.screen}>
      <FlatList
        data={data ?? []}
        keyExtractor={(entry, index) => `${entry.username ?? 'anon'}-${index}`}
        renderItem={({ item, index }) => <Row entry={item} rank={index + 1} />}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} />}
        ListHeaderComponent={
          <ThemedText type="small" themeColor="textSecondary" style={styles.caption}>
            Ranked by net worth — cash plus holdings at current prices
          </ThemedText>
        }
        ListEmptyComponent={
          <View style={styles.centered}>
            <ThemedText type="small" themeColor="textSecondary">
              No players yet.
            </ThemedText>
          </View>
        }
      />
    </ThemedView>
  );
}

function Row({ entry, rank }: { entry: LeaderboardEntry; rank: number }) {
  const rankColor = RANK_COLORS[rank - 1];

  return (
    <ThemedView
      type={entry.is_you ? 'backgroundElement' : 'background'}
      style={styles.row}>
      <ThemedText
        type="smallBold"
        style={[styles.rank, rankColor ? { color: rankColor } : undefined]}>
        {rank}
      </ThemedText>

      <View style={styles.who}>
        <View style={styles.nameRow}>
          <ThemedText type="default">{entry.username ?? 'Anonymous'}</ThemedText>
          {entry.is_you ? (
            <ThemedText type="small" style={styles.youBadge}>
              You
            </ThemedText>
          ) : null}
        </View>
        <ThemedText type="small" themeColor="textSecondary">
          {entry.bars.toFixed(0)} cash · {entry.holdings_value.toFixed(0)} invested
        </ThemedText>
      </View>

      <ThemedText type="smallBold">{entry.net_worth.toFixed(2)}</ThemedText>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  list: { paddingBottom: Spacing.five },
  caption: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.three,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.three,
  },
  rank: {
    width: 24,
    textAlign: 'center',
  },
  who: {
    flex: 1,
    gap: Spacing.half,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.two,
  },
  youBadge: {
    backgroundColor: 'rgba(139, 92, 246, 0.2)',
    color: '#c084fc',
    paddingHorizontal: Spacing.two,
    paddingVertical: Spacing.half,
    borderRadius: 4,
    fontSize: 12,
    overflow: 'hidden',
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: 'rgba(128, 128, 128, 0.3)',
    marginLeft: Spacing.three,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.four,
  },
});

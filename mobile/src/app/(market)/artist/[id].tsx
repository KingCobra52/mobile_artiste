import { Stack, useLocalSearchParams } from 'expo-router';
import { useCallback } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { PriceChart } from '@/components/price-chart';
import { ErrorState, LoadingState } from '@/components/screen-state';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { TierBadge } from '@/components/tier-badge';
import { TradePanel } from '@/components/trade-panel';
import { Spacing } from '@/constants/theme';
import { useApi } from '@/hooks/use-api';
import { fetchArtist, fetchArtistHistory } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';

export default function ArtistScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { session } = useAuth();

  // The token is what makes the API fill in shares_owned; without it the endpoint
  // still works and returns 0, which is correct for a signed-out viewer.
  const token = session?.access_token;
  const fetcher = useCallback(() => fetchArtist(id, token), [id, token]);
  const { data, error, loading, reload } = useApi(fetcher);

  // Separate from the detail fetch: history doesn't change when you trade, so a
  // buy shouldn't refetch 35 days of prices to redraw the same line.
  const historyFetcher = useCallback(() => fetchArtistHistory(id), [id]);
  const { data: history } = useApi(historyFetcher);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  // Null rather than 0 is the signal that YouTube data is genuinely absent - the
  // API renormalizes the remaining weights so the price stays comparable.
  const hasYouTube = data.subscribers !== null;

  return (
    <ThemedView style={styles.screen}>
      <Stack.Screen options={{ title: data.name ?? 'Artist' }} />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <ThemedText type="subtitle">{data.name}</ThemedText>
          <TierBadge tier={data.tier} />
        </View>

        <View style={styles.priceBlock}>
          <ThemedText type="title">{data.price_per_share.toFixed(2)}</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            bars per share
          </ThemedText>
        </View>

        {history ? <PriceChart points={history} /> : null}

        <TradePanel
          artistId={data.id}
          pricePerShare={data.price_per_share}
          sharesOwned={data.shares_owned}
          onTraded={reload}
        />

        <Section title="Last.fm">
          <Stat label="Monthly listeners" value={data.listeners} />
          <Stat label="Playcount" value={data.playcount} />
        </Section>

        <Section title="YouTube">
          {hasYouTube ? (
            <>
              <Stat label="Subscribers" value={data.subscribers} />
              <Stat label="Avg views, recent videos" value={data.recent_videos_avg_views} />
              <Stat label="Avg likes, recent videos" value={data.recent_videos_like_ratio} />
            </>
          ) : (
            <ThemedText type="small" themeColor="textSecondary">
              No verified channel yet, so this artist is priced on Last.fm signals alone.
            </ThemedText>
          )}
        </Section>

        {data.date ? (
          <ThemedText type="small" themeColor="textSecondary" style={styles.updated}>
            Updated {data.date}
          </ThemedText>
        ) : null}
      </ScrollView>
    </ThemedView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <ThemedText type="smallBold" themeColor="textSecondary">
        {title.toUpperCase()}
      </ThemedText>
      {children}
    </View>
  );
}

function Stat({ label, value }: { label: string; value: number | null }) {
  return (
    <View style={styles.stat}>
      <ThemedText type="small" themeColor="textSecondary">
        {label}
      </ThemedText>
      <ThemedText type="small">
        {value === null ? '—' : Math.round(value).toLocaleString()}
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  content: {
    padding: Spacing.three,
    gap: Spacing.four,
  },
  header: {
    gap: Spacing.two,
  },
  priceBlock: {
    gap: Spacing.one,
  },
  section: {
    gap: Spacing.two,
  },
  stat: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: Spacing.three,
  },
  updated: {
    paddingTop: Spacing.two,
  },
});

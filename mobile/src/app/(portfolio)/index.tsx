import { Link } from 'expo-router';
import { useCallback } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';

import { ErrorState, LoadingState } from '@/components/screen-state';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';
import { useApi } from '@/hooks/use-api';
import { useTheme } from '@/hooks/use-theme';
import { fetchPortfolio, type PortfolioHolding } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { FLAT_BARS, toneFor } from '@/lib/gain-loss';

export default function PortfolioScreen() {
  const { session, loading: authLoading } = useAuth();

  if (authLoading) return <LoadingState />;
  if (!session) {
    return (
      <ThemedView style={styles.centered}>
        <ThemedText type="smallBold">Not signed in</ThemedText>
        <ThemedText type="small" themeColor="textSecondary" style={styles.centeredText}>
          Sign in on the Account tab to see your holdings.
        </ThemedText>
      </ThemedView>
    );
  }
  return <SignedInPortfolio token={session.access_token} />;
}

function SignedInPortfolio({ token }: { token: string }) {
  const theme = useTheme();
  const fetcher = useCallback(() => fetchPortfolio(token), [token]);
  const { data, error, loading, reload } = useApi(fetcher);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <ThemedView style={styles.screen}>
      <FlatList
        data={data.holdings}
        keyExtractor={(holding) => String(holding.holding_id)}
        renderItem={({ item }) => <HoldingRow holding={item} />}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} />}
        ListHeaderComponent={
          <View style={styles.summary}>
            <Summary label="Cash" value={`${Number(data.bars).toFixed(2)} bars`} />
            <Summary label="Holdings" value={`${data.holdings_value.toFixed(2)} bars`} />
            <Summary
              label="Unrealised"
              value={formatSigned(data.total_gain_loss)}
              color={toneFor(data.total_gain_loss, FLAT_BARS, theme.textSecondary)}
            />
          </View>
        }
        ListEmptyComponent={
          <View style={styles.centered}>
            <ThemedText type="small" themeColor="textSecondary">
              You don&apos;t own any shares yet.
            </ThemedText>
          </View>
        }
      />
    </ThemedView>
  );
}

function Summary({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={styles.summaryItem}>
      <ThemedText type="small" themeColor="textSecondary">
        {label}
      </ThemedText>
      <ThemedText type="smallBold" style={color ? { color } : undefined}>
        {value}
      </ThemedText>
    </View>
  );
}

function HoldingRow({ holding }: { holding: PortfolioHolding }) {
  const theme = useTheme();

  return (
    <Link href={{ pathname: '/artist/[id]', params: { id: holding.artist_id } }} asChild>
      <Pressable style={styles.row}>
        <View style={styles.rowHeader}>
          <ThemedText type="default">{holding.name}</ThemedText>
          <ThemedText
            type="smallBold"
            style={{ color: toneFor(holding.gain_loss, FLAT_BARS, theme.textSecondary) }}
          >
            {formatSigned(holding.gain_loss)}
          </ThemedText>
        </View>
        <View style={styles.rowDetail}>
          {/* Per lot, not per artist - each purchase keeps the price it was
              bought at, which is what makes this comparison meaningful */}
          <ThemedText type="small" themeColor="textSecondary">
            {holding.shares} @ {holding.price_per_share.toFixed(2)} → {holding.current_price.toFixed(2)}
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {holding.bought_at}
          </ThemedText>
        </View>
      </Pressable>
    </Link>
  );
}

function formatSigned(value: number) {
  if (Math.abs(value) < FLAT_BARS) return '0.00';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`;
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  list: { paddingBottom: Spacing.five },
  summary: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: Spacing.three,
    gap: Spacing.three,
  },
  summaryItem: { gap: Spacing.one },
  row: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.three,
    gap: Spacing.one,
  },
  rowHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  rowDetail: {
    flexDirection: 'row',
    justifyContent: 'space-between',
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
    gap: Spacing.two,
    padding: Spacing.four,
  },
  centeredText: { textAlign: 'center' },
});

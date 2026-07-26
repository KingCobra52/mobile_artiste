import { Link } from 'expo-router';
import { FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';

import { ErrorState, LoadingState } from '@/components/screen-state';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { TierBadge } from '@/components/tier-badge';
import { Spacing } from '@/constants/theme';
import { useApi } from '@/hooks/use-api';
import { fetchMarket, type MarketArtist } from '@/lib/api';

export default function MarketScreen() {
  const { data, error, loading, reload } = useApi(fetchMarket);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;

  return (
    <ThemedView style={styles.screen}>
      <FlatList
        data={data ?? []}
        keyExtractor={(artist) => String(artist.id)}
        renderItem={({ item }) => <MarketRow artist={item} />}
        ItemSeparatorComponent={Separator}
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} />}
        ListHeaderComponent={
          <ThemedText type="small" themeColor="textSecondary" style={styles.count}>
            {data?.length ?? 0} artists listed
          </ThemedText>
        }
      />
    </ThemedView>
  );
}

function MarketRow({ artist }: { artist: MarketArtist }) {
  return (
    <Link href={{ pathname: '/artist/[id]', params: { id: artist.id } }} asChild>
      <Pressable style={styles.row}>
        <View style={styles.rowLeft}>
          <ThemedText type="default">{artist.name}</ThemedText>
          <TierBadge tier={artist.tier} />
        </View>
        <View style={styles.rowRight}>
          <ThemedText type="smallBold">{artist.price_per_share.toFixed(2)}</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            bars
          </ThemedText>
        </View>
      </Pressable>
    </Link>
  );
}

function Separator() {
  return <View style={styles.separator} />;
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  list: {
    paddingBottom: Spacing.five,
  },
  count: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.three,
    gap: Spacing.three,
  },
  rowLeft: {
    gap: Spacing.one,
    flexShrink: 1,
  },
  rowRight: {
    alignItems: 'flex-end',
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: 'rgba(128, 128, 128, 0.3)',
    marginLeft: Spacing.three,
  },
});

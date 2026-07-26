import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';

// Same three tiers and colours the Flask templates used, so the app reads as the
// same product. Null tier falls back to Breaking, matching market.html.
const TIER_STYLES: Record<string, { background: string; text: string }> = {
  Established: { background: 'rgba(139, 92, 246, 0.15)', text: '#a78bfa' },
  Rising: { background: 'rgba(16, 185, 129, 0.15)', text: '#34d399' },
  Breaking: { background: 'rgba(251, 191, 36, 0.15)', text: '#fbbf24' },
};

export function TierBadge({ tier }: { tier: string | null }) {
  const label = tier ?? 'Breaking';
  const colors = TIER_STYLES[label] ?? TIER_STYLES.Breaking;

  return (
    <View style={[styles.badge, { backgroundColor: colors.background }]}>
      <ThemedText style={[styles.label, { color: colors.text }]}>{label}</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: Spacing.two,
    paddingVertical: Spacing.one,
    borderRadius: 4,
    alignSelf: 'flex-start',
  },
  label: {
    fontSize: 12,
    fontWeight: '600',
    lineHeight: 16,
  },
});

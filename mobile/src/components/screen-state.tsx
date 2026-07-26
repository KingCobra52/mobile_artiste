import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';

export function LoadingState() {
  return (
    <View style={styles.centered}>
      <ActivityIndicator />
    </View>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <View style={styles.centered}>
      <ThemedText type="smallBold">Couldn&apos;t load</ThemedText>
      <ThemedText type="small" themeColor="textSecondary" style={styles.message}>
        {error.message}
      </ThemedText>
      <Pressable onPress={onRetry} accessibilityRole="button">
        <ThemedText type="linkPrimary">Try again</ThemedText>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.two,
    padding: Spacing.four,
  },
  message: {
    textAlign: 'center',
  },
});

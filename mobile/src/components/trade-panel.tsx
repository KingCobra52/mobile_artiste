import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { buyShares, sellShares, type TradeResult } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';

type Props = {
  artistId: number;
  pricePerShare: number;
  sharesOwned: number;
  /** Refetch the artist so shares_owned reflects the trade. */
  onTraded: () => void;
};

export function TradePanel({ artistId, pricePerShare, sharesOwned, onTraded }: Props) {
  const { session } = useAuth();
  const theme = useTheme();
  const [quantity, setQuantity] = useState('1');
  const [busy, setBusy] = useState<'buy' | 'sell' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TradeResult | null>(null);

  if (!session) {
    return (
      <ThemedView type="backgroundElement" style={styles.panel}>
        <ThemedText type="small" themeColor="textSecondary">
          Sign in on the Account tab to trade this artist.
        </ThemedText>
      </ThemedView>
    );
  }

  // The API validates this too - it's the only side that can be trusted - but
  // catching it here avoids a pointless round trip and a 422 the user can't read.
  const shares = Number.parseInt(quantity, 10);
  const validQuantity = Number.isInteger(shares) && shares > 0;
  const estimate = validQuantity ? shares * pricePerShare : 0;

  const trade = async (side: 'buy' | 'sell') => {
    if (!validQuantity) {
      setError('Enter a whole number of shares greater than zero.');
      return;
    }
    setBusy(side);
    setError(null);
    setResult(null);
    try {
      const call = side === 'buy' ? buyShares : sellShares;
      setResult(await call(session.access_token, artistId, shares));
      onTraded();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <ThemedView type="backgroundElement" style={styles.panel}>
      <View style={styles.row}>
        <ThemedText type="small" themeColor="textSecondary">
          You own
        </ThemedText>
        <ThemedText type="smallBold">
          {sharesOwned} {sharesOwned === 1 ? 'share' : 'shares'}
        </ThemedText>
      </View>

      <View style={styles.quantityRow}>
        <TextInput
          value={quantity}
          onChangeText={setQuantity}
          keyboardType="number-pad"
          accessibilityLabel="Number of shares"
          style={[styles.input, { color: theme.text, backgroundColor: theme.background }]}
          placeholder="0"
          placeholderTextColor={theme.textSecondary}
        />
        <ThemedText type="small" themeColor="textSecondary" style={styles.estimate}>
          {validQuantity ? `≈ ${estimate.toFixed(2)} bars` : 'enter a quantity'}
        </ThemedText>
      </View>

      <View style={styles.buttons}>
        <TradeButton
          label="Buy"
          onPress={() => trade('buy')}
          busy={busy === 'buy'}
          disabled={busy !== null}
        />
        <TradeButton
          label="Sell"
          onPress={() => trade('sell')}
          busy={busy === 'sell'}
          // Nothing to sell is a state the button should show, not an error the
          // server has to explain after a round trip
          disabled={busy !== null || sharesOwned === 0}
        />
      </View>

      {error ? (
        <ThemedText type="small" style={styles.error}>
          {error}
        </ThemedText>
      ) : null}
      {result ? (
        <ThemedText type="small" themeColor="textSecondary">
          Done. {Number(result.bars).toLocaleString()} bars left, {result.shares_owned} owned.
        </ThemedText>
      ) : null}
    </ThemedView>
  );
}

function TradeButton({
  label,
  onPress,
  busy,
  disabled,
}: {
  label: string;
  onPress: () => void;
  busy: boolean;
  disabled: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={styles.buttonWrapper}>
      <ThemedView
        type="backgroundSelected"
        style={[styles.button, disabled && !busy && styles.buttonDisabled]}>
        {busy ? <ActivityIndicator /> : <ThemedText type="smallBold">{label}</ThemedText>}
      </ThemedView>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  panel: {
    padding: Spacing.three,
    borderRadius: Spacing.two,
    gap: Spacing.three,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  quantityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.three,
  },
  input: {
    flex: 1,
    paddingVertical: Spacing.two,
    paddingHorizontal: Spacing.three,
    borderRadius: Spacing.two,
    fontSize: 16,
  },
  estimate: {
    flexShrink: 0,
  },
  buttons: {
    flexDirection: 'row',
    gap: Spacing.three,
  },
  buttonWrapper: {
    flex: 1,
  },
  button: {
    paddingVertical: Spacing.three,
    borderRadius: Spacing.two,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.4,
  },
  error: {
    color: '#ef4444',
  },
});

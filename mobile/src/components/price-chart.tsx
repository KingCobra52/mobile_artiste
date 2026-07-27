import { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Line, Polyline } from 'react-native-svg';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { PricePoint } from '@/lib/api';

const HEIGHT = 120;
const GAIN = '#34d399';
const LOSS = '#ef4444';

export function PriceChart({ points }: { points: PricePoint[] }) {
  const theme = useTheme();
  // Measured rather than assumed, so the line spans the real width on any device
  const [width, setWidth] = useState(0);

  // One point is a dot, zero is nothing - neither is a line, and scaling either
  // would divide by a zero span.
  if (points.length < 2) {
    return (
      <View style={styles.empty}>
        <ThemedText type="small" themeColor="textSecondary">
          Not enough history to chart yet.
        </ThemedText>
      </View>
    );
  }

  const prices = points.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  // A perfectly flat series would otherwise divide by zero; render it mid-height.
  const span = max - min || 1;

  const first = prices[0];
  const last = prices[prices.length - 1];
  const change = last - first;
  const pct = first ? (100 * change) / first : 0;
  const stroke = change >= 0 ? GAIN : LOSS;

  const polyline = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * width;
      // SVG y grows downward, so a high price needs a small y
      const y = HEIGHT - ((p.price - min) / span) * HEIGHT;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <ThemedText type="small" themeColor="textSecondary">
          {points.length} days
        </ThemedText>
        <ThemedText type="smallBold" style={{ color: stroke }}>
          {change >= 0 ? '+' : ''}
          {change.toFixed(2)} ({pct >= 0 ? '+' : ''}
          {pct.toFixed(1)}%)
        </ThemedText>
      </View>

      <View onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
        {width > 0 ? (
          <Svg width={width} height={HEIGHT}>
            {/* Baseline at the opening price, so the shape reads as gain or loss
                against where it started rather than against the axis floor */}
            <Line
              x1={0}
              x2={width}
              y1={HEIGHT - ((first - min) / span) * HEIGHT}
              y2={HEIGHT - ((first - min) / span) * HEIGHT}
              stroke={theme.textSecondary}
              strokeWidth={StyleSheet.hairlineWidth}
              strokeDasharray="4 4"
            />
            <Polyline
              points={polyline}
              fill="none"
              stroke={stroke}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          </Svg>
        ) : (
          <View style={{ height: HEIGHT }} />
        )}
      </View>

      <View style={styles.header}>
        <ThemedText type="small" themeColor="textSecondary">
          {points[0].date}
        </ThemedText>
        {/* The axis is auto-scaled to the series, so label the range - otherwise a
            0.2-bar wiggle looks identical to a 50-bar rally */}
        <ThemedText type="small" themeColor="textSecondary">
          {min.toFixed(2)} – {max.toFixed(2)}
        </ThemedText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: Spacing.two },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  empty: {
    height: HEIGHT,
    alignItems: 'center',
    justifyContent: 'center',
  },
});

import { Stack } from 'expo-router';

/**
 * Stack nested inside the Market tab, so tapping an artist pushes the detail
 * screen without losing the tab bar. The detail screen sets its own title from
 * the artist name via Stack.Screen.
 */
export default function MarketLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Market' }} />
      <Stack.Screen name="artist/[id]" options={{ title: 'Artist' }} />
    </Stack>
  );
}

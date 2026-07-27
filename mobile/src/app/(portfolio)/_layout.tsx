import { Stack } from 'expo-router';

export default function PortfolioLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Portfolio' }} />
    </Stack>
  );
}

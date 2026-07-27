import { NativeTabs } from 'expo-router/unstable-native-tabs';
import { useColorScheme } from 'react-native';

import { Colors } from '@/constants/theme';

/**
 * Each trigger maps to a route group with its own Stack, so pushing a detail
 * screen inside one tab doesn't disturb the others. Keep app-tabs.web.tsx in
 * sync - it declares the same set for web.
 */
export default function AppTabs() {
  const scheme = useColorScheme();
  const colors = Colors[scheme === 'unspecified' ? 'light' : scheme];

  return (
    <NativeTabs
      backgroundColor={colors.background}
      indicatorColor={colors.backgroundElement}
      labelStyle={{ selected: { color: colors.text } }}>
      <NativeTabs.Trigger name="(market)">
        <NativeTabs.Trigger.Label>Market</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="chart.line.uptrend.xyaxis" md="trending_up" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="(portfolio)">
        <NativeTabs.Trigger.Label>Portfolio</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="briefcase" md="work" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="(leaderboard)">
        <NativeTabs.Trigger.Label>Leaders</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="trophy" md="emoji_events" />
      </NativeTabs.Trigger>

      <NativeTabs.Trigger name="(account)">
        <NativeTabs.Trigger.Label>Account</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf="person.crop.circle" md="account_circle" />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}

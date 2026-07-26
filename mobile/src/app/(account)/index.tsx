import { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { ErrorState, LoadingState } from '@/components/screen-state';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';
import { useApi } from '@/hooks/use-api';
import { useTheme } from '@/hooks/use-theme';
import { fetchProfile } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import { supabase } from '@/lib/supabase';

export default function AccountScreen() {
  const { session, loading } = useAuth();

  if (loading) return <LoadingState />;
  return session ? <SignedIn token={session.access_token} /> : <SignedOut />;
}

function SignedIn({ token }: { token: string }) {
  const fetcher = useCallback(() => fetchProfile(token), [token]);
  const { data, error, loading, reload } = useApi(fetcher);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <ThemedView style={styles.screen}>
      <View style={styles.content}>
        <View>
          <ThemedText type="subtitle">{data.username ?? 'No username'}</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {data.email}
          </ThemedText>
        </View>

        <View>
          <ThemedText type="title">{Number(data.bars).toLocaleString()}</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            bars available
          </ThemedText>
        </View>

        <Pressable onPress={() => supabase.auth.signOut()} accessibilityRole="button">
          <ThemedText type="linkPrimary">Sign out</ThemedText>
        </Pressable>
      </View>
    </ThemedView>
  );
}

function SignedOut() {
  const [mode, setMode] = useState<'sign-in' | 'sign-up'>('sign-in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [username, setUsername] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);

    if (mode === 'sign-up') {
      const { data, error: signUpError } = await supabase.auth.signUp({
        email,
        password,
        // The on_auth_user_created trigger reads username out of this metadata
        // to build the profiles row, so it has to be set at signup time.
        options: { data: { username: username.trim() } },
      });

      if (signUpError) {
        setError(signUpError.message);
      } else if (!data.session) {
        // The project requires email confirmation, so signUp returns a user but
        // no session until the link is clicked. Without this branch the screen
        // would just sit there looking broken.
        setMessage(`Check ${email} for a confirmation link, then sign in.`);
        setMode('sign-in');
      }
    } else {
      const { error: signInError } = await supabase.auth.signInWithPassword({ email, password });
      if (signInError) setError(signInError.message);
    }

    setBusy(false);
  };

  return (
    <ThemedView style={styles.screen}>
      <View style={styles.content}>
        <ThemedText type="subtitle">{mode === 'sign-in' ? 'Sign in' : 'Create account'}</ThemedText>

        {mode === 'sign-up' ? (
          <Field
            label="Username"
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
            placeholder="what the leaderboard shows"
          />
        ) : null}

        <Field
          label="Email"
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="you@example.com"
        />

        <Field
          label="Password"
          value={password}
          onChangeText={setPassword}
          autoCapitalize="none"
          secureTextEntry
          placeholder="at least 6 characters"
        />

        {error ? (
          <ThemedText type="small" style={styles.error}>
            {error}
          </ThemedText>
        ) : null}
        {message ? (
          <ThemedText type="small" themeColor="textSecondary">
            {message}
          </ThemedText>
        ) : null}

        <Pressable onPress={submit} disabled={busy} accessibilityRole="button">
          <ThemedView type="backgroundSelected" style={styles.button}>
            {busy ? (
              <ActivityIndicator />
            ) : (
              <ThemedText type="smallBold">
                {mode === 'sign-in' ? 'Sign in' : 'Create account'}
              </ThemedText>
            )}
          </ThemedView>
        </Pressable>

        <Pressable
          onPress={() => {
            setMode(mode === 'sign-in' ? 'sign-up' : 'sign-in');
            setError(null);
            setMessage(null);
          }}
          accessibilityRole="button">
          <ThemedText type="linkPrimary">
            {mode === 'sign-in' ? 'Need an account? Sign up' : 'Already have an account? Sign in'}
          </ThemedText>
        </Pressable>
      </View>
    </ThemedView>
  );
}

function Field({
  label,
  ...props
}: { label: string } & React.ComponentProps<typeof TextInput>) {
  // TextInput doesn't inherit colour from ThemedText, so it has to read the
  // theme itself or the text is invisible in one of the two schemes.
  const theme = useTheme();

  return (
    <View style={styles.field}>
      <ThemedText type="small" themeColor="textSecondary">
        {label}
      </ThemedText>
      <ThemedView type="backgroundElement" style={styles.inputWrapper}>
        <TextInput
          style={[styles.input, { color: theme.text }]}
          placeholderTextColor={theme.textSecondary}
          {...props}
        />
      </ThemedView>
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
  field: {
    gap: Spacing.one,
  },
  inputWrapper: {
    borderRadius: Spacing.two,
    paddingHorizontal: Spacing.three,
  },
  input: {
    paddingVertical: Spacing.three,
    fontSize: 16,
  },
  button: {
    paddingVertical: Spacing.three,
    borderRadius: Spacing.two,
    alignItems: 'center',
  },
  error: {
    color: '#ef4444',
  },
});

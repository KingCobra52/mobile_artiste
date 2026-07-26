import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient } from '@supabase/supabase-js';

/**
 * Supabase client, used only for authentication.
 *
 * Reading and writing app data goes through the FastAPI backend, never through
 * this client directly. Row Level Security enforces that: the publishable key
 * below is shipped inside the app bundle and is therefore public, so the database
 * grants it read access to market data and to the signed-in user's own rows, and
 * no write access at all. Balances and holdings can only change via the API,
 * which connects as the table owner.
 */
const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!supabaseUrl || !supabaseKey) {
  throw new Error(
    'Missing EXPO_PUBLIC_SUPABASE_URL or EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY. ' +
      'Copy .env.example to .env.'
  );
}

export const supabase = createClient(supabaseUrl, supabaseKey, {
  auth: {
    // AsyncStorage keeps the session across app restarts; without it the user is
    // signed out every cold start.
    storage: AsyncStorage,
    autoRefreshToken: true,
    persistSession: true,
    // Only meaningful on web, where Supabase parses the callback URL fragment
    detectSessionInUrl: false,
  },
});

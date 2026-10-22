import type { SupabaseClient } from '@supabase/supabase-js';

export type AuthStartup = {
  status: 'checking' | 'ready' | 'error';
  email: string;
  message: string;
};
type AuthClient = Pick<SupabaseClient['auth'], 'initialize' | 'getSession'>;

export const checkingAuth: AuthStartup = { status: 'checking', email: '', message: '' };

/** Inspect only parameter names. Never retain or display callback credentials. */
export function isAuthCallback(href: string): boolean {
  const url = new URL(href);
  if (url.pathname.replace(/\/$/, '') === '/auth/callback') return true;
  const parameters = [url.searchParams, ...url.hash.slice(1).split('#').map(fragment => new URLSearchParams(fragment))];
  return parameters.some(params => ['access_token', 'code', 'error', 'error_code', 'error_description'].some(key => params.has(key)));
}

export function signInRedirect(origin: string): string {
  return new URL('/auth/callback', origin).href;
}

export function authNavigationBlocked(state: AuthStartup, callback: boolean): boolean {
  return callback && state.status === 'checking';
}

const knownErrorCodes = new Set(['otp_expired', 'access_denied', 'bad_code_verifier', 'flow_state_expired', 'flow_state_not_found', 'validation_failed']);
function failure(error: unknown): AuthStartup {
  const code = error && typeof error === 'object' && 'code' in error ? error.code : undefined;
  const detail = typeof code === 'string' && knownErrorCodes.has(code) ? ` (${code})` : '';
  return {
    status: 'error', email: '',
    message: `We couldn’t complete this sign-in${detail}. Return to the library to request a new link when you’re ready.`,
  };
}

/** The eager singleton already starts initialize(); calling it again awaits that same run. */
export async function initializeAuth(auth: AuthClient | null, callback: boolean): Promise<AuthStartup> {
  if (!auth) return callback
    ? { status: 'error', email: '', message: 'Cloud sign-in is not configured for this deployment. Your local proofs are still available.' }
    : { status: 'ready', email: '', message: '' };
  try {
    const initialized = await auth.initialize();
    if (initialized.error) return failure(initialized.error);
    const { data, error } = await auth.getSession();
    if (error) return failure(error);
    const email = data.session?.user.email || '';
    if (callback && !email) return {
      status: 'error', email: '',
      message: 'This link did not sign you in. Your local proofs are safe. Return to the library to request a new link when you’re ready.',
    };
    return { status: 'ready', email, message: '' };
  } catch (error) {
    return failure(error);
  }
}

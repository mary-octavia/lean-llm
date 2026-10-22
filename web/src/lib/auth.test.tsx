import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import AuthCallback from '../components/AuthCallback';
import { authNavigationBlocked, checkingAuth, initializeAuth, isAuthCallback, signInRedirect } from './auth';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(finish => { resolve = finish; });
  return { promise, resolve };
}
function client() {
  return {
    initialize: vi.fn().mockResolvedValue({ error: null }),
    getSession: vi.fn().mockResolvedValue({ data: { session: null }, error: null }),
  };
}

describe('sign-in callback startup', () => {
  it('waits for initialization and session restoration before releasing callback navigation', async () => {
    const auth = client();
    const initialization = deferred<{ error: null }>();
    const restored = deferred<{ data: { session: { user: { email: string } } }; error: null }>();
    auth.initialize.mockReturnValue(initialization.promise);
    auth.getSession.mockReturnValue(restored.promise);
    let state = checkingAuth;
    const ready = initializeAuth(auth, true).then(result => { state = result; });
    expect(auth.getSession).not.toHaveBeenCalled();
    expect(authNavigationBlocked(state, true)).toBe(true);
    initialization.resolve({ error: null });
    await initialization.promise;
    expect(auth.getSession).toHaveBeenCalledOnce();
    expect(authNavigationBlocked(state, true)).toBe(true);
    restored.resolve({ data: { session: { user: { email: 'researcher@example.org' } } }, error: null });
    await ready;
    expect(state).toEqual({ status: 'ready', email: 'researcher@example.org', message: '' });
    expect(authNavigationBlocked(state, true)).toBe(false);
  });

  it('preserves initialization failures as safe errors without reading a session', async () => {
    const auth = client();
    auth.initialize.mockResolvedValue({ error: { code: 'otp_expired', message: 'https://private.invalid/#access_token=secret' } });
    const result = await initializeAuth(auth, true);
    expect(result.status).toBe('error');
    expect(result.message).toContain('otp_expired');
    expect(JSON.stringify(result)).not.toMatch(/secret|private\.invalid|access_token/);
    expect(auth.getSession).not.toHaveBeenCalled();
    expect(authNavigationBlocked(result, true)).toBe(false);
  });

  it('shows a safe persistent failure when reading the session fails', async () => {
    const auth = client();
    auth.getSession.mockResolvedValue({ data: { session: null }, error: new Error('private token value') });
    const result = await initializeAuth(auth, true);
    expect(result.status).toBe('error');
    expect(result.message).not.toContain('private token');
    expect(result.message).toContain('Return to the library');
  });

  it('handles thrown SDK failures without exposing their contents', async () => {
    const auth = client();
    auth.initialize.mockRejectedValue(new Error('refresh_token=private'));
    const result = await initializeAuth(auth, true);
    expect(result.status).toBe('error');
    expect(result.message).not.toContain('refresh_token');
  });

  it('distinguishes a callback with no restored account from a successful sign-in', async () => {
    const result = await initializeAuth(client(), true);
    expect(result.status).toBe('error');
    expect(result.message).toContain('This link did not sign you in');
    expect(result.email).toBe('');
  });

  it('allows normal signed-out browsing without treating it as a failed callback', async () => {
    expect(await initializeAuth(client(), false)).toEqual({ status: 'ready', email: '', message: '' });
    expect(authNavigationBlocked(checkingAuth, false)).toBe(false);
  });

  it('explains an unconfigured callback while preserving ordinary local browsing', async () => {
    expect((await initializeAuth(null, true)).status).toBe('error');
    expect((await initializeAuth(null, false)).status).toBe('ready');
  });

  it('recognizes dedicated, implicit, error and legacy nested-hash callbacks', () => {
    expect(isAuthCallback('https://example.org/auth/callback')).toBe(true);
    expect(isAuthCallback('https://example.org/#access_token=placeholder&refresh_token=placeholder')).toBe(true);
    expect(isAuthCallback('https://example.org/#library#access_token=placeholder&refresh_token=placeholder')).toBe(true);
    expect(isAuthCallback('https://example.org/?code=placeholder')).toBe(true);
    expect(isAuthCallback('https://example.org/#error_code=otp_expired')).toBe(true);
    expect(isAuthCallback('https://example.org/#library')).toBe(false);
  });

  it('keeps new email redirects separate from fragment-based app navigation', () => {
    const redirect = new URL(signInRedirect('https://example.org'));
    expect(redirect.pathname).toBe('/auth/callback');
    expect(redirect.hash).toBe('');
    expect(redirect.search).toBe('');
  });

  it('renders progress and a persistent accessible failure with a return action', () => {
    const waiting = renderToStaticMarkup(<AuthCallback state={checkingAuth} onReturn={() => {}} />);
    expect(waiting).toContain('Finishing sign-in');
    expect(waiting).toContain('role="status"');
    expect(waiting).not.toContain('<button');
    const failed = renderToStaticMarkup(<AuthCallback state={{ status: 'error', email: '', message: 'This link did not sign you in.' }} onReturn={() => {}} />);
    expect(failed).toContain('role="alert"');
    expect(failed).toContain('Return to proof library');
    expect(failed).toContain('This link did not sign you in.');
  });
});

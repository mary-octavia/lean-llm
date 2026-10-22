import { LoaderCircle, LockKeyhole } from 'lucide-react';
import type { AuthStartup } from '../lib/auth';

export default function AuthCallback({ state, onReturn }: { state: AuthStartup; onReturn: () => void }) {
  const checking = state.status === 'checking';
  return <section className="shell inner-page auth-callback" aria-labelledby="auth-callback-title">
    <div className="eyebrow">PRIVATE PROOF LIBRARY</div>
    <div className="auth-callback-card">
      {checking ? <LoaderCircle className="spin" size={26} aria-hidden="true" /> : <LockKeyhole size={26} aria-hidden="true" />}
      <h1 id="auth-callback-title">{checking ? 'Finishing sign-in…' : 'Let’s finish signing in.'}</h1>
      {checking
        ? <p role="status">Checking your email link. Please keep this page open.</p>
        : <><p role="alert">{state.message}</p><button className="button secondary" onClick={onReturn}>Return to proof library</button></>}
    </div>
  </section>;
}

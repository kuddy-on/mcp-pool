import { useState } from 'react';
import { Layers } from 'lucide-react';

import { Button } from '../common/Button';

interface Props {
  t: Record<string, string>;
  error: string;
  onLogin: (username: string, password: string) => Promise<boolean>;
}

export function LoginScreen({ t, error, onLogin }: Props) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  return (
    <main className="login-page">
      <form className="login-panel" onSubmit={async (event) => {
        event.preventDefault();
        setSubmitting(true);
        await onLogin(username, password);
        setSubmitting(false);
      }}>
        <div className="brand-mark brand-mark--large"><Layers size={24} /></div>
        <h1>{t.loginTitle}</h1>
        {error ? <div className="form-error" role="alert">{error}</div> : null}
        <label className="field"><span>{t.labelUsername}</span><input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label>
        <label className="field"><span>{t.labelPassword}</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
        <Button type="submit" variant="primary" disabled={submitting}>{submitting ? t.testing : t.btnLogin}</Button>
      </form>
    </main>
  );
}

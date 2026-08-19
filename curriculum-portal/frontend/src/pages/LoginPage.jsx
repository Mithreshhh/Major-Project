import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { apiRequest } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import { DEMO_ACCOUNTS } from '../demoAccounts.js';
import './AuthPage.css';

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingDemo, setLoadingDemo] = useState(null);
  const [error, setError] = useState(null);

  const performLogin = async (loginEmail, loginPassword) => {
    setError(null);
    try {
      const data = await apiRequest('/auth/login', {
        method: 'POST',
        body: { email: loginEmail, password: loginPassword },
      });
      login(data.token, data.user);
      navigate('/');
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    await performLogin(email, password);
    setIsLoading(false);
  };

  const handleDemoLogin = async (account) => {
    setLoadingDemo(account.email);
    setEmail(account.email);
    setPassword(account.password);
    await performLogin(account.email, account.password);
    setLoadingDemo(null);
  };

  const isBusy = isLoading || Boolean(loadingDemo);

  return (
    <div className="auth-page">
      <div className="auth-card glass-panel">
        <div className="auth-card__header">
          <span className="eyebrow">Welcome back</span>
          <h1 className="auth-card__title">Log in to your institute</h1>
          <p className="auth-card__subtitle">
            Access your syllabus reports and job-market gap analysis dashboard.
          </p>
        </div>

        {error && <p className="banner banner--error">{error}</p>}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              className="input"
              placeholder="admin@yourcollege.edu"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isBusy}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isBusy}
              required
            />
          </div>

          <button type="submit" className="btn btn--primary btn--full" disabled={isBusy}>
            {isLoading ? (
              <>
                <span className="spinner" /> Logging in…
              </>
            ) : (
              'Log in'
            )}
          </button>
        </form>

        <div className="auth-divider">Quick demo login</div>

        <div className="demo-accounts">
          {DEMO_ACCOUNTS.map((account) => (
            <button
              key={account.email}
              type="button"
              className="demo-account"
              onClick={() => handleDemoLogin(account)}
              disabled={isBusy}
            >
              <span className="demo-account__info">
                <span className="demo-account__name">{account.instituteName}</span>
                <span className="demo-account__email">{account.email}</span>
              </span>
              <span className="demo-account__go">
                {loadingDemo === account.email ? <span className="spinner spinner--light" /> : '→'}
              </span>
            </button>
          ))}
        </div>
        <p className="auth-card__footer" style={{ marginTop: '0.85rem', fontSize: '0.78rem' }}>
          Demo accounts require the backend seed script (<code>npm run seed</code> in /backend).
        </p>

        <div className="auth-card__footer">
          Don&apos;t have an account? <Link to="/signup">Sign up</Link>
        </div>
      </div>
    </div>
  );
}

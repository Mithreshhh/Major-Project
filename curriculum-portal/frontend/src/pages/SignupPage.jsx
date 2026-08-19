import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { apiRequest } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import './AuthPage.css';

const MIN_PASSWORD_LENGTH = 8;

export default function SignupPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [instituteName, setInstituteName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (!instituteName.trim()) {
      setError('Institute name is required');
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`);
      return;
    }

    setIsLoading(true);
    try {
      const data = await apiRequest('/auth/signup', {
        method: 'POST',
        body: { email, password, instituteName },
      });
      login(data.token, data.user);
      navigate('/');
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card glass-panel">
        <div className="auth-card__header">
          <span className="eyebrow">Get started</span>
          <h1 className="auth-card__title">Create your institute account</h1>
          <p className="auth-card__subtitle">
            Set up your institute once, then upload syllabi to see how they measure up.
          </p>
        </div>

        {error && <p className="banner banner--error">{error}</p>}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="instituteName">Institute name</label>
            <input
              id="instituteName"
              type="text"
              className="input"
              placeholder="Springfield Institute of Technology"
              value={instituteName}
              onChange={(e) => setInstituteName(e.target.value)}
              disabled={isLoading}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              className="input"
              placeholder="admin@yourcollege.edu"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
              required
            />
          </div>

          <button type="submit" className="btn btn--primary btn--full" disabled={isLoading}>
            {isLoading ? (
              <>
                <span className="spinner" /> Creating account…
              </>
            ) : (
              'Create account'
            )}
          </button>
        </form>

        <div className="auth-card__footer">
          Already have an account? <Link to="/login">Log in</Link>
        </div>
      </div>
    </div>
  );
}

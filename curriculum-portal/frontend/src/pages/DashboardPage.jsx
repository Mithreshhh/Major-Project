import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { apiRequest } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import './DashboardPage.css';

function scoreTone(gapScore) {
  const value = Number(gapScore);
  if (value <= 33) return 'tone-good';
  if (value <= 66) return 'tone-mid';
  return 'tone-bad';
}

export default function DashboardPage() {
  const { token } = useAuth();
  const navigate = useNavigate();

  const [reports, setReports] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    apiRequest('/reports', { token })
      .then((data) => {
        if (!cancelled) {
          setReports(data.reports || []);
          setStatus('ready');
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message);
          setStatus('error');
        }
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="page">
      <div className="dashboard-header">
        <div>
          <span className="eyebrow">Your institute</span>
          <h1 className="page-title">Report Dashboard</h1>
          <p className="page-subtitle">All past syllabus submissions and their gap analysis scores.</p>
        </div>
        <Link to="/" className="btn btn--primary">
          + Upload syllabus
        </Link>
      </div>

      {status === 'loading' && (
        <p className="banner banner--info" style={{ marginTop: '2rem' }}>
          <span className="spinner spinner--light" /> Loading reports…
        </p>
      )}

      {status === 'error' && (
        <p className="banner banner--error" style={{ marginTop: '2rem' }}>
          {error}
        </p>
      )}

      {status === 'ready' && reports.length === 0 && (
        <div className="glass-panel empty-state">
          <p className="empty-state__title">No submissions yet</p>
          <p className="empty-state__hint">Upload your first syllabus to see it appear here.</p>
          <Link to="/" className="btn btn--primary" style={{ marginTop: '1.25rem' }}>
            Upload a syllabus
          </Link>
        </div>
      )}

      {status === 'ready' && reports.length > 0 && (
        <div className="report-grid">
          {reports.map((report) => (
            <button
              key={report.reportId}
              type="button"
              className={`glass-panel glass-panel--interactive report-card ${scoreTone(report.gapScore)}`}
              onClick={() => navigate(`/report/${report.reportId}`)}
            >
              <div className="report-card__top">
                <span className="report-card__filename">{report.filename}</span>
                <span className="report-card__score">{Math.round(Number(report.gapScore))}%</span>
              </div>
              <div className="report-card__bar">
                <div
                  className="report-card__bar-fill"
                  style={{ width: `${Math.max(0, Math.min(100, Number(report.gapScore)))}%` }}
                />
              </div>
              <div className="report-card__meta">
                <span>Gap score</span>
                <span>
                  {report.createdAt
                    ? new Date(report.createdAt).toLocaleDateString(undefined, {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                      })
                    : '—'}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

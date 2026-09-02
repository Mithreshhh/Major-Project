import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { apiRequest } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import GapScoreGauge from '../components/GapScoreGauge.jsx';
import './ReportPage.css';

export default function ReportPage() {
  const { id } = useParams();
  const { token } = useAuth();

  const [report, setReport] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    setStatus('loading');
    setError(null);

    apiRequest(`/report/${id}`, { token })
      .then((data) => {
        if (!cancelled) {
          setReport(data);
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
  }, [id, token]);

  if (status === 'loading') {
    return (
      <div className="page">
        <p className="banner banner--info">
          <span className="spinner spinner--light" /> Loading report…
        </p>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="page">
        <p className="banner banner--error">{error}</p>
        <Link to="/dashboard" className="btn btn--ghost" style={{ marginTop: '1.25rem' }}>
          ← Back to dashboard
        </Link>
      </div>
    );
  }

  const matchedSkills = report.matchedSkills || [];
  const missingSkills = report.missingSkills || [];
  const createdAt = report.createdAt ? new Date(report.createdAt) : null;

  return (
    <div className="page">
      <span className="eyebrow">Gap analysis report</span>
      <h1 className="page-title page-title--file">{report.filename}</h1>
      <p className="page-subtitle">
        {createdAt
          ? `Analyzed ${createdAt.toLocaleDateString(undefined, {
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })} at ${createdAt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`
          : 'Analysis complete'}
      </p>

      <div className="scores-row">
        <div className="glass-panel score-card">
          <GapScoreGauge score={report.gapScore} label="Gap Score" />
          <p className="score-card__caption">
            Share of job-market skills this syllabus doesn&apos;t cover. Lower is better.
          </p>
        </div>

        <div className="glass-panel score-card">
          <GapScoreGauge score={report.nepScore} label="NEP Score" invert />
          <p className="score-card__caption">
            Share of NEP 2020 competencies the syllabus covers. Higher is better.
          </p>
        </div>
      </div>

      <div className="skills-grid">
        <section className="glass-panel skills-panel">
          <h2 className="skills-panel__title skills-panel__title--matched">
            Matched <span className="skills-panel__count">{matchedSkills.length}</span>
          </h2>
          {matchedSkills.length > 0 ? (
            <div className="tag-cloud">
              {matchedSkills.map((skill) => (
                <span key={skill} className="tag tag--success">
                  ✓ {skill}
                </span>
              ))}
            </div>
          ) : (
            <p className="skills-panel__empty">Nothing in this syllabus matched the job-market skill set.</p>
          )}
        </section>

        <section className="glass-panel skills-panel">
          <h2 className="skills-panel__title skills-panel__title--missing">
            Missing <span className="skills-panel__count">{missingSkills.length}</span>
          </h2>
          {missingSkills.length > 0 ? (
            <div className="tag-cloud">
              {missingSkills.map((skill) => (
                <span key={skill} className="tag tag--danger">
                  ✕ {skill}
                </span>
              ))}
            </div>
          ) : (
            <p className="skills-panel__empty">No gaps — this syllabus covers the full job-market skill set.</p>
          )}
        </section>
      </div>

      <Link to="/dashboard" className="btn btn--ghost" style={{ marginTop: '2rem' }}>
        ← Back to dashboard
      </Link>
    </div>
  );
}

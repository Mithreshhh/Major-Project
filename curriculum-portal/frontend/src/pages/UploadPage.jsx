import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { apiRequest } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import './UploadPage.css';

const ACCEPTED_EXTENSIONS = ['.pdf', '.docx'];

/** Band a 0-100 score. `higherIsBetter` flips it for NEP alignment. */
function scoreTone(value, higherIsBetter) {
  if (value === null || value === undefined) return 'tone-none';
  const goodness = higherIsBetter ? Number(value) : 100 - Number(value);
  if (goodness >= 66) return 'tone-good';
  if (goodness >= 33) return 'tone-mid';
  return 'tone-bad';
}

function isAcceptedFile(file) {
  const name = file?.name?.toLowerCase() || '';
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

export default function UploadPage() {
  const { token } = useAuth();
  const fileInputRef = useRef(null);

  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [status, setStatus] = useState('idle'); // idle | loading | success | error
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const resetForNewFile = () => {
    setResult(null);
    setError(null);
    setStatus('idle');
  };

  const handleFileSelected = (selected) => {
    if (!selected) return;
    if (!isAcceptedFile(selected)) {
      setError('Only .pdf and .docx files are supported.');
      setFile(null);
      return;
    }
    setFile(selected);
    resetForNewFile();
  };

  const handleInputChange = (e) => handleFileSelected(e.target.files?.[0] || null);

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    handleFileSelected(e.dataTransfer.files?.[0] || null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) return;

    setStatus('loading');
    setError(null);
    setResult(null);

    const formData = new FormData();
    formData.append('syllabus', file);

    try {
      const data = await apiRequest('/upload', { method: 'POST', body: formData, token, isFormData: true });
      setResult(data);
      setStatus('success');
    } catch (err) {
      setError(err.message);
      setStatus('error');
    }
  };

  const isLoading = status === 'loading';

  return (
    <div className="page">
      <span className="eyebrow">Syllabus intake</span>
      <h1 className="page-title">
        Measure a syllabus against
        <br />
        the market it graduates into.
      </h1>
      <p className="page-subtitle">
        Drop in a course syllabus. We extract every skill it teaches, score that against live
        job-market demand, and check it for NEP 2020 alignment — in about a minute.
      </p>

      <form
        className={`dropzone glass-panel${isDragging ? ' dropzone--active' : ''}${file ? ' dropzone--filled' : ''}`}
        onSubmit={handleSubmit}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          type="file"
          name="syllabus"
          accept={ACCEPTED_EXTENSIONS.join(',')}
          onChange={handleInputChange}
          disabled={isLoading}
          hidden
        />

        <div
          className="dropzone__hitbox"
          onClick={() => !isLoading && fileInputRef.current?.click()}
        >
          {/* Hairline SVG rather than an emoji: emoji render in the OS's
              own colour and weight, which breaks a monochrome interface. */}
          <div className="dropzone__icon" aria-hidden="true">
            {file ? (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.25">
                <path d="M11.5 2.5H5.5a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V6.5l-4-4Z" />
                <path d="M11.5 2.5v4h4" />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.25">
                <path d="M10 13.5V3.5" />
                <path d="m6 7.5 4-4 4 4" />
                <path d="M3.5 13.5v2a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-2" />
              </svg>
            )}
          </div>

          {file ? (
            <>
              <p className="dropzone__filename">{file.name}</p>
              <p className="dropzone__hint">{(file.size / 1024).toFixed(0)} KB · ready to analyze</p>
            </>
          ) : (
            <>
              <p className="dropzone__title">Drop your syllabus here</p>
              <p className="dropzone__hint">or click to browse · PDF or DOCX · up to 10 MB</p>
            </>
          )}
        </div>

        <div className="dropzone__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
          >
            {file ? 'Choose a different file' : 'Browse files'}
          </button>
          <button type="submit" className="btn btn--primary" disabled={!file || isLoading}>
            {isLoading ? (
              <>
                <span className="spinner" /> Analyzing…
              </>
            ) : (
              'Upload & Analyze'
            )}
          </button>
        </div>
      </form>

      {error && <p className="banner banner--error" style={{ marginTop: '1.25rem' }}>{error}</p>}

      {isLoading && (
        <p className="banner banner--info" style={{ marginTop: '1.25rem' }}>
          <span className="spinner spinner--light" /> Extracting skills, embedding them, and matching
          against job-market and NEP reference data…
        </p>
      )}

      {result && (
        <>
          <div className="banner banner--success upload-success" style={{ marginTop: '1.5rem' }}>
            <div>
              <strong>Analysis complete.</strong> {result.filename || 'Your syllabus'} has been scored
              against job-market demand and NEP competencies.
            </div>
            <Link to={`/report/${result.reportId}`} className="btn btn--primary btn--sm">
              View full report →
            </Link>
          </div>

          <div className="upload-metrics">
            {[
              {
                label: 'Gap score',
                value: result.gapScore,
                // Lower gap is better, so goodness is inverted.
                tone: scoreTone(result.gapScore, false),
                suffix: '%',
              },
              {
                label: 'NEP alignment',
                value: result.nepScore,
                tone: scoreTone(result.nepScore, true),
                suffix: '%',
              },
              { label: 'Skills matched', value: result.matchedSkills?.length, tone: 'tone-none' },
              { label: 'Skills missing', value: result.missingSkills?.length, tone: 'tone-none' },
            ].map((metric) => (
              <div key={metric.label} className="upload-metric">
                <span className="upload-metric__label">{metric.label}</span>
                <span className={`upload-metric__value ${metric.tone}`}>
                  {/* null is "not scored", not zero — see nepScoreUnavailable
                      in the upload response. */}
                  {metric.value === null || metric.value === undefined
                    ? '—'
                    : `${Math.round(Number(metric.value))}${metric.suffix || ''}`}
                </span>
              </div>
            ))}
          </div>

          {result.nepScoreUnavailable && (
            <p className="upload-note">{result.nepScoreUnavailable}</p>
          )}
        </>
      )}
    </div>
  );
}

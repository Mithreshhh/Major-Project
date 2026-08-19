import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { apiRequest } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import './UploadPage.css';

const ACCEPTED_EXTENSIONS = ['.pdf', '.docx'];

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
      <h1 className="page-title">Upload a syllabus</h1>
      <p className="page-subtitle">
        Drop in a course syllabus (.pdf or .docx) and we&apos;ll extract its skills, score its
        coverage of job-market demand, and check it against NEP competencies.
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
          <div className="dropzone__icon" aria-hidden="true">
            {file ? '📄' : '⇪'}
          </div>

          {file ? (
            <>
              <p className="dropzone__filename">{file.name}</p>
              <p className="dropzone__hint">{(file.size / 1024).toFixed(0)} KB — ready to analyze</p>
            </>
          ) : (
            <>
              <p className="dropzone__title">Drag &amp; drop your syllabus here</p>
              <p className="dropzone__hint">or click to browse — PDF or DOCX, up to 10MB</p>
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
          <span className="spinner spinner--light" /> Extracting skills and matching against job-market
          and NEP data…
        </p>
      )}

      {result && (
        <div className="banner banner--success upload-success" style={{ marginTop: '1.25rem' }}>
          <div>
            <strong>Analysis complete.</strong> Gap score:{' '}
            <span className="upload-success__score">{result.gapScore}%</span>
            {' · '}NEP score: <span className="upload-success__score">{result.nepScore}%</span>
          </div>
          <Link to={`/report/${result.reportId}`} className="btn btn--primary btn--sm">
            View full report →
          </Link>
        </div>
      )}
    </div>
  );
}

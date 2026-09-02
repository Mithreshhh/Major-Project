import { useEffect, useMemo, useState } from 'react';

import { apiRequest } from '../api/client.js';
import { useAuth } from '../context/AuthContext.jsx';
import './ComparePage.css';

/**
 * Columns are declared as data rather than hand-written <th> markup so the
 * header row, the sort handlers, and the cell renderers can't drift apart as
 * columns are added.
 *
 * `higherIsBetter` drives both the colour banding and the default sort
 * direction: clicking "Gap score" should surface the worst performers first,
 * while clicking "NEP score" should surface the best.
 */
const COLUMNS = [
  { key: 'name', label: 'Institute', numeric: false },
  { key: 'gapScore', label: 'Gap score', numeric: true, higherIsBetter: false, suffix: '%' },
  { key: 'nepScore', label: 'NEP score', numeric: true, higherIsBetter: true, suffix: '%' },
  { key: 'reportCount', label: 'Reports', numeric: true },
  { key: 'lastAnalyzedAt', label: 'Last analyzed', numeric: false },
];

function scoreTone(value, higherIsBetter) {
  if (value === null || value === undefined) return 'tone-none';
  const goodness = higherIsBetter ? value : 100 - value;
  if (goodness >= 66) return 'tone-good';
  if (goodness >= 33) return 'tone-mid';
  return 'tone-bad';
}

function formatScore(value, suffix = '') {
  if (value === null || value === undefined) return '—';
  return `${Math.round(Number(value))}${suffix}`;
}

function formatDate(value) {
  if (!value) return '—';
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export default function ComparePage() {
  const { token } = useAuth();

  const [data, setData] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [error, setError] = useState(null);
  const [sortBy, setSortBy] = useState('gapScore');
  const [order, setOrder] = useState('asc');

  useEffect(() => {
    let cancelled = false;

    apiRequest('/compare', { token })
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
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

  // Sorted locally rather than by re-fetching: the dataset is one row per
  // institute, so a round trip per header click would be latency for nothing.
  // The endpoint still sorts server-side, so the API is correct on its own.
  const institutes = useMemo(() => {
    const rows = [...(data?.institutes || [])];
    const column = COLUMNS.find((c) => c.key === sortBy);
    const direction = order === 'desc' ? -1 : 1;

    rows.sort((a, b) => {
      const left = a[sortBy];
      const right = b[sortBy];
      // Unscored institutes sink to the bottom either way — treating null as
      // 0 would rank one as having a perfect gap score.
      if (left === null || left === undefined) return 1;
      if (right === null || right === undefined) return -1;
      if (!column?.numeric) return String(left).localeCompare(String(right)) * direction;
      return (left - right) * direction;
    });
    return rows;
  }, [data, sortBy, order]);

  const handleSort = (column) => {
    if (sortBy === column.key) {
      setOrder((current) => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortBy(column.key);
    // Open each column on its most useful end: worst gap first, best NEP
    // first, A-Z for names.
    setOrder(column.numeric && column.higherIsBetter ? 'desc' : 'asc');
  };

  const maxReports = Math.max(1, ...institutes.map((i) => i.reportCount || 0));

  return (
    <div className="page">
      <div className="compare-header">
        <div>
          <span className="eyebrow">Benchmarking</span>
          <h1 className="page-title">Institute Comparison</h1>
          <p className="page-subtitle">
            Latest gap and NEP alignment scores across institutes. Lower gap is better; higher NEP is
            better.
          </p>
        </div>
      </div>

      {status === 'loading' && (
        <p className="banner banner--info" style={{ marginTop: '2rem' }}>
          <span className="spinner spinner--light" /> Loading comparison…
        </p>
      )}

      {status === 'error' && (
        <p className="banner banner--error" style={{ marginTop: '2rem' }}>
          {error}
        </p>
      )}

      {status === 'ready' && data?.source === 'mock' && (
        <p className="banner banner--info compare-mock-banner">
          <strong>Sample data.</strong> These institutes are placeholders, not live results — the
          backend is serving mock data while the database is offline.
        </p>
      )}

      {status === 'ready' && institutes.length === 0 && (
        <div className="glass-panel empty-state">
          <p className="empty-state__title">Nothing to compare yet</p>
          <p className="empty-state__hint">
            Institutes appear here once they have at least one analyzed syllabus.
          </p>
        </div>
      )}

      {status === 'ready' && institutes.length > 0 && (
        <>
          <section className="glass-panel compare-chart" aria-label="Score comparison chart">
            {/* Bars are coloured by how good the score is, not by which metric
                it is - the same encoding the report gauges and table pills
                use. Each bar is therefore labelled, rather than relying on a
                colour key, which would contradict the colours on screen. */}
            <p className="compare-chart__note">
              Bar colour shows performance, not metric —{' '}
              <span className="compare-chart__swatch tone-good" /> on track,{' '}
              <span className="compare-chart__swatch tone-mid" /> mixed,{' '}
              <span className="compare-chart__swatch tone-bad" /> needs attention.
            </p>

            {institutes.map((institute) => (
              <div key={institute.instituteId} className="compare-chart__row">
                <span className="compare-chart__name" title={institute.name}>
                  {institute.name}
                </span>

                <div className="compare-chart__bars">
                  {[
                    { label: 'Gap', value: institute.gapScore, higherIsBetter: false },
                    { label: 'NEP', value: institute.nepScore, higherIsBetter: true },
                  ].map((metric) => (
                    <div key={metric.label} className="compare-chart__metric">
                      <span className="compare-chart__metric-label">{metric.label}</span>
                      <div className="compare-chart__track">
                        <div
                          className={`compare-chart__bar ${scoreTone(
                            metric.value,
                            metric.higherIsBetter
                          )}`}
                          style={{ width: `${Math.max(0, Math.min(100, metric.value ?? 0))}%` }}
                        />
                      </div>
                      <span className="compare-chart__value">{formatScore(metric.value, '%')}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>

          <div className="glass-panel compare-table-wrap">
            <table className="compare-table">
              <caption className="compare-table__caption">
                {institutes.length} institute{institutes.length === 1 ? '' : 's'} — click a column to
                sort
              </caption>
              <thead>
                <tr>
                  {COLUMNS.map((column) => {
                    const active = sortBy === column.key;
                    return (
                      <th
                        key={column.key}
                        scope="col"
                        className={column.numeric ? 'is-numeric' : undefined}
                        aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}
                      >
                        <button
                          type="button"
                          className={`compare-table__sort${active ? ' is-active' : ''}`}
                          onClick={() => handleSort(column)}
                        >
                          {column.label}
                          <span className="compare-table__arrow" aria-hidden="true">
                            {active ? (order === 'asc' ? '▲' : '▼') : '↕'}
                          </span>
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {institutes.map((institute) => (
                  <tr key={institute.instituteId}>
                    <td>
                      <span className="compare-table__name">{institute.name}</span>
                      {institute.location && (
                        <span className="compare-table__sub">{institute.location}</span>
                      )}
                    </td>
                    <td className="is-numeric">
                      <span className={`compare-pill ${scoreTone(institute.gapScore, false)}`}>
                        {formatScore(institute.gapScore, '%')}
                      </span>
                    </td>
                    <td className="is-numeric">
                      <span className={`compare-pill ${scoreTone(institute.nepScore, true)}`}>
                        {formatScore(institute.nepScore, '%')}
                      </span>
                    </td>
                    <td className="is-numeric">
                      <div className="compare-table__count">
                        <span>{institute.reportCount}</span>
                        <span
                          className="compare-table__count-bar"
                          style={{ width: `${(institute.reportCount / maxReports) * 100}%` }}
                        />
                      </div>
                    </td>
                    <td>{formatDate(institute.lastAnalyzedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

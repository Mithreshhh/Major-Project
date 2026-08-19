import { useEffect, useState } from 'react';
import './GapScoreGauge.css';

/**
 * Circular progress gauge for a 0-100 score.
 *
 * By default a higher score is worse (gap score: % of job-market skills
 * missing from the syllabus), so color runs green -> amber -> red as the
 * value climbs. Pass `invert` for scores where higher is better (NEP score).
 */
export default function GapScoreGauge({ score, size = 168, strokeWidth = 12, label = 'Gap Score', invert = false }) {
  const clamped = Math.max(0, Math.min(100, Number(score) || 0));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  const [animatedOffset, setAnimatedOffset] = useState(circumference);

  useEffect(() => {
    const targetOffset = circumference - (clamped / 100) * circumference;
    const frame = requestAnimationFrame(() => setAnimatedOffset(targetOffset));
    return () => cancelAnimationFrame(frame);
  }, [circumference, clamped]);

  const goodness = invert ? clamped : 100 - clamped;
  const color = goodness >= 66 ? 'var(--color-success)' : goodness >= 33 ? 'var(--color-warning)' : 'var(--color-danger)';

  return (
    <div className="gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle className="gauge__track" cx={size / 2} cy={size / 2} r={radius} strokeWidth={strokeWidth} fill="none" />
        <circle
          className="gauge__fill"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={strokeWidth}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={animatedOffset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ stroke: color, color }}
        />
      </svg>
      <div className="gauge__center">
        <span className="gauge__value">{Math.round(clamped)}%</span>
        <span className="gauge__label">{label}</span>
      </div>
    </div>
  );
}

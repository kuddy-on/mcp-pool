import React from 'react';
import { CheckCircle, XCircle } from 'lucide-react';

export interface StatusBadgeProps {
  status: 'active' | 'degraded' | 'exhausted' | 'paused' | string;
  labels?: {
    active?: string;
    exhausted?: string;
    paused?: string;
    degraded?: string;
  };
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, labels = {} }) => {
  const badgeStyles: Record<string, React.CSSProperties> = {
    active: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '4px',
      color: '#15803d',
      fontWeight: 600,
      fontSize: '12px',
    },
    exhausted: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '4px',
      color: '#b91c1c',
      fontWeight: 600,
      fontSize: '12px',
    },
    paused: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '4px',
      color: '#d97706',
      fontWeight: 600,
      fontSize: '12px',
    },
    degraded: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '4px',
      color: '#d97706',
      fontWeight: 600,
      fontSize: '12px',
    },
  };

  if (status === 'active') {
    return (
      <span style={badgeStyles.active}>
        <CheckCircle size={12} /> {labels.active || 'Active'}
      </span>
    );
  }
  if (status === 'exhausted') {
    return (
      <span style={badgeStyles.exhausted}>
        <XCircle size={12} /> {labels.exhausted || 'Exhausted'}
      </span>
    );
  }
  const labelText = (labels as Record<string, string>)[status] || status;
  return <span style={badgeStyles.paused}>{labelText}</span>;
};

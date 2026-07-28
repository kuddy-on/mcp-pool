import React from 'react';
import { Activity, RefreshCw } from 'lucide-react';
import type { RequestLogItem } from '../../types';
import { Button } from '../common/Button';

export interface LiveLogsTableProps {
  logs: RequestLogItem[];
  t: Record<string, string>;
  timeZone: string;
  browserTz: string;
  fetchLogs: () => void;
}

export const LiveLogsTable: React.FC<LiveLogsTableProps> = ({
  logs,
  t,
  timeZone,
  browserTz,
  fetchLogs,
}) => {
  const formatTimestampWithTz = (isoString: string) => {
    try {
      const normalized =
        isoString.endsWith('Z') || isoString.includes('+') || isoString.includes('-', 10)
          ? isoString
          : isoString + 'Z';
      const date = new Date(normalized);
      const targetTz = timeZone === 'Browser (Auto)' ? browserTz : timeZone;
      return date.toLocaleString('zh-CN', { timeZone: targetTz, hour12: false });
    } catch {
      return isoString;
    }
  };

  return (
    <section
      style={{
        backgroundColor: '#ffffff',
        borderRadius: '8px',
        padding: '14px 16px',
        border: '1px solid #e2e8f0',
        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Activity size={16} color="#4f46e5" />
          <h2 style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
            {t.liveLogsTitle}
          </h2>
        </div>
        <Button variant="secondary" onClick={fetchLogs}>
          <RefreshCw size={12} /> {t.refreshLogs}
        </Button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.2fr 1fr 1.5fr 1fr 1fr 1fr 0.6fr 0.6fr 1.5fr',
            padding: '6px 10px',
            fontSize: '11px',
            fontWeight: 700,
            color: '#475569',
            textTransform: 'uppercase',
          }}
        >
          <div>{t.thTime}</div>
          <div>{t.thService}</div>
          <div>{t.thMethodPath}</div>
          <div>{t.thClientKey}</div>
          <div>{t.thKeyUsed}</div>
          <div>{t.thClientIp}</div>
          <div>{t.thStatus}</div>
          <div>{t.thDuration}</div>
          <div>{t.thFailoverChain}</div>
        </div>
        {logs.map((log) => (
          <div
            key={log.id}
            style={{
              display: 'grid',
              gridTemplateColumns: '1.2fr 1fr 1.5fr 1fr 1fr 1fr 0.6fr 0.6fr 1.5fr',
              padding: '8px 10px',
              borderRadius: '6px',
              border: '1px solid #e2e8f0',
              fontSize: '12px',
              alignItems: 'center',
              color: '#0f172a',
              backgroundColor: '#ffffff',
            }}
          >
            <div>{formatTimestampWithTz(log.timestamp)}</div>
            <div>{log.service_name}</div>
            <div style={{ fontFamily: 'monospace', display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <div>
                {log.method} /{log.path}
              </div>
              {log.mcp_method && (
                <span
                  style={{
                    backgroundColor: '#f3e8ff',
                    color: '#7e22ce',
                    fontSize: '10px',
                    padding: '1px 4px',
                    borderRadius: '3px',
                    fontWeight: 600,
                    width: 'fit-content',
                  }}
                >
                  {log.mcp_method}
                </span>
              )}
            </div>
            <div>
              <span
                style={{
                  fontFamily: 'monospace',
                  backgroundColor: log.client_key_name ? '#dbeafe' : '#f1f5f9',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  color: log.client_key_name ? '#1e40af' : '#94a3b8',
                  fontWeight: 600,
                }}
              >
                {log.client_key_name || '-'}
              </span>
            </div>
            <div>
              <span
                style={{
                  fontFamily: 'monospace',
                  backgroundColor: '#f1f5f9',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  color: '#0f172a',
                  fontWeight: 600,
                }}
              >
                {log.key_name || 'N/A'}
              </span>
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: '11px', color: '#64748b' }}>
              {log.client_ip || '-'}
            </div>
            <div>
              <span
                style={{
                  color: log.status_code < 400 ? '#16a34a' : '#dc2626',
                  fontWeight: 600,
                }}
              >
                {log.status_code}
              </span>
            </div>
            <div>{log.duration_ms} ms</div>
            <div style={{ fontSize: '11px', color: '#64748b' }}>
              {log.failover_chain.join(' → ')}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
};

import React, { useState } from 'react';
import { ShieldCheck, Copy, CheckCircle } from 'lucide-react';
import type { ServiceResponse } from '../../types';
import { Button } from '../common/Button';
import { copyToClipboard } from '../../utils/clipboard';

export interface AgentGuideCardProps {
  selectedService: ServiceResponse;
  externalUrl: string;
  t: Record<string, string>;
}

export const AgentGuideCard: React.FC<AgentGuideCardProps> = ({
  selectedService,
  externalUrl,
  t,
}) => {
  const [copied, setCopied] = useState(false);

  const endpointUrl = `${externalUrl.replace(/\/+$/, '')}/s/${selectedService.name}/mcp`;

  const handleCopy = async () => {
    const success = await copyToClipboard(endpointUrl);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div
      style={{
        backgroundColor: '#eef2ff',
        border: '1px solid #c7d2fe',
        borderRadius: '8px',
        padding: '12px 16px',
        marginBottom: '16px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          color: '#3730a3',
          fontWeight: 600,
          fontSize: '13px',
          marginBottom: '4px',
        }}
      >
        <ShieldCheck size={16} color="#4f46e5" />
        {t.agentGuideTitle} ({selectedService.name})
      </div>
      <p
        style={{
          fontSize: '12px',
          color: '#4338ca',
          margin: '0 0 8px 0',
          lineHeight: '1.4',
        }}
      >
        {t.agentGuideDesc}
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '12px', fontWeight: 600, color: '#312e81' }}>
          {t.gatewayUrlLabel}
        </span>
        <code
          style={{
            backgroundColor: '#ffffff',
            padding: '4px 8px',
            borderRadius: '4px',
            border: '1px solid #a5b4fc',
            color: '#1e1b4b',
            fontFamily: 'monospace',
            fontSize: '12px',
            fontWeight: 600,
            flex: 1,
          }}
        >
          {endpointUrl}
        </code>
        <Button variant="primary" onClick={handleCopy}>
          {copied ? (
            <>
              <CheckCircle size={12} /> {t.copied}
            </>
          ) : (
            <>
              <Copy size={12} /> {t.copy}
            </>
          )}
        </Button>
      </div>
    </div>
  );
};

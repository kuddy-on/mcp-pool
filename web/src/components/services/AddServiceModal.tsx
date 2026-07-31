import React, { useState } from 'react';
import { apiRequest } from '../../api/client';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { CustomSelect } from '../common/CustomSelect';

export interface AddServiceModalProps {
  isOpen: boolean;
  onClose: () => void;
  t: Record<string, string>;
  token: string;
  fetchServices: () => void;
}

export const AddServiceModal: React.FC<AddServiceModalProps> = ({
  isOpen,
  onClose,
  t,
  token,
  fetchServices,
}) => {
  const [newServiceName, setNewServiceName] = useState('');
  const [newServiceUrl, setNewServiceUrl] = useState('');
  const [newServiceProvider, setNewServiceProvider] = useState('context7');

  const providerOptions = [
    { label: 'Context7 (Official)', value: 'context7' },
    { label: 'Generic HTTP Header', value: 'generic' },
  ];

  const handleCreateService = async () => {
    if (!newServiceName || !newServiceUrl) return;
    try {
      await apiRequest('/api/admin/services', token, {
        method: 'POST',
        body: JSON.stringify({
          name: newServiceName,
          upstream_url: newServiceUrl,
          provider_type: newServiceProvider,
        }),
      });
      onClose();
      setNewServiceName('');
      setNewServiceUrl('');
      fetchServices();
    } catch (err) {
      console.error('Failed to create service', err);
    }
  };

  const applyPreset = (presetName: string, url: string, provider: string) => {
    setNewServiceName(presetName);
    setNewServiceUrl(url);
    setNewServiceProvider(provider);
  };

  return (
    <Modal title={t.modalAddServiceTitle} isOpen={isOpen} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div>
          <label style={{ fontSize: '11px', color: '#64748b', display: 'block', marginBottom: '6px' }}>
            {t.quickAddPreset}
          </label>
          <Button
            variant="small"
            type="button"
            onClick={() =>
              applyPreset('context7-prod', 'https://mcp.context7.com/mcp', 'context7')
            }
          >
            + Context7 Official MCP
          </Button>
        </div>

        <div>
          <label
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: '#475569',
              display: 'block',
              marginBottom: '4px',
            }}
          >
            {t.labelServiceName}
          </label>
          <input
            style={{
              width: '100%',
              padding: '8px 10px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              fontSize: '13px',
              boxSizing: 'border-box',
            }}
            value={newServiceName}
            onChange={(e) => setNewServiceName(e.target.value)}
            placeholder={t.phServiceName}
          />
        </div>

        <div>
          <label
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: '#475569',
              display: 'block',
              marginBottom: '4px',
            }}
          >
            {t.labelUpstreamUrl}
          </label>
          <input
            style={{
              width: '100%',
              padding: '8px 10px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              fontSize: '13px',
              boxSizing: 'border-box',
            }}
            value={newServiceUrl}
            onChange={(e) => setNewServiceUrl(e.target.value)}
            placeholder={t.phUpstreamUrl}
          />
        </div>

        <div>
          <label
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: '#475569',
              display: 'block',
              marginBottom: '4px',
            }}
          >
            {t.labelProviderType}
          </label>
          <CustomSelect
            options={providerOptions}
            value={newServiceProvider}
            onChange={(val) => setNewServiceProvider(val)}
            style={{ width: '100%' }}
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' }}>
          <Button variant="secondary" onClick={onClose}>
            {t.btnCancel}
          </Button>
          <Button variant="primary" onClick={handleCreateService}>
            {t.btnSaveService}
          </Button>
        </div>
      </div>
    </Modal>
  );
};

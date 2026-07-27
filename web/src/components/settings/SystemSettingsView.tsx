import React, { useState } from 'react';
import { Settings, Plus, Key, Copy, CheckCircle, Trash2 } from 'lucide-react';
import type { ClientApiKey, UserDTO } from '../../types';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';
import { copyToClipboard } from '../../utils/clipboard';

export interface SystemSettingsViewProps {
  externalUrl: string;
  setExternalUrl: (url: string) => void;
  clientKeys: ClientApiKey[];
  currentUser: UserDTO | null;
  t: Record<string, string>;
  authHeaders: () => HeadersInit;
  fetchSettings: () => void;
}

export const SystemSettingsView: React.FC<SystemSettingsViewProps> = ({
  externalUrl,
  setExternalUrl,
  clientKeys,
  currentUser,
  t,
  authHeaders,
  fetchSettings,
}) => {
  const [showAddClientKeyModal, setShowAddClientKeyModal] = useState(false);
  const [newClientKeyName, setNewClientKeyName] = useState('');
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);

  const handleSaveSettings = async () => {
    try {
      await fetch('/api/admin/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ gateway_external_url: externalUrl }),
      });
      fetchSettings();
    } catch (err) {
      console.error('Failed to save settings', err);
    }
  };

  const handleCreateClientKey = async () => {
    if (!newClientKeyName) return;
    try {
      const res = await fetch('/api/admin/client-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ name: newClientKeyName }),
      });
      if (res.ok) {
        const data = await res.json();
        setNewlyCreatedKey(data.api_key);
        setShowAddClientKeyModal(false);
        setNewClientKeyName('');
        fetchSettings();
      }
    } catch (err) {
      console.error('Failed to create client key', err);
    }
  };

  const handleDeleteClientKey = async (keyId: string) => {
    try {
      await fetch(`/api/admin/client-keys/${keyId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      fetchSettings();
    } catch (err) {
      console.error('Failed to delete client key', err);
    }
  };

  const handleCopyNewKey = async () => {
    if (newlyCreatedKey) {
      const success = await copyToClipboard(newlyCreatedKey);
      if (success) {
        setCopiedKey(true);
        setTimeout(() => setCopiedKey(false), 2000);
      }
    }
  };

  if (currentUser?.role !== 'admin') {
    return (
      <section
        style={{
          backgroundColor: '#ffffff',
          borderRadius: '8px',
          padding: '24px',
          border: '1px solid #e2e8f0',
          textAlign: 'center',
          color: '#64748b',
        }}
      >
        {t.adminOnlySettingTip}
      </section>
    );
  }

  return (
    <main style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* External Domain Config */}
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
            <Settings size={16} color="#4f46e5" />
            <h2 style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
              {t.settingsTitle}
            </h2>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
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
              {t.externalUrlLabel}
            </label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                style={{
                  flex: 1,
                  padding: '8px 10px',
                  borderRadius: '6px',
                  border: '1px solid #cbd5e1',
                  fontSize: '13px',
                }}
                value={externalUrl}
                onChange={(e) => setExternalUrl(e.target.value)}
                placeholder="http://localhost:8100 or https://mcp.mydomain.com"
              />
              <Button variant="primary" onClick={handleSaveSettings}>
                {t.saveSettings}
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* Client API Keys */}
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
            <Key size={16} color="#4f46e5" />
            <h3 style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
              {t.clientKeysTitle}
            </h3>
          </div>
          <Button variant="primary" onClick={() => setShowAddClientKeyModal(true)}>
            <Plus size={12} /> {t.addClientKey}
          </Button>
        </div>

        {newlyCreatedKey && (
          <div
            style={{
              backgroundColor: '#f0fdf4',
              border: '1px solid #bbf7d0',
              borderRadius: '6px',
              padding: '12px',
              marginBottom: '12px',
            }}
          >
            <div
              style={{
                fontSize: '12px',
                fontWeight: 600,
                color: '#166534',
                marginBottom: '6px',
              }}
            >
              {t.rawKeyAlertTitle}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <code
                style={{
                  backgroundColor: '#ffffff',
                  padding: '6px 10px',
                  borderRadius: '4px',
                  border: '1px solid #86efac',
                  color: '#15803d',
                  fontFamily: 'monospace',
                  fontSize: '13px',
                  fontWeight: 700,
                  flex: 1,
                }}
              >
                {newlyCreatedKey}
              </code>
              <Button variant="primary" onClick={handleCopyNewKey}>
                {copiedKey ? (
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
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1.5fr 1.5fr 1fr 1.2fr',
              padding: '6px 10px',
              fontSize: '11px',
              fontWeight: 700,
              color: '#475569',
              textTransform: 'uppercase',
            }}
          >
            <div>{t.thClientKeyName}</div>
            <div>{t.thClientKeyMask}</div>
            <div>{t.thCreatedAt}</div>
            <div>{t.thActions}</div>
          </div>
          {clientKeys.map((ck) => (
            <div
              key={ck.id}
              style={{
                display: 'grid',
                gridTemplateColumns: '1.5fr 1.5fr 1fr 1.2fr',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
                fontSize: '12px',
                alignItems: 'center',
                backgroundColor: '#ffffff',
              }}
            >
              <div style={{ fontWeight: 600, color: '#0f172a' }}>{ck.name}</div>
              <div style={{ fontFamily: 'monospace', color: '#475569' }}>
                {ck.api_key_masked}
              </div>
              <div style={{ color: '#64748b', fontSize: '11px' }}>
                {new Date(ck.created_at).toLocaleDateString()}
              </div>
              <div>
                <Button variant="danger-small" onClick={() => handleDeleteClientKey(ck.id)}>
                  <Trash2 size={11} /> {t.actionDelete}
                </Button>
              </div>
            </div>
          ))}
        </div>

        {/* Add Client Key Modal */}
        <Modal
          title={t.addClientKey}
          isOpen={showAddClientKeyModal}
          onClose={() => setShowAddClientKeyModal(false)}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
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
                {t.thClientKeyName}
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
                value={newClientKeyName}
                onChange={(e) => setNewClientKeyName(e.target.value)}
                placeholder="e.g. Cursor-Pro-Client"
              />
            </div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '8px',
                marginTop: '8px',
              }}
            >
              <Button variant="secondary" onClick={() => setShowAddClientKeyModal(false)}>
                {t.btnCancel}
              </Button>
              <Button variant="primary" onClick={handleCreateClientKey}>
                {t.addClientKey}
              </Button>
            </div>
          </div>
        </Modal>
      </section>
    </main>
  );
};

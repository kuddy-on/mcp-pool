import React, { useState } from 'react';
import { Key, Plus, CheckCircle, XCircle, Edit2 } from 'lucide-react';
import type { AccountKey, ServiceResponse } from '../../types';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';

export interface KeyTableProps {
  service: ServiceResponse;
  t: Record<string, string>;
  authHeaders: () => HeadersInit;
  fetchServices: () => void;
}

export const KeyTable: React.FC<KeyTableProps> = ({
  service,
  t,
  authHeaders,
  fetchServices,
}) => {
  const [showAddKeyModal, setShowAddKeyModal] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newSecretKey, setNewSecretKey] = useState('');
  const [newKeyQuota, setNewKeyQuota] = useState('0');

  const [editingKey, setEditingKey] = useState<AccountKey | null>(null);
  const [editKeyName, setEditKeyName] = useState('');
  const [editKeySecret, setEditKeySecret] = useState('');
  const [editKeyQuota, setEditKeyQuota] = useState('0');
  const [editKeyUsedThisMonth, setEditKeyUsedThisMonth] = useState('0');

  const handleAddKey = async () => {
    if (!newSecretKey) return;
    try {
      const res = await fetch(`/api/admin/services/${service.id}/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          name: newKeyName || 'API Key',
          secret_key: newSecretKey,
          monthly_quota: parseInt(newKeyQuota, 10) || 0,
        }),
      });
      if (res.ok) {
        setShowAddKeyModal(false);
        setNewKeyName('');
        setNewSecretKey('');
        setNewKeyQuota('0');
        fetchServices();
      }
    } catch (err) {
      console.error('Failed to add key', err);
    }
  };

  const openEditKey = (k: AccountKey) => {
    setEditingKey(k);
    setEditKeyName(k.name);
    setEditKeySecret('');
    setEditKeyQuota(String(k.monthly_quota || 0));
    setEditKeyUsedThisMonth(String(k.used_this_month || 0));
  };

  const handleSaveEditKey = async () => {
    if (!editingKey) return;
    try {
      const payload: Record<string, any> = {
        name: editKeyName,
        monthly_quota: parseInt(editKeyQuota, 10) || 0,
        used_this_month: parseInt(editKeyUsedThisMonth, 10) || 0,
      };
      if (editKeySecret.trim()) {
        payload.secret_key = editKeySecret.trim();
      }
      const res = await fetch(`/api/admin/services/${service.id}/keys/${editingKey.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setEditingKey(null);
        fetchServices();
      }
    } catch (err) {
      console.error('Failed to update key', err);
    }
  };

  const handleToggleKey = async (keyId: string, currentActive: boolean) => {
    try {
      await fetch(`/api/admin/services/${service.id}/keys/${keyId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ is_active: !currentActive }),
      });
      fetchServices();
    } catch (err) {
      console.error('Failed to toggle key status', err);
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    try {
      await fetch(`/api/admin/services/${service.id}/keys/${keyId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      fetchServices();
    } catch (err) {
      console.error('Failed to delete key', err);
    }
  };

  return (
    <div>
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
          <h3 style={{ fontSize: '14px', margin: 0, color: '#0f172a' }}>{t.accountPool}</h3>
        </div>
        <Button variant="primary" onClick={() => setShowAddKeyModal(true)}>
          <Plus size={12} /> {t.addKey}
        </Button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.2fr 1.2fr 0.8fr 1.5fr 0.8fr 1.2fr',
            padding: '6px 10px',
            fontSize: '11px',
            fontWeight: 700,
            color: '#475569',
            textTransform: 'uppercase',
          }}
        >
          <div>{t.thName}</div>
          <div>{t.thKeyMask}</div>
          <div>{t.thStatus}</div>
          <div>{t.thQuotaUsage}</div>
          <div>{t.thRequests}</div>
          <div>{t.thActions}</div>
        </div>

        {service.keys.map((k) => {
          const pct =
            k.monthly_quota > 0
              ? Math.min(100, Math.round((k.used_this_month / k.monthly_quota) * 100))
              : 0;
          return (
            <div
              key={k.id}
              style={{
                display: 'grid',
                gridTemplateColumns: '1.2fr 1.2fr 0.8fr 1.5fr 0.8fr 1.2fr',
                padding: '8px 10px',
                alignItems: 'center',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
                fontSize: '12px',
                backgroundColor: '#ffffff',
              }}
            >
              <div style={{ fontWeight: 600, color: '#0f172a' }}>{k.name}</div>
              <div style={{ fontFamily: 'monospace', color: '#475569' }}>{k.key_masked}</div>
              <div>
                {k.is_active && !k.quota_exhausted && (
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      color: '#15803d',
                      fontWeight: 600,
                    }}
                  >
                    <CheckCircle size={12} /> {t.statusActive}
                  </span>
                )}
                {k.quota_exhausted && (
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      color: '#b91c1c',
                      fontWeight: 600,
                    }}
                  >
                    <XCircle size={12} /> {t.statusExhausted}
                  </span>
                )}
                {!k.is_active && !k.quota_exhausted && (
                  <span style={{ color: '#d97706', fontWeight: 600 }}>{t.statusPaused}</span>
                )}
              </div>
              <div>
                {k.monthly_quota > 0 ? (
                  <div>
                    <div
                      style={{
                        fontSize: '11px',
                        color: pct >= 90 ? '#dc2626' : '#475569',
                        fontWeight: 600,
                        marginBottom: '2px',
                      }}
                    >
                      {k.used_this_month} / {k.monthly_quota} ({pct}%)
                    </div>
                    <div
                      style={{
                        width: '100%',
                        maxWidth: '120px',
                        height: '4px',
                        backgroundColor: '#e2e8f0',
                        borderRadius: '2px',
                        overflow: 'hidden',
                      }}
                    >
                      <div
                        style={{
                          width: `${pct}%`,
                          height: '100%',
                          backgroundColor:
                            pct >= 90 ? '#ef4444' : pct >= 75 ? '#f59e0b' : '#6366f1',
                          borderRadius: '2px',
                        }}
                      />
                    </div>
                  </div>
                ) : (
                  <span style={{ color: '#94a3b8', fontSize: '11px' }}>
                    {k.used_this_month} / ∞
                  </span>
                )}
              </div>
              <div style={{ color: '#0f172a' }}>{k.requests_count}</div>
              <div style={{ display: 'flex', gap: '6px' }}>
                <Button variant="small" onClick={() => openEditKey(k)}>
                  <Edit2 size={11} /> {t.actionEdit}
                </Button>
                <Button variant="small" onClick={() => handleToggleKey(k.id, k.is_active)}>
                  {k.is_active ? t.actionPause : t.actionResume}
                </Button>
                <Button variant="danger-small" onClick={() => handleDeleteKey(k.id)}>
                  {t.actionDelete}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Add Key Modal */}
      <Modal
        title={t.modalAddKeyTitle}
        isOpen={showAddKeyModal}
        onClose={() => setShowAddKeyModal(false)}
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
              {t.labelKeyName}
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
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder={t.phKeyName}
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
              {t.labelSecretKey}
            </label>
            <input
              type="password"
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
              value={newSecretKey}
              onChange={(e) => setNewSecretKey(e.target.value)}
              placeholder={t.phSecretKey}
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
              {t.labelMonthlyQuota}
            </label>
            <input
              type="number"
              min="0"
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
              value={newKeyQuota}
              onChange={(e) => setNewKeyQuota(e.target.value)}
              placeholder={t.phMonthlyQuota}
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
            <Button variant="secondary" onClick={() => setShowAddKeyModal(false)}>
              {t.btnCancel}
            </Button>
            <Button variant="primary" onClick={handleAddKey}>
              {t.btnAddKey}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Edit Key Modal */}
      <Modal
        title={t.modalEditKeyTitle}
        isOpen={Boolean(editingKey)}
        onClose={() => setEditingKey(null)}
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
              {t.labelKeyName}
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
              value={editKeyName}
              onChange={(e) => setEditKeyName(e.target.value)}
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
              {t.labelSecretKey} (留空不修改)
            </label>
            <input
              type="password"
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
              value={editKeySecret}
              onChange={(e) => setEditKeySecret(e.target.value)}
              placeholder="••••••••"
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
              {t.labelMonthlyQuota}
            </label>
            <input
              type="number"
              min="0"
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
              value={editKeyQuota}
              onChange={(e) => setEditKeyQuota(e.target.value)}
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
              {t.labelUsedThisMonth}
            </label>
            <input
              type="number"
              min="0"
              style={{
                width: '100%',
                padding: '8px 10px',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                fontSize: '13px',
                boxSizing: 'border-box',
              }}
              value={editKeyUsedThisMonth}
              onChange={(e) => setEditKeyUsedThisMonth(e.target.value)}
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
            <Button variant="secondary" onClick={() => setEditingKey(null)}>
              {t.btnCancel}
            </Button>
            <Button variant="primary" onClick={handleSaveEditKey}>
              {t.btnSaveService}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

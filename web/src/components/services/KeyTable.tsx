import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  Edit2,
  Gauge,
  Key,
  Plus,
  RefreshCw,
  XCircle,
} from 'lucide-react';
import { apiRequest } from '../../api/client';
import type {
  AccountKey,
  ProviderQuotaKeyStatus,
  ServiceQuotaStatusResponse,
  ServiceResponse,
} from '../../types';
import { Button } from '../common/Button';
import { AddKeyModal, EditKeyModal } from './KeyModals';

export interface KeyTableProps {
  service: ServiceResponse;
  t: Record<string, string>;
  token: string;
  fetchServices: () => void;
}

const formatQuotaTime = (value: string | null): string => {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const KeyTable: React.FC<KeyTableProps> = ({
  service,
  t,
  token,
  fetchServices,
}) => {
  const [showAddKeyModal, setShowAddKeyModal] = useState(false);
  const [editingKey, setEditingKey] = useState<AccountKey | null>(null);
  const [providerQuota, setProviderQuota] = useState<ServiceQuotaStatusResponse | null>(null);
  const [quotaLoading, setQuotaLoading] = useState(false);
  const [refreshingQuotaKey, setRefreshingQuotaKey] = useState<string | null>(null);
  const [refreshingAllQuota, setRefreshingAllQuota] = useState(false);
  const [quotaRequestError, setQuotaRequestError] = useState(false);
  const activeServiceIdRef = useRef(service.id);
  activeServiceIdRef.current = service.id;

  const isContext7 = service.provider_type.toLowerCase() === 'context7';
  const gridTemplateColumns = isContext7
    ? '1fr 1fr 0.75fr 1.55fr 1.2fr 0.65fr 1.25fr'
    : '1.2fr 1.2fr 0.8fr 1.5fr 0.8fr 1.2fr';
  const tableMinWidth = isContext7 ? '840px' : '680px';

  const fetchProviderQuota = useCallback(
    async (showLoading = false, signal?: AbortSignal) => {
      if (!isContext7) {
        setProviderQuota(null);
        setQuotaRequestError(false);
        return;
      }
      if (showLoading) setQuotaLoading(true);
      try {
        const data = await apiRequest<ServiceQuotaStatusResponse>(
          `/api/admin/services/${service.id}/quota-status`,
          token,
          {
          signal,
          },
        );
        if (!signal?.aborted && activeServiceIdRef.current === data.service_id) {
          setProviderQuota(data);
          setQuotaRequestError(false);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        console.error('Failed to fetch provider quota status', err);
        if (!signal?.aborted && activeServiceIdRef.current === service.id) {
          setQuotaRequestError(true);
        }
      } finally {
        if (showLoading && !signal?.aborted && activeServiceIdRef.current === service.id) {
          setQuotaLoading(false);
        }
      }
    },
    [isContext7, service.id, token]
  );

  useEffect(() => {
    setProviderQuota(null);
    setRefreshingQuotaKey(null);
    setRefreshingAllQuota(false);
    setQuotaRequestError(false);
    if (!isContext7) {
      setQuotaLoading(false);
      return;
    }

    const controller = new AbortController();
    void fetchProviderQuota(true, controller.signal);
    const interval = window.setInterval(() => {
      void fetchProviderQuota(false, controller.signal);
    }, 5000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [fetchProviderQuota, isContext7]);

  const handleRefreshProviderQuota = async (keyId: string) => {
    if (!window.confirm(t.quotaRefreshWarning)) return;
    const requestServiceId = service.id;
    setRefreshingQuotaKey(keyId);
    setQuotaRequestError(false);
    try {
      const params = new URLSearchParams({ key_id: keyId });
      const data = await apiRequest<ServiceQuotaStatusResponse>(
        `/api/admin/services/${service.id}/quota-status/refresh?${params.toString()}`,
        token,
        {
          method: 'POST',
        },
      );
      if (activeServiceIdRef.current === data.service_id) {
        setProviderQuota(data);
        fetchServices();
      }
    } catch (err) {
      console.error('Failed to refresh provider quota status', err);
      if (activeServiceIdRef.current === requestServiceId) {
        setQuotaRequestError(true);
      }
    } finally {
      if (activeServiceIdRef.current === requestServiceId) {
        setRefreshingQuotaKey(null);
      }
    }
  };

  const handleRefreshAllProviderQuota = async () => {
    const warning = t.quotaRefreshAllWarning.replace(
      '{count}',
      String(service.keys.length)
    );
    if (!window.confirm(warning)) return;

    const requestServiceId = service.id;
    setRefreshingAllQuota(true);
    setQuotaRequestError(false);
    try {
      const data = await apiRequest<ServiceQuotaStatusResponse>(
        `/api/admin/services/${service.id}/quota-status/refresh`,
        token,
        { method: 'POST' },
      );
      if (activeServiceIdRef.current === data.service_id) {
        setProviderQuota(data);
        fetchServices();
      }
    } catch (err) {
      console.error('Failed to refresh all provider quota statuses', err);
      if (activeServiceIdRef.current === requestServiceId) {
        setQuotaRequestError(true);
      }
    } finally {
      if (activeServiceIdRef.current === requestServiceId) {
        setRefreshingAllQuota(false);
      }
    }
  };

  const renderProviderQuota = (quota: ProviderQuotaKeyStatus | undefined, keyId: string) => {
    const refreshing = refreshingQuotaKey === keyId;
    const hasLatestError = quota?.status === 'error' || quota?.status === 'auth_invalid';
    const canRenderUsage =
      quota && quota.limit !== null && quota.remaining !== null && quota.used !== null;
    const pct =
      canRenderUsage && quota.limit! > 0
        ? Math.min(100, Math.round((quota.used! / quota.limit!) * 100))
        : 0;

    return (
      <div style={{ minWidth: 0 }}>
        {canRenderUsage ? (
          <>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                color: quota.status === 'exhausted' ? '#b91c1c' : '#334155',
                fontWeight: 700,
                fontSize: '11px',
              }}
            >
              <span>
                {quota.used} / {quota.limit}
              </span>
              <span style={{ color: quota.remaining === 0 ? '#b91c1c' : '#15803d' }}>
                · {t.quotaRemaining} {quota.remaining}
              </span>
              {quota.estimated && (
                <span
                  title={t.quotaEstimatedHint}
                  style={{
                    color: '#0369a1',
                    border: '1px solid #7dd3fc',
                    borderRadius: '3px',
                    padding: '0 3px',
                    fontSize: '9px',
                    lineHeight: 1.4,
                  }}
                >
                  {t.quotaEstimated}
                </span>
              )}
              {(quota.stale || hasLatestError) && (
                <span
                  title={
                    hasLatestError
                      ? quota.status === 'auth_invalid'
                        ? t.quotaAuthInvalid
                        : t.quotaQueryFailed
                      : t.quotaStale
                  }
                  style={{
                    color: hasLatestError ? '#b91c1c' : '#b45309',
                    display: 'inline-flex',
                    alignItems: 'center',
                  }}
                >
                  <AlertTriangle size={11} />
                </span>
              )}
            </div>
            <div
              style={{
                width: '100%',
                maxWidth: '145px',
                height: '4px',
                marginTop: '3px',
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
                    pct >= 90 ? '#ef4444' : pct >= 75 ? '#f59e0b' : '#10b981',
                }}
              />
            </div>
            <div style={{ marginTop: '3px', color: '#64748b', fontSize: '10px' }}>
              {t.quotaResets}: {formatQuotaTime(quota.reset_at)}
            </div>
            <div style={{ color: '#94a3b8', fontSize: '10px' }}>
              {t.quotaSnapshotAt}: {formatQuotaTime(quota.last_success_at)}
            </div>
            {hasLatestError && (
              <>
                <div style={{ color: '#94a3b8', fontSize: '10px' }}>
                  {t.quotaAttemptedAt}: {formatQuotaTime(quota.last_attempt_at)}
                </div>
                <div style={{ color: '#b91c1c', fontSize: '10px', fontWeight: 600 }}>
                  {quota.status === 'auth_invalid' ? t.quotaAuthInvalid : t.quotaQueryFailed}
                </div>
              </>
            )}
          </>
        ) : (
          <div
            style={{
              color: quota?.status === 'auth_invalid' ? '#b91c1c' : '#64748b',
              fontSize: '11px',
            }}
          >
            {quota?.status === 'auth_invalid'
              ? t.quotaAuthInvalid
              : quota?.status === 'error'
                ? t.quotaQueryFailed
                : t.quotaNotChecked}
            {quota?.last_attempt_at && (
              <div style={{ color: '#94a3b8', fontSize: '10px' }}>
                {t.quotaAttemptedAt}: {formatQuotaTime(quota.last_attempt_at)}
              </div>
            )}
          </div>
        )}
        {providerQuota?.can_refresh && (
          <button
            type="button"
            onClick={() => void handleRefreshProviderQuota(keyId)}
            disabled={refreshing || refreshingAllQuota}
            title={t.quotaRefreshWarning}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              marginTop: '4px',
              padding: 0,
              border: 0,
              background: 'transparent',
              color: '#4f46e5',
              fontSize: '10px',
              fontWeight: 600,
              cursor: refreshing || refreshingAllQuota ? 'wait' : 'pointer',
            }}
          >
            <RefreshCw
              size={10}
              className={refreshing || refreshingAllQuota ? 'spin' : undefined}
            />
            {refreshing ? t.quotaRefreshing : t.quotaRefresh}
          </button>
        )}
      </div>
    );
  };

  const handleToggleKey = async (keyId: string, currentActive: boolean) => {
    try {
      await apiRequest(`/api/admin/services/${service.id}/keys/${keyId}`, token, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !currentActive }),
      });
      fetchServices();
    } catch (err) {
      console.error('Failed to toggle key status', err);
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    try {
      await apiRequest(`/api/admin/services/${service.id}/keys/${keyId}`, token, {
        method: 'DELETE',
      });
      fetchServices();
    } catch (err) {
      console.error('Failed to delete key', err);
    }
  };

  return (
    <div className="key-table">
      <div
        className="key-table__toolbar"
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

      {isContext7 && (
        <div
          className="quota-hint"
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '7px',
            marginBottom: '10px',
            padding: '8px 10px',
            border: '1px solid #bfdbfe',
            borderRadius: '6px',
            backgroundColor: '#eff6ff',
            color: '#1e3a8a',
            fontSize: '11px',
          }}
        >
          <Gauge size={14} style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>{t.context7QuotaHint}</span>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginLeft: 'auto',
              flexShrink: 0,
            }}
          >
            {(quotaLoading || quotaRequestError) && (
              <span style={{ color: quotaRequestError ? '#b91c1c' : '#64748b' }}>
                {quotaRequestError ? t.quotaQueryFailed : t.quotaLoading}
              </span>
            )}
            {providerQuota?.can_refresh && (
              <Button
                variant="small"
                onClick={() => void handleRefreshAllProviderQuota()}
                disabled={
                  refreshingAllQuota ||
                  refreshingQuotaKey !== null ||
                  service.keys.length === 0
                }
                title={t.quotaRefreshAllWarning.replace(
                  '{count}',
                  String(service.keys.length)
                )}
                style={{ color: '#4f46e5', borderColor: '#93c5fd' }}
              >
                <RefreshCw size={11} className={refreshingAllQuota ? 'spin' : undefined} />
                {refreshingAllQuota ? t.quotaRefreshingAll : t.quotaRefreshAll}
              </Button>
            )}
          </div>
        </div>
      )}

      <div
        className="key-table__grid"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          overflowX: 'auto',
        }}
      >
        <div
          className="key-table__head"
          style={{
            display: 'grid',
            gridTemplateColumns,
            minWidth: tableMinWidth,
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
          {isContext7 && <div>{t.thProviderQuota}</div>}
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
              className="key-table__row"
              key={k.id}
              style={{
                display: 'grid',
                gridTemplateColumns,
                minWidth: tableMinWidth,
                padding: '8px 10px',
                alignItems: 'center',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
                fontSize: '12px',
                backgroundColor: '#ffffff',
              }}
            >
              <div className="key-cell key-cell--name" data-label={t.thName} style={{ fontWeight: 600, color: '#0f172a' }}>{k.name}</div>
              <div className="key-cell" data-label={t.thKeyMask} style={{ fontFamily: 'monospace', color: '#475569' }}>{k.key_masked}</div>
              <div className="key-cell" data-label={t.thStatus}>
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
              {isContext7 && <div className="key-cell" data-label={t.thProviderQuota}>
                {renderProviderQuota(
                  providerQuota?.keys.find((quota) => quota.key_id === k.id),
                  k.id
                )}
              </div>}
              <div className="key-cell" data-label={t.thQuotaUsage}>
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
              <div className="key-cell" data-label={t.thRequests} style={{ color: '#0f172a' }}>{k.requests_count}</div>
              <div className="key-cell key-cell--actions" data-label={t.thActions} style={{ display: 'flex', gap: '6px' }}>
                <Button variant="small" onClick={() => setEditingKey(k)}>
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

      <AddKeyModal serviceId={service.id} open={showAddKeyModal} onClose={() => setShowAddKeyModal(false)} t={t} token={token} onSaved={fetchServices} />
      <EditKeyModal serviceId={service.id} item={editingKey} onClose={() => setEditingKey(null)} t={t} token={token} onSaved={fetchServices} />
    </div>
  );
};

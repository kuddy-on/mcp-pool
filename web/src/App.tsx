import React, { useEffect, useState } from 'react';
import {
  Server,
  Key,
  RefreshCw,
  CheckCircle,
  XCircle,
  ShieldCheck,
  Activity,
  Plus,
  Trash2,
  Play,
  Layers,
  Globe,
} from 'lucide-react';

type Lang = 'zh' | 'en';

const translations = {
  zh: {
    title: 'MCPPool 网关控制台',
    servicesTab: '服务与账号池',
    logsTab: '实时日志',
    mcpServices: 'MCP 服务列表',
    addService: '添加服务',
    upstream: '上游地址',
    testConnection: '测试连接',
    testing: '测试中...',
    deleteService: '删除服务',
    testResults: '连接测试结果',
    accountPool: '账号池 / API 密钥',
    addKey: '添加 Key',
    thName: '名称',
    thKeyMask: '密钥脱敏',
    thStatus: '状态',
    thRequests: '请求数',
    thActions: '操作',
    statusActive: '可用',
    statusExhausted: '已耗尽',
    statusPaused: '已暂停',
    actionPause: '暂停',
    actionResume: '恢复',
    actionDelete: '删除',
    liveLogsTitle: '实时请求日志与故障切换链路',
    refreshLogs: '刷新日志',
    thTime: '时间',
    thService: '服务',
    thMethodPath: '请求方法与路径',
    thDuration: '耗时',
    thFailoverChain: '故障切换链路',
    modalAddServiceTitle: '新增 MCP 服务',
    labelServiceName: '服务名称',
    labelUpstreamUrl: '上游 Endpoint URL',
    labelProviderType: 'Provider 类型',
    btnCancel: '取消',
    btnSaveService: '保存服务',
    modalAddKeyTitle: '添加 Key 到密钥池',
    labelKeyName: 'Key 名称 / 别名',
    labelSecretKey: '密钥内容 (Secret API Key)',
    btnAddKey: '添加 Key',
    confirmDeleteService: '确定要删除该 MCP 服务吗？',
    keysCount: '个可用 Key',
  },
  en: {
    title: 'MCPPool Gateway Dashboard',
    servicesTab: 'Services & Account Pools',
    logsTab: 'Live Logs',
    mcpServices: 'MCP Services',
    addService: 'Add Service',
    upstream: 'Upstream',
    testConnection: 'Test Connection',
    testing: 'Testing...',
    deleteService: 'Delete Service',
    testResults: 'Connection Test Results',
    accountPool: 'Account Pool / API Keys',
    addKey: 'Add Key',
    thName: 'Name',
    thKeyMask: 'Key Mask',
    thStatus: 'Status',
    thRequests: 'Requests',
    thActions: 'Actions',
    statusActive: 'Active',
    statusExhausted: 'Exhausted',
    statusPaused: 'Paused',
    actionPause: 'Pause',
    actionResume: 'Resume',
    actionDelete: 'Delete',
    liveLogsTitle: 'Live Request Logs & Failover Chains',
    refreshLogs: 'Refresh Logs',
    thTime: 'Time',
    thService: 'Service',
    thMethodPath: 'Method & Path',
    thDuration: 'Duration',
    thFailoverChain: 'Failover Chain',
    modalAddServiceTitle: 'Add New MCP Service',
    labelServiceName: 'Service Name',
    labelUpstreamUrl: 'Upstream Endpoint URL',
    labelProviderType: 'Provider Type',
    btnCancel: 'Cancel',
    btnSaveService: 'Save Service',
    modalAddKeyTitle: 'Add Key to Pool',
    labelKeyName: 'Key Name / Alias',
    labelSecretKey: 'Secret API Key',
    btnAddKey: 'Add Key',
    confirmDeleteService: 'Are you sure you want to delete this MCP service?',
    keysCount: 'Keys',
  },
};

interface AccountKey {
  id: string;
  name: string;
  key_masked: string;
  is_active: boolean;
  quota_exhausted: boolean;
  paused_until: string | null;
  weight: number;
  fail_count: number;
  requests_count: number;
  last_used: string | null;
}

interface ServiceResponse {
  id: string;
  name: string;
  upstream_url: string;
  provider_type: string;
  auth_header: string;
  auth_prefix: string;
  total_keys: number;
  active_keys: number;
  status: string;
  keys: AccountKey[];
}

interface RequestLogItem {
  id: string;
  service_name: string;
  timestamp: string;
  method: string;
  path: string;
  key_id: string | null;
  status_code: number;
  signal_kind: string;
  duration_ms: number;
  failover_chain: string[];
}

interface TestResultItem {
  step: string;
  success: boolean;
  message: string;
  duration_ms: number;
}

export function App() {
  const [lang, setLang] = useState<Lang>('zh');
  const t = translations[lang];

  const [services, setServices] = useState<ServiceResponse[]>([]);
  const [selectedService, setSelectedService] = useState<ServiceResponse | null>(null);
  const [logs, setLogs] = useState<RequestLogItem[]>([]);
  const [activeTab, setActiveTab] = useState<'services' | 'logs'>('services');

  // Modal states
  const [showAddServiceModal, setShowAddServiceModal] = useState(false);
  const [newServiceName, setNewServiceName] = useState('');
  const [newServiceUrl, setNewServiceUrl] = useState('');
  const [newServiceProvider, setNewServiceProvider] = useState('context7');

  const [showAddKeyModal, setShowAddKeyModal] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newSecretKey, setNewSecretKey] = useState('');

  const [testResults, setTestResults] = useState<TestResultItem[] | null>(null);
  const [testing, setTesting] = useState(false);

  const fetchServices = async () => {
    try {
      const res = await fetch('/api/admin/services');
      if (res.ok) {
        const data: ServiceResponse[] = await res.json();
        setServices(data);
        if (data.length > 0) {
          setSelectedService((prev) => {
            if (!prev) return data[0];
            const updated = data.find((s) => s.id === prev.id);
            return updated || data[0];
          });
        }
      }
    } catch (err) {
      console.error('Failed to fetch services', err);
    }
  };

  const fetchLogs = async () => {
    try {
      const res = await fetch('/api/admin/requests');
      if (res.ok) {
        const data: RequestLogItem[] = await res.json();
        setLogs(data);
      }
    } catch (err) {
      console.error('Failed to fetch logs', err);
    }
  };

  useEffect(() => {
    fetchServices();
    fetchLogs();
    const interval = setInterval(() => {
      fetchServices();
      fetchLogs();
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleCreateService = async () => {
    if (!newServiceName || !newServiceUrl) return;
    try {
      const res = await fetch('/api/admin/services', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newServiceName,
          upstream_url: newServiceUrl,
          provider_type: newServiceProvider,
          api_keys: [],
        }),
      });
      if (res.ok) {
        setShowAddServiceModal(false);
        setNewServiceName('');
        setNewServiceUrl('');
        fetchServices();
      }
    } catch (err) {
      console.error('Failed to create service', err);
    }
  };

  const handleDeleteService = async (serviceId: string) => {
    if (!confirm(t.confirmDeleteService)) return;
    try {
      const res = await fetch(`/api/admin/services/${serviceId}`, { method: 'DELETE' });
      if (res.ok) {
        fetchServices();
      }
    } catch (err) {
      console.error('Failed to delete service', err);
    }
  };

  const handleAddKey = async () => {
    if (!selectedService || !newSecretKey) return;
    try {
      const res = await fetch(`/api/admin/services/${selectedService.id}/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newKeyName || 'API Key',
          secret_key: newSecretKey,
        }),
      });
      if (res.ok) {
        setShowAddKeyModal(false);
        setNewKeyName('');
        setNewSecretKey('');
        fetchServices();
      }
    } catch (err) {
      console.error('Failed to add key', err);
    }
  };

  const handleToggleKey = async (keyId: string, currentActive: boolean) => {
    if (!selectedService) return;
    try {
      await fetch(`/api/admin/services/${selectedService.id}/keys/${keyId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !currentActive }),
      });
      fetchServices();
    } catch (err) {
      console.error('Failed to toggle key status', err);
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    if (!selectedService) return;
    try {
      await fetch(`/api/admin/services/${selectedService.id}/keys/${keyId}`, {
        method: 'DELETE',
      });
      fetchServices();
    } catch (err) {
      console.error('Failed to delete key', err);
    }
  };

  const handleTestService = async (serviceId: string) => {
    setTesting(true);
    setTestResults(null);
    try {
      const res = await fetch(`/api/admin/services/${serviceId}/test`, { method: 'POST' });
      if (res.ok) {
        const results: TestResultItem[] = await res.json();
        setTestResults(results);
      }
    } catch (err) {
      console.error('Failed to test service', err);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <div style={styles.brand}>
          <ShieldCheck size={20} color="#4f46e5" />
          <h1 style={styles.title}>{t.title}</h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={styles.navTabs}>
            <button
              style={activeTab === 'services' ? styles.tabActive : styles.tab}
              onClick={() => setActiveTab('services')}
            >
              <Layers size={14} /> {t.servicesTab}
            </button>
            <button
              style={activeTab === 'logs' ? styles.tabActive : styles.tab}
              onClick={() => setActiveTab('logs')}
            >
              <Activity size={14} /> {t.logsTab}
            </button>
          </div>

          <div style={styles.langSelector}>
            <Globe size={14} color="#64748b" />
            <select
              style={styles.langSelect}
              value={lang}
              onChange={(e) => setLang(e.target.value as Lang)}
            >
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
      </header>

      {activeTab === 'services' && (
        <main style={styles.grid}>
          {/* Left Panel: Services List */}
          <section style={styles.card}>
            <div style={styles.cardHeaderBetween}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Server size={16} color="#4f46e5" />
                <h2 style={styles.cardTitle}>{t.mcpServices}</h2>
              </div>
              <button style={styles.btnPrimary} onClick={() => setShowAddServiceModal(true)}>
                <Plus size={12} /> {t.addService}
              </button>
            </div>

            <div style={styles.serviceList}>
              {services.map((s) => {
                const isSelected = selectedService?.id === s.id;
                return (
                  <div
                    key={s.id}
                    style={{
                      ...styles.serviceItem,
                      borderLeft: isSelected ? '3px solid #4f46e5' : '3px solid transparent',
                      backgroundColor: isSelected ? '#f1f5f9' : '#ffffff',
                    }}
                    onClick={() => setSelectedService(s)}
                  >
                    <div>
                      <div style={{ fontWeight: 600, color: '#0f172a' }}>{s.name}</div>
                      <div style={{ fontSize: '11px', color: '#64748b' }}>{s.upstream_url}</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span
                        style={
                          s.status === 'active'
                            ? styles.statusActive
                            : s.status === 'degraded'
                            ? styles.statusDegraded
                            : styles.statusExhausted
                        }
                      >
                        {s.status === 'active'
                          ? t.statusActive
                          : s.status === 'degraded'
                          ? t.statusPaused
                          : t.statusExhausted}
                      </span>
                      <div style={{ fontSize: '11px', color: '#64748b', marginTop: '1px' }}>
                        {s.active_keys} / {s.total_keys} {t.keysCount}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Right Panel: Selected Service Detail & Account Pool */}
          {selectedService && (
            <section style={{ ...styles.card, flex: 2 }}>
              <div style={styles.cardHeaderBetween}>
                <div>
                  <h2 style={{ ...styles.cardTitle, fontSize: '15px' }}>{selectedService.name}</h2>
                  <div style={{ fontSize: '12px', color: '#64748b' }}>
                    {t.upstream}: {selectedService.upstream_url}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    style={styles.btnSecondary}
                    onClick={() => handleTestService(selectedService.id)}
                    disabled={testing}
                  >
                    <Play size={12} /> {testing ? t.testing : t.testConnection}
                  </button>
                  <button
                    style={styles.btnDanger}
                    onClick={() => handleDeleteService(selectedService.id)}
                  >
                    <Trash2 size={12} /> {t.deleteService}
                  </button>
                </div>
              </div>

              {testResults && (
                <div style={styles.testConsole}>
                  <div style={{ fontWeight: 600, marginBottom: '6px' }}>{t.testResults}</div>
                  {testResults.map((tr, idx) => (
                    <div key={idx} style={styles.testItem}>
                      <span>{tr.step}:</span>
                      <span style={{ color: tr.success ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                        {tr.message} ({tr.duration_ms}ms)
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Account Pool / Keys */}
              <div style={{ marginTop: '14px' }}>
                <div style={styles.cardHeaderBetween}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Key size={16} color="#4f46e5" />
                    <h3 style={{ fontSize: '14px', margin: 0, color: '#0f172a' }}>{t.accountPool}</h3>
                  </div>
                  <button style={styles.btnPrimary} onClick={() => setShowAddKeyModal(true)}>
                    <Plus size={12} /> {t.addKey}
                  </button>
                </div>

                <div style={styles.table}>
                  <div style={styles.tableHeader}>
                    <div>{t.thName}</div>
                    <div>{t.thKeyMask}</div>
                    <div>{t.thStatus}</div>
                    <div>{t.thRequests}</div>
                    <div>{t.thActions}</div>
                  </div>
                  {selectedService.keys.map((k) => (
                    <div key={k.id} style={styles.tableRow}>
                      <div style={{ fontWeight: 600, color: '#0f172a' }}>{k.name}</div>
                      <div style={{ fontFamily: 'monospace', color: '#475569' }}>{k.key_masked}</div>
                      <div>
                        {k.is_active && !k.quota_exhausted && (
                          <span style={styles.statusActive}>
                            <CheckCircle size={12} /> {t.statusActive}
                          </span>
                        )}
                        {k.quota_exhausted && (
                          <span style={styles.statusExhausted}>
                            <XCircle size={12} /> {t.statusExhausted}
                          </span>
                        )}
                        {!k.is_active && !k.quota_exhausted && (
                          <span style={styles.statusDegraded}>{t.statusPaused}</span>
                        )}
                      </div>
                      <div style={{ color: '#0f172a' }}>{k.requests_count}</div>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button
                          style={styles.btnSmall}
                          onClick={() => handleToggleKey(k.id, k.is_active)}
                        >
                          {k.is_active ? t.actionPause : t.actionResume}
                        </button>
                        <button
                          style={{ ...styles.btnSmall, color: '#ef4444' }}
                          onClick={() => handleDeleteKey(k.id)}
                        >
                          {t.actionDelete}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}
        </main>
      )}

      {activeTab === 'logs' && (
        <section style={styles.card}>
          <div style={styles.cardHeaderBetween}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Activity size={16} color="#4f46e5" />
              <h2 style={styles.cardTitle}>{t.liveLogsTitle}</h2>
            </div>
            <button style={styles.btnSecondary} onClick={fetchLogs}>
              <RefreshCw size={12} /> {t.refreshLogs}
            </button>
          </div>

          <div style={styles.logTable}>
            <div style={styles.logHeader}>
              <div>{t.thTime}</div>
              <div>{t.thService}</div>
              <div>{t.thMethodPath}</div>
              <div>{t.thStatus}</div>
              <div>{t.thDuration}</div>
              <div>{t.thFailoverChain}</div>
            </div>
            {logs.map((log) => (
              <div key={log.id} style={styles.logRow}>
                <div>{new Date(log.timestamp).toLocaleTimeString()}</div>
                <div>{log.service_name}</div>
                <div style={{ fontFamily: 'monospace' }}>
                  {log.method} /{log.path}
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
      )}

      {/* Add Service Modal */}
      {showAddServiceModal && (
        <div style={styles.modalOverlay}>
          <div style={styles.modal}>
            <h3 style={{ marginTop: 0, fontSize: '15px', color: '#0f172a' }}>{t.modalAddServiceTitle}</h3>
            <div style={styles.formGroup}>
              <label style={styles.label}>{t.labelServiceName}</label>
              <input
                style={styles.input}
                value={newServiceName}
                onChange={(e) => setNewServiceName(e.target.value)}
                placeholder="e.g. context7-prod"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>{t.labelUpstreamUrl}</label>
              <input
                style={styles.input}
                value={newServiceUrl}
                onChange={(e) => setNewServiceUrl(e.target.value)}
                placeholder="https://api.context7.com/mcp"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>{t.labelProviderType}</label>
              <select
                style={styles.input}
                value={newServiceProvider}
                onChange={(e) => setNewServiceProvider(e.target.value)}
              >
                <option value="context7">Context7</option>
                <option value="generic">Generic Header</option>
              </select>
            </div>
            <div style={styles.modalActions}>
              <button style={styles.btnSecondary} onClick={() => setShowAddServiceModal(false)}>
                {t.btnCancel}
              </button>
              <button style={styles.btnPrimary} onClick={handleCreateService}>
                {t.btnSaveService}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Key Modal */}
      {showAddKeyModal && (
        <div style={styles.modalOverlay}>
          <div style={styles.modal}>
            <h3 style={{ marginTop: 0, fontSize: '15px', color: '#0f172a' }}>{t.modalAddKeyTitle}</h3>
            <div style={styles.formGroup}>
              <label style={styles.label}>{t.labelKeyName}</label>
              <input
                style={styles.input}
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="e.g. Backup Account Key"
              />
            </div>
            <div style={styles.formGroup}>
              <label style={styles.label}>{t.labelSecretKey}</label>
              <input
                type="password"
                style={styles.input}
                value={newSecretKey}
                onChange={(e) => setNewSecretKey(e.target.value)}
                placeholder="Enter secret key string"
              />
            </div>
            <div style={styles.modalActions}>
              <button style={styles.btnSecondary} onClick={() => setShowAddKeyModal(false)}>
                {t.btnCancel}
              </button>
              <button style={styles.btnPrimary} onClick={handleAddKey}>
                {t.btnAddKey}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    backgroundColor: '#f1f5f9',
    minHeight: '100vh',
    padding: '16px 24px',
    color: '#0f172a',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
    paddingBottom: '12px',
    borderBottom: '1px solid #cbd5e1',
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  title: {
    fontSize: '16px',
    fontWeight: 700,
    color: '#0f172a',
    margin: 0,
  },
  navTabs: {
    display: 'flex',
    gap: '6px',
  },
  tab: {
    padding: '5px 12px',
    borderRadius: '5px',
    border: '1px solid #cbd5e1',
    backgroundColor: '#ffffff',
    color: '#334155',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  tabActive: {
    padding: '5px 12px',
    borderRadius: '5px',
    border: '1px solid #4f46e5',
    backgroundColor: '#4f46e5',
    color: '#ffffff',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  langSelector: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    backgroundColor: '#ffffff',
    border: '1px solid #cbd5e1',
    borderRadius: '5px',
    padding: '5px 10px',
    height: '29px',
    boxSizing: 'border-box',
  },
  langSelect: {
    border: 'none',
    backgroundColor: 'transparent',
    fontSize: '12px',
    fontWeight: 600,
    color: '#334155',
    cursor: 'pointer',
    outline: 'none',
    lineHeight: '1',
    padding: '0 2px',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '300px 1fr',
    gap: '16px',
  },
  card: {
    backgroundColor: '#ffffff',
    borderRadius: '8px',
    padding: '14px 16px',
    border: '1px solid #e2e8f0',
    boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
  },
  cardHeaderBetween: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  cardTitle: {
    fontSize: '14px',
    fontWeight: 700,
    color: '#0f172a',
    margin: 0,
  },
  serviceList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  serviceItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '8px 10px',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
    cursor: 'pointer',
  },
  table: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '1.5fr 1.5fr 1fr 1fr 1.2fr',
    padding: '6px 10px',
    fontSize: '11px',
    fontWeight: 700,
    color: '#475569',
    textTransform: 'uppercase',
  },
  tableRow: {
    display: 'grid',
    gridTemplateColumns: '1.5fr 1.5fr 1fr 1fr 1.2fr',
    padding: '8px 10px',
    alignItems: 'center',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
    fontSize: '12px',
  },
  statusActive: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: '#15803d',
    fontWeight: 600,
    fontSize: '12px',
  },
  statusDegraded: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: '#b45309',
    fontWeight: 600,
    fontSize: '12px',
  },
  statusExhausted: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: '#b91c1c',
    fontWeight: 600,
    fontSize: '12px',
  },
  btnPrimary: {
    backgroundColor: '#4f46e5',
    color: '#ffffff',
    border: 'none',
    padding: '5px 10px',
    borderRadius: '5px',
    fontWeight: 600,
    fontSize: '12px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  btnSecondary: {
    backgroundColor: '#ffffff',
    color: '#1e293b',
    border: '1px solid #cbd5e1',
    padding: '5px 10px',
    borderRadius: '5px',
    fontWeight: 600,
    fontSize: '12px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  btnDanger: {
    backgroundColor: '#dc2626',
    color: '#ffffff',
    border: 'none',
    padding: '5px 10px',
    borderRadius: '5px',
    fontWeight: 600,
    fontSize: '12px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  btnSmall: {
    padding: '3px 8px',
    fontSize: '11px',
    borderRadius: '4px',
    border: '1px solid #cbd5e1',
    backgroundColor: '#ffffff',
    color: '#0f172a',
    cursor: 'pointer',
    fontWeight: 500,
  },
  label: {
    fontSize: '12px',
    fontWeight: 600,
    color: '#334155',
  },
  testConsole: {
    backgroundColor: '#0f172a',
    color: '#f8fafc',
    padding: '10px 12px',
    borderRadius: '6px',
    fontSize: '12px',
    marginTop: '10px',
  },
  testItem: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: '4px',
  },
  logTable: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  logHeader: {
    display: 'grid',
    gridTemplateColumns: '1fr 1.2fr 1.8fr 1fr 1fr 2.5fr',
    padding: '6px 10px',
    fontSize: '11px',
    fontWeight: 700,
    color: '#475569',
    textTransform: 'uppercase',
  },
  logRow: {
    display: 'grid',
    gridTemplateColumns: '1fr 1.2fr 1.8fr 1fr 1fr 2.5fr',
    padding: '8px 10px',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
    fontSize: '12px',
    alignItems: 'center',
    color: '#0f172a',
  },
  modalOverlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(15, 23, 42, 0.5)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modal: {
    backgroundColor: '#ffffff',
    borderRadius: '8px',
    padding: '18px 20px',
    width: '360px',
    boxShadow: '0 10px 25px rgba(0,0,0,0.15)',
  },
  formGroup: {
    marginBottom: '12px',
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  input: {
    padding: '6px 10px',
    borderRadius: '5px',
    border: '1px solid #cbd5e1',
    fontSize: '13px',
    color: '#0f172a',
    backgroundColor: '#ffffff',
  },
  modalActions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '6px',
    marginTop: '16px',
  },
};

export default App;

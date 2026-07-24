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
} from 'lucide-react';

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
    if (!confirm('Are you sure you want to delete this MCP service?')) return;
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
          <ShieldCheck size={28} color="#4f46e5" />
          <h1 style={styles.title}>MCPPool Gateway Dashboard</h1>
        </div>
        <div style={styles.navTabs}>
          <button
            style={activeTab === 'services' ? styles.tabActive : styles.tab}
            onClick={() => setActiveTab('services')}
          >
            <Layers size={16} /> Services & Account Pools
          </button>
          <button
            style={activeTab === 'logs' ? styles.tabActive : styles.tab}
            onClick={() => setActiveTab('logs')}
          >
            <Activity size={16} /> Live Logs
          </button>
        </div>
      </header>

      {activeTab === 'services' && (
        <main style={styles.grid}>
          {/* Left Panel: Services List */}
          <section style={styles.card}>
            <div style={styles.cardHeaderBetween}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Server size={20} color="#4f46e5" />
                <h2 style={styles.cardTitle}>MCP Services</h2>
              </div>
              <button style={styles.btnPrimary} onClick={() => setShowAddServiceModal(true)}>
                <Plus size={14} /> Add Service
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
                      borderLeft: isSelected ? '4px solid #4f46e5' : '4px solid transparent',
                      backgroundColor: isSelected ? '#f8fafc' : '#ffffff',
                    }}
                    onClick={() => setSelectedService(s)}
                  >
                    <div>
                      <div style={{ fontWeight: 600 }}>{s.name}</div>
                      <div style={{ fontSize: '12px', color: '#64748b' }}>{s.upstream_url}</div>
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
                        {s.status}
                      </span>
                      <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
                        {s.active_keys} / {s.total_keys} Keys
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
                  <h2 style={{ ...styles.cardTitle, fontSize: '18px' }}>{selectedService.name}</h2>
                  <div style={{ fontSize: '13px', color: '#64748b' }}>
                    Upstream: {selectedService.upstream_url}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    style={styles.btnSecondary}
                    onClick={() => handleTestService(selectedService.id)}
                    disabled={testing}
                  >
                    <Play size={14} /> {testing ? 'Testing...' : 'Test Connection'}
                  </button>
                  <button
                    style={styles.btnDanger}
                    onClick={() => handleDeleteService(selectedService.id)}
                  >
                    <Trash2 size={14} /> Delete Service
                  </button>
                </div>
              </div>

              {testResults && (
                <div style={styles.testConsole}>
                  <div style={{ fontWeight: 600, marginBottom: '8px' }}>Connection Test Results</div>
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
              <div style={{ marginTop: '20px' }}>
                <div style={styles.cardHeaderBetween}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Key size={18} color="#4f46e5" />
                    <h3 style={{ fontSize: '15px', margin: 0 }}>Account Pool / API Keys</h3>
                  </div>
                  <button style={styles.btnPrimary} onClick={() => setShowAddKeyModal(true)}>
                    <Plus size={14} /> Add Key
                  </button>
                </div>

                <div style={styles.table}>
                  <div style={styles.tableHeader}>
                    <div>Name</div>
                    <div>Key Mask</div>
                    <div>Status</div>
                    <div>Requests</div>
                    <div>Actions</div>
                  </div>
                  {selectedService.keys.map((k) => (
                    <div key={k.id} style={styles.tableRow}>
                      <div style={{ fontWeight: 600 }}>{k.name}</div>
                      <div style={{ fontFamily: 'monospace', color: '#64748b' }}>{k.key_masked}</div>
                      <div>
                        {k.is_active && !k.quota_exhausted && (
                          <span style={styles.statusActive}>
                            <CheckCircle size={14} /> Active
                          </span>
                        )}
                        {k.quota_exhausted && (
                          <span style={styles.statusExhausted}>
                            <XCircle size={14} /> Exhausted
                          </span>
                        )}
                        {!k.is_active && !k.quota_exhausted && (
                          <span style={styles.statusDegraded}>Paused</span>
                        )}
                      </div>
                      <div>{k.requests_count}</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button
                          style={styles.btnSmall}
                          onClick={() => handleToggleKey(k.id, k.is_active)}
                        >
                          {k.is_active ? 'Pause' : 'Resume'}
                        </button>
                        <button
                          style={{ ...styles.btnSmall, color: '#ef4444' }}
                          onClick={() => handleDeleteKey(k.id)}
                        >
                          Delete
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Activity size={20} color="#4f46e5" />
              <h2 style={styles.cardTitle}>Live Request Logs & Failover Chains</h2>
            </div>
            <button style={styles.btnSecondary} onClick={fetchLogs}>
              <RefreshCw size={14} /> Refresh Logs
            </button>
          </div>

          <div style={styles.logTable}>
            <div style={styles.logHeader}>
              <div>Time</div>
              <div>Service</div>
              <div>Method & Path</div>
              <div>Status</div>
              <div>Duration</div>
              <div>Failover Chain</div>
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
                      color: log.status_code < 400 ? '#22c55e' : '#ef4444',
                      fontWeight: 600,
                    }}
                  >
                    {log.status_code}
                  </span>
                </div>
                <div>{log.duration_ms} ms</div>
                <div style={{ fontSize: '12px', color: '#64748b' }}>
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
            <h3 style={{ marginTop: 0 }}>Add New MCP Service</h3>
            <div style={styles.formGroup}>
              <label>Service Name</label>
              <input
                style={styles.input}
                value={newServiceName}
                onChange={(e) => setNewServiceName(e.target.value)}
                placeholder="e.g. context7-prod"
              />
            </div>
            <div style={styles.formGroup}>
              <label>Upstream Endpoint URL</label>
              <input
                style={styles.input}
                value={newServiceUrl}
                onChange={(e) => setNewServiceUrl(e.target.value)}
                placeholder="https://api.context7.com/mcp"
              />
            </div>
            <div style={styles.formGroup}>
              <label>Provider Type</label>
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
                Cancel
              </button>
              <button style={styles.btnPrimary} onClick={handleCreateService}>
                Save Service
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Key Modal */}
      {showAddKeyModal && (
        <div style={styles.modalOverlay}>
          <div style={styles.modal}>
            <h3 style={{ marginTop: 0 }}>Add Key to Pool</h3>
            <div style={styles.formGroup}>
              <label>Key Name / Alias</label>
              <input
                style={styles.input}
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="e.g. Backup Account Key"
              />
            </div>
            <div style={styles.formGroup}>
              <label>Secret API Key</label>
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
                Cancel
              </button>
              <button style={styles.btnPrimary} onClick={handleAddKey}>
                Add Key
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
    fontFamily: 'Inter, system-ui, Avenir, Helvetica, Arial, sans-serif',
    backgroundColor: '#f8fafc',
    minHeight: '100vh',
    padding: '24px',
    color: '#0f172a',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '24px',
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  title: {
    fontSize: '22px',
    fontWeight: 700,
    margin: 0,
  },
  navTabs: {
    display: 'flex',
    gap: '8px',
  },
  tab: {
    padding: '8px 16px',
    borderRadius: '6px',
    border: 'none',
    backgroundColor: '#e2e8f0',
    color: '#475569',
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  tabActive: {
    padding: '8px 16px',
    borderRadius: '6px',
    border: 'none',
    backgroundColor: '#4f46e5',
    color: '#ffffff',
    fontWeight: 600,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 2.5fr',
    gap: '24px',
  },
  card: {
    backgroundColor: '#ffffff',
    borderRadius: '12px',
    padding: '20px',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  cardHeaderBetween: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
  },
  cardTitle: {
    fontSize: '16px',
    fontWeight: 600,
    margin: 0,
  },
  serviceList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  serviceItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
    cursor: 'pointer',
  },
  table: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '2fr 2fr 1.5fr 1fr 1.5fr',
    padding: '8px 12px',
    fontSize: '12px',
    fontWeight: 600,
    color: '#64748b',
    textTransform: 'uppercase',
  },
  tableRow: {
    display: 'grid',
    gridTemplateColumns: '2fr 2fr 1.5fr 1fr 1.5fr',
    padding: '12px',
    alignItems: 'center',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
  },
  statusActive: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: '#16a34a',
    fontWeight: 600,
    fontSize: '13px',
  },
  statusDegraded: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: '#d97706',
    fontWeight: 600,
    fontSize: '13px',
  },
  statusExhausted: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: '#dc2626',
    fontWeight: 600,
    fontSize: '13px',
  },
  btnPrimary: {
    backgroundColor: '#4f46e5',
    color: '#ffffff',
    border: 'none',
    padding: '8px 14px',
    borderRadius: '6px',
    fontWeight: 600,
    fontSize: '13px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  btnSecondary: {
    backgroundColor: '#f1f5f9',
    color: '#334155',
    border: '1px solid #cbd5e1',
    padding: '8px 14px',
    borderRadius: '6px',
    fontWeight: 600,
    fontSize: '13px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  btnDanger: {
    backgroundColor: '#ef4444',
    color: '#ffffff',
    border: 'none',
    padding: '8px 14px',
    borderRadius: '6px',
    fontWeight: 600,
    fontSize: '13px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  btnSmall: {
    padding: '4px 8px',
    fontSize: '12px',
    borderRadius: '4px',
    border: '1px solid #cbd5e1',
    backgroundColor: '#ffffff',
    cursor: 'pointer',
  },
  testConsole: {
    backgroundColor: '#0f172a',
    color: '#f8fafc',
    padding: '12px',
    borderRadius: '6px',
    fontSize: '13px',
    marginTop: '12px',
  },
  testItem: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: '4px',
  },
  logTable: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  logHeader: {
    display: 'grid',
    gridTemplateColumns: '1fr 1.5fr 2fr 1fr 1fr 3fr',
    padding: '8px 12px',
    fontSize: '12px',
    fontWeight: 600,
    color: '#64748b',
    textTransform: 'uppercase',
  },
  logRow: {
    display: 'grid',
    gridTemplateColumns: '1fr 1.5fr 2fr 1fr 1fr 3fr',
    padding: '10px 12px',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
    fontSize: '13px',
    alignItems: 'center',
  },
  modalOverlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.5)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modal: {
    backgroundColor: '#ffffff',
    borderRadius: '12px',
    padding: '24px',
    width: '400px',
    boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
  },
  formGroup: {
    marginBottom: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  input: {
    padding: '8px 12px',
    borderRadius: '6px',
    border: '1px solid #cbd5e1',
    fontSize: '14px',
  },
  modalActions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: '8px',
    marginTop: '20px',
  },
};

export default App;

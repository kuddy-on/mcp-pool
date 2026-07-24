import React, { useState } from 'react';
import { Server, Key, RefreshCw, CheckCircle, XCircle, ShieldCheck, Activity } from 'lucide-react';

interface KeyStatus {
  id: string;
  name: string;
  status: 'active' | 'exhausted' | 'cooling_down';
  keyMasked: string;
  requestsCount: number;
  lastUsed: string;
}

interface ServiceInfo {
  name: string;
  upstreamUrl: string;
  providerType: string;
  authHeader: string;
  activeKeyId: string;
}

export function App() {
  const [service, setService] = useState<ServiceInfo>({
    name: 'context7',
    upstreamUrl: 'https://api.context7.com/mcp',
    providerType: 'context7',
    authHeader: 'Authorization: Bearer',
    activeKeyId: 'key-2',
  });

  const [keys, setKeys] = useState<KeyStatus[]>([
    {
      id: 'key-1',
      name: 'Primary Account Key',
      status: 'exhausted',
      keyMasked: 'c7_live_...9a8f',
      requestsCount: 1500,
      lastUsed: '10 mins ago (401 Quota Limit)',
    },
    {
      id: 'key-2',
      name: 'Secondary Failover Key',
      status: 'active',
      keyMasked: 'c7_live_...3b2e',
      requestsCount: 420,
      lastUsed: 'Just now',
    },
    {
      id: 'key-3',
      name: 'Backup Pool Key',
      status: 'active',
      keyMasked: 'c7_live_...77c1',
      requestsCount: 0,
      lastUsed: 'Never',
    },
  ]);

  const [logs, setLogs] = useState<string[]>([
    '[SYSTEM] Gateway initialized with 3 keys in rotation pool.',
    '[ROUTER] Request /v1/mcp mapped to default service "context7".',
    '[KEY_POOL] Key key-1 returned 401 Quota Exhausted. Auto-marking invalid.',
    '[KEY_POOL] Rotated to next healthy key: key-2.',
    '[PROXY] Request forwarded successfully using key-2 (Status 200 OK).',
  ]);

  const simulateQuotaExhaustion = () => {
    const activeKeyIndex = keys.findIndex((k) => k.id === service.activeKeyId);
    if (activeKeyIndex === -1) return;

    const currentKey = keys[activeKeyIndex];
    const updatedKeys = [...keys];
    updatedKeys[activeKeyIndex] = {
      ...currentKey,
      status: 'exhausted',
      lastUsed: 'Just now (401 Quota Limit)',
    };

    const nextAvailable = updatedKeys.find((k) => k.status === 'active');

    setKeys(updatedKeys);

    if (nextAvailable) {
      setService((prev) => ({ ...prev, activeKeyId: nextAvailable.id }));
      setLogs((prev) => [
        ...prev,
        `[KEY_POOL] Key ${currentKey.id} returned 401 Quota Exhausted!`,
        `[KEY_POOL] Auto-switched to key: ${nextAvailable.id}.`,
      ]);
    } else {
      setService((prev) => ({ ...prev, activeKeyId: 'none' }));
      setLogs((prev) => [
        ...prev,
        `[KEY_POOL] Key ${currentKey.id} returned 401 Quota Exhausted!`,
        `[ALERT] All API keys in pool are exhausted! Gateway returning 503.`,
      ]);
    }
  };

  const resetKeys = () => {
    setKeys([
      {
        id: 'key-1',
        name: 'Primary Account Key',
        status: 'active',
        keyMasked: 'c7_live_...9a8f',
        requestsCount: 0,
        lastUsed: 'Never',
      },
      {
        id: 'key-2',
        name: 'Secondary Failover Key',
        status: 'active',
        keyMasked: 'c7_live_...3b2e',
        requestsCount: 0,
        lastUsed: 'Never',
      },
      {
        id: 'key-3',
        name: 'Backup Pool Key',
        status: 'active',
        keyMasked: 'c7_live_...77c1',
        requestsCount: 0,
        lastUsed: 'Never',
      },
    ]);
    setService((prev) => ({ ...prev, activeKeyId: 'key-1' }));
    setLogs((prev) => [...prev, '[SYSTEM] Key pool reset. All keys marked as active.']);
  };

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <div style={styles.brand}>
          <ShieldCheck size={28} color="#6366f1" />
          <h1 style={styles.title}>MCPPool Gateway Dashboard</h1>
        </div>
        <div style={styles.badge}>MVP Single-Service Auto-Failover</div>
      </header>

      <main style={styles.grid}>
        {/* Service Config Panel */}
        <section style={styles.card}>
          <div style={styles.cardHeader}>
            <Server size={20} color="#4f46e5" />
            <h2 style={styles.cardTitle}>Upstream Service Config</h2>
          </div>
          <div style={styles.infoGroup}>
            <label style={styles.label}>Service Name</label>
            <div style={styles.value}>{service.name}</div>
          </div>
          <div style={styles.infoGroup}>
            <label style={styles.label}>Upstream Endpoint</label>
            <div style={styles.value}>{service.upstreamUrl}</div>
          </div>
          <div style={styles.infoGroup}>
            <label style={styles.label}>Provider Adapter</label>
            <div style={styles.value}>{service.providerType}</div>
          </div>
          <div style={styles.infoGroup}>
            <label style={styles.label}>Auth Injection</label>
            <div style={styles.value}>{service.authHeader}</div>
          </div>
        </section>

        {/* Key Pool Status Panel */}
        <section style={{ ...styles.card, flex: 2 }}>
          <div style={styles.cardHeaderBetween}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Key size={20} color="#4f46e5" />
              <h2 style={styles.cardTitle}>API Key Pool & Failover Status</h2>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button style={styles.btnDanger} onClick={simulateQuotaExhaustion}>
                Simulate Current Key Quota Exhaustion
              </button>
              <button style={styles.btnSecondary} onClick={resetKeys}>
                <RefreshCw size={14} /> Reset Pool
              </button>
            </div>
          </div>

          <div style={styles.table}>
            <div style={styles.tableHeader}>
              <div>Key Name</div>
              <div>Secret Mask</div>
              <div>Status</div>
              <div>Requests</div>
              <div>Last Activity</div>
            </div>
            {keys.map((k) => {
              const isActive = k.id === service.activeKeyId;
              return (
                <div
                  key={k.id}
                  style={{
                    ...styles.tableRow,
                    backgroundColor: isActive ? '#f0fdf4' : '#ffffff',
                    borderLeft: isActive ? '4px solid #22c55e' : '4px solid transparent',
                  }}
                >
                  <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {k.name}
                    {isActive && <span style={styles.activeTag}>IN USE</span>}
                  </div>
                  <div style={{ fontFamily: 'monospace', color: '#64748b' }}>{k.keyMasked}</div>
                  <div>
                    {k.status === 'active' && (
                      <span style={styles.statusActive}>
                        <CheckCircle size={14} /> Active
                      </span>
                    )}
                    {k.status === 'exhausted' && (
                      <span style={styles.statusExhausted}>
                        <XCircle size={14} /> Quota Exhausted
                      </span>
                    )}
                  </div>
                  <div>{k.requestsCount}</div>
                  <div style={{ fontSize: '13px', color: '#64748b' }}>{k.lastUsed}</div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Live Proxy Activity Logs */}
        <section style={{ ...styles.card, gridColumn: '1 / -1' }}>
          <div style={styles.cardHeader}>
            <Activity size={20} color="#4f46e5" />
            <h2 style={styles.cardTitle}>Live Proxy Logs</h2>
          </div>
          <div style={styles.logConsole}>
            {logs.map((log, index) => (
              <div key={index} style={styles.logLine}>
                {log}
              </div>
            ))}
          </div>
        </section>
      </main>
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
  badge: {
    backgroundColor: '#e0e7ff',
    color: '#3730a3',
    padding: '6px 12px',
    borderRadius: '16px',
    fontSize: '13px',
    fontWeight: 600,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 2fr',
    gap: '24px',
  },
  card: {
    backgroundColor: '#ffffff',
    borderRadius: '12px',
    padding: '20px',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '16px',
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
  infoGroup: {
    marginBottom: '12px',
  },
  label: {
    fontSize: '12px',
    color: '#64748b',
    textTransform: 'uppercase',
    fontWeight: 600,
  },
  value: {
    fontSize: '14px',
    fontWeight: 500,
    color: '#1e293b',
    marginTop: '2px',
  },
  table: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '2fr 1.5fr 1.5fr 1fr 2fr',
    padding: '8px 12px',
    fontSize: '12px',
    fontWeight: 600,
    color: '#64748b',
    textTransform: 'uppercase',
  },
  tableRow: {
    display: 'grid',
    gridTemplateColumns: '2fr 1.5fr 1.5fr 1fr 2fr',
    padding: '12px',
    alignItems: 'center',
    borderRadius: '6px',
    border: '1px solid #e2e8f0',
  },
  activeTag: {
    backgroundColor: '#bbf7d0',
    color: '#166534',
    fontSize: '10px',
    padding: '2px 6px',
    borderRadius: '4px',
    fontWeight: 700,
  },
  statusActive: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
    color: '#16a34a',
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
  btnDanger: {
    backgroundColor: '#ef4444',
    color: '#ffffff',
    border: 'none',
    padding: '8px 14px',
    borderRadius: '6px',
    fontWeight: 600,
    fontSize: '13px',
    cursor: 'pointer',
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
  logConsole: {
    backgroundColor: '#0f172a',
    color: '#38bdf8',
    fontFamily: 'monospace',
    padding: '16px',
    borderRadius: '8px',
    height: '160px',
    overflowY: 'auto',
    fontSize: '13px',
  },
  logLine: {
    marginBottom: '6px',
  },
};

export default App;

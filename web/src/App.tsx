import React, { useEffect, useState } from 'react';
import { Server, Trash2, Play, Layers, Globe, Lock, Users, LogOut, Clock, Plus } from 'lucide-react';
import type {
  UserDTO,
  ServiceResponse,
  RequestLogItem,
  TestResultItem,
  ClientApiKey,
  Lang,
} from './types';
import { translations, TIMEZONES } from './locales';
import { Button } from './components/common/Button';
import { CustomSelect } from './components/common/CustomSelect';
import { StatusBadge } from './components/common/StatusBadge';
import { KeyTable } from './components/services/KeyTable';
import { AddServiceModal } from './components/services/AddServiceModal';
import { AgentGuideCard } from './components/services/AgentGuideCard';
import { LiveLogsTable } from './components/logs/LiveLogsTable';
import { SystemSettingsView } from './components/settings/SystemSettingsView';
import { UserManagementView } from './components/users/UserManagementView';

export default function App() {
  // Auth State
  const [authToken, setAuthToken] = useState<string | null>(
    localStorage.getItem('mcp_auth_token')
  );
  const [currentUser, setCurrentUser] = useState<UserDTO | null>(null);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginErrMsg, setLoginErrMsg] = useState('');

  // UI & i18n
  const [lang, setLang] = useState<Lang>('zh');
  const t = translations[lang];

  // Timezone state (Default read from browser Intl)
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
  const [timeZone, setTimeZone] = useState<string>('Browser (Auto)');

  // Tabs
  const getInitialTab = (): 'services' | 'logs' | 'settings' | 'users' => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'logs' || hash === 'settings' || hash === 'users') return hash;
    return 'services';
  };
  const [activeTab, setActiveTabState] = useState<'services' | 'logs' | 'settings' | 'users'>(
    getInitialTab
  );

  const setActiveTab = (tab: 'services' | 'logs' | 'settings' | 'users') => {
    setActiveTabState(tab);
    window.location.hash = tab;
  };

  // Data states
  const [services, setServices] = useState<ServiceResponse[]>([]);
  const [selectedService, setSelectedService] = useState<ServiceResponse | null>(null);
  const [logs, setLogs] = useState<RequestLogItem[]>([]);
  const [usersList, setUsersList] = useState<UserDTO[]>([]);

  // Settings states
  const [externalUrl, setExternalUrl] = useState('http://localhost:8100');
  const [clientKeys, setClientKeys] = useState<ClientApiKey[]>([]);

  // Modal states
  const [showAddServiceModal, setShowAddServiceModal] = useState(false);
  const [testResults, setTestResults] = useState<TestResultItem[] | null>(null);
  const [testing, setTesting] = useState(false);

  const authHeaders = (): HeadersInit => {
    return authToken ? { Authorization: `Bearer ${authToken}` } : {};
  };

  const checkMe = async () => {
    if (!authToken) return;
    try {
      const res = await fetch('/api/auth/me', { headers: authHeaders() });
      if (res.ok) {
        setCurrentUser(await res.json());
      } else {
        handleLogout();
      }
    } catch {
      handleLogout();
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginErrMsg('');
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      });
      if (res.ok) {
        const data = await res.json();
        setAuthToken(data.token);
        localStorage.setItem('mcp_auth_token', data.token);
        setCurrentUser(data.user);
      } else {
        setLoginErrMsg(t.loginError);
      }
    } catch {
      setLoginErrMsg(t.loginError);
    }
  };

  const handleLogout = () => {
    setAuthToken(null);
    setCurrentUser(null);
    localStorage.removeItem('mcp_auth_token');
  };

  const fetchServices = async () => {
    if (!authToken) return;
    try {
      const res = await fetch('/api/admin/services', { headers: authHeaders() });
      if (res.ok) {
        const data: ServiceResponse[] = await res.json();
        setServices(data);
        if (data.length > 0) {
          if (!selectedService) {
            setSelectedService(data[0]);
          } else {
            const updated = data.find((s) => s.id === selectedService.id);
            setSelectedService(updated || data[0]);
          }
        } else {
          setSelectedService(null);
        }
      }
    } catch (err) {
      console.error('Failed to fetch services', err);
    }
  };

  const fetchLogs = async () => {
    if (!authToken) return;
    try {
      const res = await fetch('/api/admin/requests?limit=50', { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setLogs(data);
      }
    } catch (err) {
      console.error('Failed to fetch logs', err);
    }
  };

  const fetchSettings = async () => {
    if (!authToken) return;
    try {
      const resSet = await fetch('/api/admin/settings', { headers: authHeaders() });
      if (resSet.ok) {
        const dataSet = await resSet.json();
        setExternalUrl(dataSet.gateway_external_url);
      }
      const resKeys = await fetch('/api/admin/client-keys', { headers: authHeaders() });
      if (resKeys.ok) {
        const dataKeys = await resKeys.json();
        setClientKeys(dataKeys);
      }
    } catch (err) {
      console.error('Failed to fetch settings', err);
    }
  };

  const fetchUsers = async () => {
    if (!authToken) return;
    try {
      const res = await fetch('/api/admin/users', { headers: authHeaders() });
      if (res.ok) {
        setUsersList(await res.json());
      }
    } catch (err) {
      console.error('Failed to fetch users', err);
    }
  };

  useEffect(() => {
    if (authToken) {
      checkMe();
    }
  }, [authToken]);

  useEffect(() => {
    if (authToken && currentUser) {
      fetchServices();
      fetchLogs();
      fetchSettings();
      if (currentUser.role === 'admin') fetchUsers();

      const interval = setInterval(() => {
        fetchServices();
        fetchLogs();
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [authToken, currentUser]);

  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '');
      if (hash === 'services' || hash === 'logs' || hash === 'settings' || hash === 'users') {
        setActiveTabState(hash);
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleDeleteService = async (serviceId: string) => {
    if (!window.confirm(t.confirmDeleteService)) return;
    try {
      await fetch(`/api/admin/services/${serviceId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      fetchServices();
    } catch (err) {
      console.error('Failed to delete service', err);
    }
  };

  const handleTestService = async () => {
    if (!selectedService) return;
    setTesting(true);
    setTestResults(null);
    try {
      const res = await fetch(`/api/admin/services/${selectedService.id}/test`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (res.ok) {
        const results = await res.json();
        setTestResults(results);
      }
    } catch (err) {
      console.error('Failed to test service', err);
    } finally {
      setTesting(false);
    }
  };

  // If not logged in, render Login Page
  if (!authToken) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          backgroundColor: '#f1f5f9',
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        }}
      >
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: '12px',
            padding: '32px',
            width: '360px',
            boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1)',
            border: '1px solid #e2e8f0',
          }}
        >
          <div style={{ textAlign: 'center', marginBottom: '24px' }}>
            <div
              style={{
                width: '48px',
                height: '48px',
                backgroundColor: '#e0e7ff',
                borderRadius: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 12px auto',
              }}
            >
              <Layers size={24} color="#4f46e5" />
            </div>
            <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
              {t.loginTitle}
            </h2>
          </div>
          {loginErrMsg && (
            <div
              style={{
                backgroundColor: '#fef2f2',
                color: '#991b1b',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '13px',
                marginBottom: '16px',
                border: '1px solid #fecaca',
              }}
            >
              {loginErrMsg}
            </div>
          )}
          <form onSubmit={handleLogin}>
            <div style={{ marginBottom: '14px' }}>
              <label
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  color: '#475569',
                  display: 'block',
                  marginBottom: '4px',
                }}
              >
                {t.labelUsername}
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
                value={loginUsername}
                onChange={(e) => setLoginUsername(e.target.value)}
                autoComplete="off"
              />
            </div>
            <div style={{ marginBottom: '16px' }}>
              <label
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  color: '#475569',
                  display: 'block',
                  marginBottom: '4px',
                }}
              >
                {t.labelPassword}
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
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                autoComplete="off"
              />
            </div>
            <Button type="submit" variant="primary" style={{ width: '100%' }}>
              {t.btnLogin}
            </Button>
          </form>
        </div>
      </div>
    );
  }

  const langOptions = [
    { label: '中文', value: 'zh' },
    { label: 'English', value: 'en' },
  ];

  const tzOptions = TIMEZONES.map((tz) => ({ label: tz, value: tz }));

  return (
    <div
      style={{
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        backgroundColor: '#f1f5f9',
        minHeight: '100vh',
        color: '#0f172a',
        padding: '16px 24px',
      }}
    >
      {/* Top Navbar */}
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '20px',
          paddingBottom: '12px',
          borderBottom: '1px solid #cbd5e1',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              backgroundColor: '#4f46e5',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#ffffff',
            }}
          >
            <Layers size={18} />
          </div>
          <div>
            <h1 style={{ fontSize: '18px', fontWeight: 700, margin: 0, color: '#0f172a' }}>
              {t.title}
            </h1>
          </div>
        </div>

        {/* Header Controls: Timezone, Language & Logout */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Clock size={14} color="#64748b" />
            <CustomSelect
              options={tzOptions}
              value={timeZone}
              onChange={(val) => setTimeZone(val)}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Globe size={14} color="#64748b" />
            <CustomSelect
              options={langOptions}
              value={lang}
              onChange={(val) => setLang(val as Lang)}
            />
          </div>

          {currentUser && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginLeft: '8px' }}>
              <span
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  color: '#334155',
                  backgroundColor: '#e2e8f0',
                  padding: '4px 8px',
                  borderRadius: '4px',
                }}
              >
                {currentUser.username} ({currentUser.role})
              </span>
              <Button variant="secondary" onClick={handleLogout}>
                <LogOut size={12} /> {t.logout}
              </Button>
            </div>
          )}
        </div>
      </header>

      {/* Tabs Navigation */}
      <nav style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        <Button
          variant={activeTab === 'services' ? 'primary' : 'secondary'}
          onClick={() => setActiveTab('services')}
        >
          <Server size={14} /> {t.servicesTab}
        </Button>
        <Button
          variant={activeTab === 'logs' ? 'primary' : 'secondary'}
          onClick={() => setActiveTab('logs')}
        >
          <Clock size={14} /> {t.logsTab}
        </Button>
        <Button
          variant={activeTab === 'settings' ? 'primary' : 'secondary'}
          onClick={() => setActiveTab('settings')}
        >
          <Lock size={14} /> {t.settingsTab}
        </Button>
        {currentUser?.role === 'admin' && (
          <Button
            variant={activeTab === 'users' ? 'primary' : 'secondary'}
            onClick={() => setActiveTab('users')}
          >
            <Users size={14} /> {t.usersTab}
          </Button>
        )}
      </nav>

      {/* Main Tab Views */}
      {activeTab === 'services' && (
        <main
          style={{
            display: 'grid',
            gridTemplateColumns: '300px 1fr',
            gap: '16px',
          }}
        >
          {/* Services List Panel */}
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
              <h2 style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
                {t.mcpServices}
              </h2>
              <Button variant="primary" onClick={() => setShowAddServiceModal(true)}>
                <Plus size={12} /> {t.addService}
              </Button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {services.map((s) => {
                const isSelected = selectedService?.id === s.id;
                return (
                  <div
                    key={s.id}
                    onClick={() => setSelectedService(s)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: '6px',
                      border: isSelected ? '2px solid #4f46e5' : '1px solid #e2e8f0',
                      backgroundColor: isSelected ? '#f5f3ff' : '#ffffff',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <span style={{ fontWeight: 600, fontSize: '13px', color: '#0f172a' }}>
                        {s.name}
                      </span>
                      <StatusBadge status={s.status} />
                    </div>
                    <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>
                      {s.active_keys} / {s.total_keys} {t.keysCount}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Selected Service Detail Panel */}
          {selectedService ? (
            <section style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <AgentGuideCard
                selectedService={selectedService}
                externalUrl={externalUrl}
                t={t}
              />

              <div
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
                  <div>
                    <h2 style={{ fontSize: '16px', fontWeight: 700, margin: 0, color: '#0f172a' }}>
                      {selectedService.name}
                    </h2>
                    <div
                      style={{
                        fontSize: '12px',
                        color: '#64748b',
                        marginTop: '2px',
                        fontFamily: 'monospace',
                      }}
                    >
                      {t.upstream}: {selectedService.upstream_url}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <Button variant="secondary" onClick={handleTestService} disabled={testing}>
                      <Play size={12} /> {testing ? t.testing : t.testConnection}
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() => handleDeleteService(selectedService.id)}
                    >
                      <Trash2 size={12} /> {t.deleteService}
                    </Button>
                  </div>
                </div>

                {/* Connection Test Results */}
                {testResults && (
                  <div
                    style={{
                      backgroundColor: '#f8fafc',
                      borderRadius: '6px',
                      padding: '10px 12px',
                      marginBottom: '16px',
                      border: '1px solid #e2e8f0',
                    }}
                  >
                    <div
                      style={{
                        fontSize: '12px',
                        fontWeight: 600,
                        color: '#334155',
                        marginBottom: '6px',
                      }}
                    >
                      {t.testResults}
                    </div>
                    {testResults.map((r, i) => (
                      <div
                        key={i}
                        style={{
                          fontSize: '12px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          marginBottom: '4px',
                        }}
                      >
                        <StatusBadge status={r.success ? 'active' : 'exhausted'} />
                        <span style={{ fontWeight: 600 }}>{r.step}:</span>
                        <span>{r.message}</span>
                        <span style={{ color: '#64748b', fontSize: '11px' }}>
                          ({r.duration_ms} ms)
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Key Pool Table */}
                <KeyTable
                  service={selectedService}
                  t={t}
                  authHeaders={authHeaders}
                  fetchServices={fetchServices}
                />
              </div>
            </section>
          ) : (
            <div
              style={{
                backgroundColor: '#ffffff',
                borderRadius: '8px',
                padding: '24px',
                textAlign: 'center',
                color: '#64748b',
              }}
            >
              No service selected
            </div>
          )}
        </main>
      )}

      {activeTab === 'logs' && (
        <LiveLogsTable
          logs={logs}
          t={t}
          timeZone={timeZone}
          browserTz={browserTz}
          fetchLogs={fetchLogs}
        />
      )}

      {activeTab === 'settings' && (
        <SystemSettingsView
          externalUrl={externalUrl}
          setExternalUrl={setExternalUrl}
          clientKeys={clientKeys}
          currentUser={currentUser}
          t={t}
          authHeaders={authHeaders}
          fetchSettings={fetchSettings}
        />
      )}

      {activeTab === 'users' && (
        <UserManagementView
          usersList={usersList}
          currentUser={currentUser}
          t={t}
          authHeaders={authHeaders}
          fetchUsers={fetchUsers}
        />
      )}

      {/* Add Service Modal */}
      <AddServiceModal
        isOpen={showAddServiceModal}
        onClose={() => setShowAddServiceModal(false)}
        t={t}
        authHeaders={authHeaders}
        fetchServices={fetchServices}
      />
    </div>
  );
}

import { useEffect, useState } from 'react';

import { LoginScreen } from './components/auth/LoginScreen';
import { DashboardHeader } from './components/layout/DashboardHeader';
import { PrimaryNav } from './components/layout/PrimaryNav';
import { LiveLogsTable } from './components/logs/LiveLogsTable';
import { ServicesView } from './components/services/ServicesView';
import { SystemSettingsView } from './components/settings/SystemSettingsView';
import { UserManagementView } from './components/users/UserManagementView';
import { useAuth } from './hooks/useAuth';
import { type DashboardTab, useDashboardData } from './hooks/useDashboardData';
import { translations } from './locales';
import type { Lang } from './types';

const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';

function initialTab(): DashboardTab {
  const hash = window.location.hash.slice(1);
  return ['logs', 'settings', 'users'].includes(hash) ? hash as DashboardTab : 'services';
}

export default function App() {
  const [lang, setLang] = useState<Lang>('zh');
  const [timeZone, setTimeZone] = useState('Browser (Auto)');
  const [activeTab, setActiveTab] = useState<DashboardTab>(initialTab);
  const t = translations[lang];
  const auth = useAuth(t.loginError);
  const data = useDashboardData(auth.authToken, auth.currentUser, activeTab);

  useEffect(() => {
    const syncHash = () => setActiveTab(initialTab());
    window.addEventListener('hashchange', syncHash);
    return () => window.removeEventListener('hashchange', syncHash);
  }, []);

  useEffect(() => {
    if (auth.currentUser && auth.currentUser.role !== 'admin' && activeTab === 'users') {
      setActiveTab('services');
      window.location.hash = 'services';
    }
  }, [activeTab, auth.currentUser]);

  const navigate = (tab: DashboardTab) => {
    setActiveTab(tab);
    window.location.hash = tab;
  };

  if (!auth.authToken) {
    return <LoginScreen t={t} error={auth.loginError} onLogin={auth.login} />;
  }

  return (
    <div className="app-shell">
      <DashboardHeader
        title={t.title}
        lang={lang}
        setLang={setLang}
        timeZone={timeZone}
        setTimeZone={setTimeZone}
        user={auth.currentUser}
        logoutLabel={t.logout}
        onLogout={() => void auth.logout()}
      />
      <PrimaryNav
        active={activeTab}
        isAdmin={auth.currentUser?.role === 'admin'}
        t={t}
        onChange={navigate}
      />
      <div className="app-content">
        {data.dataError ? <div className="form-error data-error" role="alert">{data.dataError}</div> : null}
        {activeTab === 'services' && auth.authToken ? (
          <ServicesView
            services={data.services}
            selected={data.selectedService}
            selectService={data.setSelectedId}
            token={auth.authToken}
            externalUrl={data.externalUrl}
            t={t}
            refresh={() => void data.fetchServices()}
          />
        ) : null}
        {activeTab === 'logs' ? (
          <LiveLogsTable
            logs={data.logs}
            t={t}
            timeZone={timeZone}
            browserTz={browserTimeZone}
            fetchLogs={() => void data.fetchLogs()}
          />
        ) : null}
        {activeTab === 'settings' ? (
          <SystemSettingsView
            externalUrl={data.externalUrl}
            setExternalUrl={data.setExternalUrl}
            clientKeys={data.clientKeys}
            currentUser={auth.currentUser}
            t={t}
            token={auth.authToken}
            fetchSettings={() => void data.fetchSettings()}
          />
        ) : null}
        {activeTab === 'users' && auth.currentUser?.role === 'admin' ? (
          <UserManagementView
            usersList={data.users}
            currentUser={auth.currentUser}
            t={t}
            token={auth.authToken}
            fetchUsers={() => void data.fetchUsers()}
          />
        ) : null}
      </div>
    </div>
  );
}

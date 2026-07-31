import { useCallback, useEffect, useMemo, useState } from 'react';

import { apiRequest } from '../api/client';
import type { ClientApiKey, RequestLogItem, ServiceResponse, UserDTO } from '../types';

export type DashboardTab = 'services' | 'logs' | 'settings' | 'users';

export function useDashboardData(token: string | null, user: UserDTO | null, activeTab: DashboardTab) {
  const [services, setServices] = useState<ServiceResponse[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [logs, setLogs] = useState<RequestLogItem[]>([]);
  const [users, setUsers] = useState<UserDTO[]>([]);
  const [externalUrl, setExternalUrl] = useState('http://localhost:8100');
  const [clientKeys, setClientKeys] = useState<ClientApiKey[]>([]);
  const [dataError, setDataError] = useState('');
  const capture = useCallback(async (task: () => Promise<void>) => {
    try {
      await task();
      setDataError('');
    } catch (error) {
      setDataError(error instanceof Error ? error.message : 'Unable to load dashboard data');
    }
  }, []);
  const selectedService = useMemo(
    () => services.find((service) => service.id === selectedId) ?? services[0] ?? null,
    [selectedId, services],
  );
  const fetchServices = useCallback(async () => {
    if (!token) return;
    await capture(async () => {
      const data = await apiRequest<ServiceResponse[]>('/api/admin/services', token);
      setServices(data);
      setSelectedId((current) =>
        current && data.some((service) => service.id === current) ? current : data[0]?.id ?? null,
      );
    });
  }, [capture, token]);
  const fetchLogs = useCallback(async () => {
    if (!token) return;
    await capture(async () => {
      setLogs(await apiRequest<RequestLogItem[]>('/api/admin/requests?limit=50', token));
    });
  }, [capture, token]);
  const fetchSettings = useCallback(async () => {
    if (!token) return;
    await capture(async () => {
      const settings = await apiRequest<{ gateway_external_url: string }>(
        '/api/admin/settings',
        token,
      );
      setExternalUrl(settings.gateway_external_url);
      if (user?.role === 'admin') {
        setClientKeys(await apiRequest<ClientApiKey[]>('/api/admin/client-keys', token));
      } else {
        setClientKeys([]);
      }
    });
  }, [capture, token, user?.role]);
  const fetchUsers = useCallback(async () => {
    if (!token || user?.role !== 'admin') return;
    await capture(async () => {
      setUsers(await apiRequest<UserDTO[]>('/api/admin/users', token));
    });
  }, [capture, token, user?.role]);
  useEffect(() => {
    if (!token || !user) return;
    void fetchServices();
    void fetchSettings();
  }, [fetchServices, fetchSettings, token, user]);
  useEffect(() => {
    if (!token || !user) return;
    const refresh = () => {
      if (document.visibilityState === 'hidden') return;
      if (activeTab === 'services') void fetchServices();
      if (activeTab === 'logs') void fetchLogs();
      if (activeTab === 'settings') void fetchSettings();
      if (activeTab === 'users') void fetchUsers();
    };
    refresh();
    if (!['services', 'logs'].includes(activeTab)) return;
    const interval = window.setInterval(refresh, 5000);
    return () => window.clearInterval(interval);
  }, [activeTab, fetchLogs, fetchServices, fetchSettings, fetchUsers, token, user]);
  return {
    services, selectedService, setSelectedId, logs, users, externalUrl, setExternalUrl,
    clientKeys, dataError, fetchServices, fetchLogs, fetchSettings, fetchUsers,
  };
}

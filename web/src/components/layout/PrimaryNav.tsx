import type { ComponentType } from 'react';
import { Clock, Lock, Server, Users } from 'lucide-react';

import type { DashboardTab } from '../../hooks/useDashboardData';
import { Button } from '../common/Button';

interface Props { active: DashboardTab; isAdmin: boolean; t: Record<string, string>; onChange: (tab: DashboardTab) => void; }
export function PrimaryNav({ active, isAdmin, t, onChange }: Props) {
  const items: Array<[DashboardTab, ComponentType<{ size: number }>, string]> = [
    ['services', Server, t.servicesTab],
    ['logs', Clock, t.logsTab],
    ['settings', Lock, t.settingsTab],
  ];
  if (isAdmin) items.push(['users', Users, t.usersTab]);
  return <nav className="primary-nav" aria-label="Primary">{items.map(([tab, Icon, label]) => (
    <Button key={tab} variant={active === tab ? 'primary' : 'ghost'} onClick={() => onChange(tab)}><Icon size={16} />{label}</Button>
  ))}</nav>;
}

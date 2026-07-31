import { Clock, Globe, Layers, LogOut } from 'lucide-react';

import { TIMEZONES } from '../../locales';
import type { Lang, UserDTO } from '../../types';
import { Button } from '../common/Button';
import { CustomSelect } from '../common/CustomSelect';

interface Props {
  title: string; lang: Lang; setLang: (lang: Lang) => void;
  timeZone: string; setTimeZone: (zone: string) => void;
  user: UserDTO | null; logoutLabel: string; onLogout: () => void;
}
const languages = [{ label: '中文', value: 'zh' }, { label: 'English', value: 'en' }];
const timezones = TIMEZONES.map((zone) => ({ label: zone, value: zone }));

export function DashboardHeader(props: Props) {
  return (
    <header className="topbar">
      <div className="topbar__brand"><div className="brand-mark"><Layers size={18} /></div><h1>{props.title}</h1></div>
      <div className="topbar__controls">
        <div className="control-cluster timezone-control"><Clock size={15} /><CustomSelect options={timezones} value={props.timeZone} onChange={props.setTimeZone} /></div>
        <div className="control-cluster"><Globe size={15} /><CustomSelect options={languages} value={props.lang} onChange={(value) => props.setLang(value as Lang)} /></div>
        {props.user ? <span className="user-chip">{props.user.username}</span> : null}
        <Button variant="secondary" onClick={props.onLogout}><LogOut size={14} /> {props.logoutLabel}</Button>
      </div>
    </header>
  );
}

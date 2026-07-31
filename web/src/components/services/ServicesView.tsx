import { useState } from 'react';
import { ChevronRight, Play, Plus, Server, Trash2 } from 'lucide-react';

import { apiRequest } from '../../api/client';
import type { ServiceResponse, TestResultItem } from '../../types';
import { Button } from '../common/Button';
import { StatusBadge } from '../common/StatusBadge';
import { AddServiceModal } from './AddServiceModal';
import { AgentGuideCard } from './AgentGuideCard';
import { KeyTable } from './KeyTable';

interface Props {
  services: ServiceResponse[];
  selected: ServiceResponse | null;
  selectService: (id: string) => void;
  token: string;
  externalUrl: string;
  t: Record<string, string>;
  refresh: () => void;
}

export function ServicesView(props: Props) {
  const [addOpen, setAddOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const [results, setResults] = useState<TestResultItem[] | null>(null);
  const selected = props.selected;

  const testService = async () => {
    if (!selected) return;
    setTesting(true);
    setResults(null);
    try {
      setResults(await apiRequest<TestResultItem[]>(
        `/api/admin/services/${selected.id}/test`,
        props.token,
        { method: 'POST' },
      ));
    } finally {
      setTesting(false);
    }
  };

  const deleteService = async () => {
    if (!selected || !window.confirm(props.t.confirmDeleteService)) return;
    await apiRequest<{ status: string }>(
      `/api/admin/services/${selected.id}`,
      props.token,
      { method: 'DELETE' },
    );
    props.refresh();
  };

  return (
    <>
      <main className="services-workspace">
        <aside className="service-rail">
          <div className="service-rail__header">
            <div><span className="section-kicker">{props.t.servicesTab}</span><strong>{props.t.mcpServices}</strong></div>
            <Button variant="primary" onClick={() => setAddOpen(true)}><Plus size={14} />{props.t.addService}</Button>
          </div>
          <div className="service-list">
            {props.services.map((service) => (
              <button
                key={service.id}
                className={`service-list__item ${selected?.id === service.id ? 'is-selected' : ''}`}
                onClick={() => props.selectService(service.id)}
              >
                <span className="service-avatar">{service.name.slice(0, 1).toUpperCase()}</span>
                <span className="service-list__copy">
                  <strong>{service.name}</strong>
                  <small>{service.upstream_url}</small>
                  <StatusBadge status={service.status} labels={{ active: props.t.statusActive, degraded: 'Degraded' }} />
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
            {props.services.length === 0 ? (
              <div className="empty-state"><Server size={24} /><span>{props.t.mcpServices}</span></div>
            ) : null}
          </div>
        </aside>

        <section className="service-detail">
          {selected ? (
            <>
              <div className="service-hero">
                <div className="service-hero__identity">
                  <span className="service-avatar service-avatar--large">{selected.name.slice(0, 1).toUpperCase()}</span>
                  <div><h2>{selected.name}</h2><StatusBadge status={selected.status} labels={{ active: props.t.statusActive }} /></div>
                </div>
                <div className="service-hero__actions">
                  <Button variant="secondary" onClick={testService} disabled={testing}><Play size={14} />{testing ? props.t.testing : props.t.testConnection}</Button>
                  <Button variant="danger-small" onClick={deleteService}><Trash2 size={14} />{props.t.deleteService}</Button>
                </div>
                <dl className="service-meta">
                  <div><dt>{props.t.upstream}</dt><dd>{selected.upstream_url}</dd></div>
                  <div><dt>{props.t.labelProviderType}</dt><dd>{selected.provider_type}</dd></div>
                  <div><dt>{props.t.keysCount}</dt><dd>{selected.active_keys} / {selected.total_keys}</dd></div>
                </dl>
              </div>
              {results ? <div className="test-results">{results.map((item) => <span key={item.step} className={item.success ? 'is-success' : 'is-error'}>{item.step}: {item.message}</span>)}</div> : null}
              <section className="key-panel">
                <KeyTable service={selected} t={props.t} token={props.token} fetchServices={props.refresh} />
              </section>
              <AgentGuideCard selectedService={selected} externalUrl={props.externalUrl} t={props.t} />
            </>
          ) : (
            <div className="empty-detail"><Server size={28} /><p>{props.t.mcpServices}</p></div>
          )}
        </section>
      </main>
      <AddServiceModal isOpen={addOpen} onClose={() => setAddOpen(false)} t={props.t} token={props.token} fetchServices={props.refresh} />
    </>
  );
}

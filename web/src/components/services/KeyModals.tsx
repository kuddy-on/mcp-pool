import { useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import type { AccountKey } from '../../types';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';

interface SharedProps {
  serviceId: string;
  t: Record<string, string>;
  token: string;
  onSaved: () => void;
}

function Field(props: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const { label, ...inputProps } = props;
  return <label className="field"><span>{label}</span><input {...inputProps} /></label>;
}

export function AddKeyModal(props: SharedProps & { open: boolean; onClose: () => void }) {
  const [name, setName] = useState('');
  const [secret, setSecret] = useState('');
  const [quota, setQuota] = useState('0');
  const save = async () => {
    if (!secret) return;
    await apiRequest(`/api/admin/services/${props.serviceId}/keys`, props.token, {
      method: 'POST',
      body: JSON.stringify({ name: name || 'API Key', secret_key: secret, monthly_quota: Number(quota) || 0 }),
    });
    setName(''); setSecret(''); setQuota('0'); props.onClose(); props.onSaved();
  };
  return (
    <Modal title={props.t.modalAddKeyTitle} isOpen={props.open} onClose={props.onClose}>
      <div className="modal-form">
        <Field label={props.t.labelKeyName} value={name} onChange={(event) => setName(event.target.value)} placeholder={props.t.phKeyName} />
        <Field label={props.t.labelSecretKey} type="password" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder={props.t.phSecretKey} />
        <Field label={props.t.labelMonthlyQuota} type="number" min="0" value={quota} onChange={(event) => setQuota(event.target.value)} />
        <div className="modal-actions"><Button variant="secondary" onClick={props.onClose}>{props.t.btnCancel}</Button><Button variant="primary" onClick={() => void save()}>{props.t.btnAddKey}</Button></div>
      </div>
    </Modal>
  );
}

export function EditKeyModal(props: SharedProps & { item: AccountKey | null; onClose: () => void }) {
  const [name, setName] = useState('');
  const [secret, setSecret] = useState('');
  const [quota, setQuota] = useState('0');
  const [used, setUsed] = useState('0');
  useEffect(() => {
    if (!props.item) return;
    setName(props.item.name); setSecret(''); setQuota(String(props.item.monthly_quota || 0));
    setUsed(String(props.item.used_this_month || 0));
  }, [props.item]);
  const save = async () => {
    if (!props.item) return;
    const body: Record<string, string | number> = {
      name, monthly_quota: Number(quota) || 0, used_this_month: Number(used) || 0,
    };
    if (secret.trim()) body.secret_key = secret.trim();
    await apiRequest(`/api/admin/services/${props.serviceId}/keys/${props.item.id}`, props.token, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
    props.onClose(); props.onSaved();
  };
  return (
    <Modal title={props.t.modalEditKeyTitle} isOpen={Boolean(props.item)} onClose={props.onClose}>
      <div className="modal-form">
        <Field label={props.t.labelKeyName} value={name} onChange={(event) => setName(event.target.value)} />
        <Field label={`${props.t.labelSecretKey} (留空不修改)`} type="password" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="••••••••" />
        <Field label={props.t.labelMonthlyQuota} type="number" min="0" value={quota} onChange={(event) => setQuota(event.target.value)} />
        <Field label={props.t.labelUsedThisMonth} type="number" min="0" value={used} onChange={(event) => setUsed(event.target.value)} />
        <div className="modal-actions"><Button variant="secondary" onClick={props.onClose}>{props.t.btnCancel}</Button><Button variant="primary" onClick={() => void save()}>{props.t.btnSaveService}</Button></div>
      </div>
    </Modal>
  );
}

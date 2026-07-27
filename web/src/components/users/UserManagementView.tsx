import React, { useState } from 'react';
import { Users, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import type { UserDTO } from '../../types';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';
import { CustomSelect } from '../common/CustomSelect';

export interface UserManagementViewProps {
  usersList: UserDTO[];
  currentUser: UserDTO | null;
  t: Record<string, string>;
  authHeaders: () => HeadersInit;
  fetchUsers: () => void;
}

export const UserManagementView: React.FC<UserManagementViewProps> = ({
  usersList,
  currentUser,
  t,
  authHeaders,
  fetchUsers,
}) => {
  const [showAddUserModal, setShowAddUserModal] = useState(false);
  const [newUserName, setNewUserName] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserRole, setNewUserRole] = useState('user');

  const roleOptions = [
    { label: t.roleUser || 'User', value: 'user' },
    { label: t.roleAdmin || 'Admin', value: 'admin' },
  ];

  const handleCreateUser = async () => {
    if (!newUserName || !newUserPassword) return;
    try {
      const res = await fetch('/api/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          username: newUserName,
          password: newUserPassword,
          role: newUserRole,
        }),
      });
      if (res.ok) {
        setShowAddUserModal(false);
        setNewUserName('');
        setNewUserPassword('');
        setNewUserRole('user');
        fetchUsers();
      }
    } catch (err) {
      console.error('Failed to create user', err);
    }
  };

  const handleDeleteUser = async (userId: string) => {
    try {
      await fetch(`/api/admin/users/${userId}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      fetchUsers();
    } catch (err) {
      console.error('Failed to delete user', err);
    }
  };

  return (
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Users size={16} color="#4f46e5" />
          <h2 style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', margin: 0 }}>
            {t.usersManagementTitle}
          </h2>
        </div>
        <Button variant="primary" onClick={() => setShowAddUserModal(true)}>
          <Plus size={12} /> {t.addUser}
        </Button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.5fr 1.5fr 1.2fr',
            padding: '6px 10px',
            fontSize: '11px',
            fontWeight: 700,
            color: '#475569',
            textTransform: 'uppercase',
          }}
        >
          <div>{t.labelUsername}</div>
          <div>{t.thRole}</div>
          <div>{t.thActions}</div>
        </div>
        {usersList.map((usr) => (
          <div
            key={usr.id}
            style={{
              display: 'grid',
              gridTemplateColumns: '1.5fr 1.5fr 1.2fr',
              padding: '8px 10px',
              borderRadius: '6px',
              border: '1px solid #e2e8f0',
              fontSize: '12px',
              alignItems: 'center',
              backgroundColor: '#ffffff',
            }}
          >
            <div style={{ fontWeight: 600, color: '#0f172a' }}>{usr.username}</div>
            <div>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  backgroundColor: usr.role === 'admin' ? '#e0e7ff' : '#f1f5f9',
                  color: usr.role === 'admin' ? '#3730a3' : '#475569',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  fontWeight: 600,
                }}
              >
                {usr.role === 'admin' && <ShieldCheck size={11} />}
                {usr.role === 'admin' ? t.roleAdmin : t.roleUser}
              </span>
            </div>
            <div>
              {currentUser?.id !== usr.id && (
                <Button variant="danger-small" onClick={() => handleDeleteUser(usr.id)}>
                  <Trash2 size={11} /> {t.actionDelete}
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Add User Modal */}
      <Modal
        title={t.addUser}
        isOpen={showAddUserModal}
        onClose={() => setShowAddUserModal(false)}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
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
              value={newUserName}
              onChange={(e) => setNewUserName(e.target.value)}
              placeholder="e.g. alice"
            />
          </div>
          <div>
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
              value={newUserPassword}
              onChange={(e) => setNewUserPassword(e.target.value)}
              placeholder="password"
            />
          </div>
          <div>
            <label
              style={{
                fontSize: '12px',
                fontWeight: 600,
                color: '#475569',
                display: 'block',
                marginBottom: '4px',
              }}
            >
              {t.thRole}
            </label>
            <CustomSelect
              options={roleOptions}
              value={newUserRole}
              onChange={(val) => setNewUserRole(val)}
              style={{ width: '100%' }}
            />
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: '8px',
              marginTop: '8px',
            }}
          >
            <Button variant="secondary" onClick={() => setShowAddUserModal(false)}>
              {t.btnCancel}
            </Button>
            <Button variant="primary" onClick={handleCreateUser}>
              {t.addUser}
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  );
};

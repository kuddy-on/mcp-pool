import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import App from './App';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('App authentication', () => {
  it('logs in, keeps the token tab-scoped, and revokes it on logout', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/auth/login') {
        return jsonResponse({
          token: 'signed-token',
          user: { id: 'admin-1', username: 'admin', role: 'admin' },
        });
      }
      if (url === '/api/auth/me') {
        return jsonResponse({ id: 'admin-1', username: 'admin', role: 'admin' });
      }
      if (url === '/api/admin/settings') {
        return jsonResponse({ gateway_external_url: 'https://gateway.example' });
      }
      if (url === '/api/auth/logout' && init?.method === 'POST') {
        return jsonResponse({ status: 'ok' });
      }
      return jsonResponse([]);
    });
    vi.stubGlobal('fetch', fetchMock);

    const { container } = render(<App />);
    const inputs = container.querySelectorAll('input');
    fireEvent.change(inputs[0], { target: { value: 'admin' } });
    fireEvent.change(inputs[1], { target: { value: 'a-secure-password' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    await screen.findByRole('button', { name: /退出登录/ });
    expect(sessionStorage.getItem('mcp_auth_token')).toBe('signed-token');

    fireEvent.click(screen.getByRole('button', { name: /退出登录/ }));

    await screen.findByText('登录 MCPPool 管理控制台');
    expect(sessionStorage.getItem('mcp_auth_token')).toBeNull();
    await waitFor(() => {
      const logoutCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/auth/logout');
      expect(logoutCall?.[1]?.method).toBe('POST');
      expect(new Headers(logoutCall?.[1]?.headers).get('Authorization')).toBe(
        'Bearer signed-token',
      );
    });
  });

  it('shows a stable error and does not store a token after failed login', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Unauthorized' }, 401)));

    const { container } = render(<App />);
    const inputs = container.querySelectorAll('input');
    fireEvent.change(inputs[0], { target: { value: 'admin' } });
    fireEvent.change(inputs[1], { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    await screen.findByText('用户名或密码错误');
    expect(sessionStorage.getItem('mcp_auth_token')).toBeNull();
  });

  it('does not request or render admin-only data for a regular user', async () => {
    sessionStorage.clear();
    window.location.hash = 'users';
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/auth/login') {
        return jsonResponse({
          token: 'user-token',
          user: { id: 'user-1', username: 'alice', role: 'user' },
        });
      }
      if (url === '/api/admin/settings') {
        return jsonResponse({ gateway_external_url: 'https://gateway.example' });
      }
      if (url === '/api/admin/services') return jsonResponse([]);
      return jsonResponse({ detail: 'Forbidden' }, 403);
    });
    vi.stubGlobal('fetch', fetchMock);

    const { container } = render(<App />);
    const inputs = container.querySelectorAll('input');
    fireEvent.change(inputs[0], { target: { value: 'alice' } });
    fireEvent.change(inputs[1], { target: { value: 'a-secure-password' } });
    fireEvent.click(screen.getByRole('button', { name: '登录' }));

    await screen.findByRole('button', { name: /服务与账号池/ });
    await waitFor(() => expect(window.location.hash).toBe('#services'));
    expect(screen.queryByRole('button', { name: /用户管理/ })).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/admin/client-keys')).toBe(
      false,
    );
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/admin/users')).toBe(false);
    sessionStorage.clear();
    window.location.hash = '';
  });
});

import { useCallback, useEffect, useState } from 'react';

import { ApiError, apiRequest } from '../api/client';
import type { UserDTO } from '../types';

interface LoginResponse {
  token: string;
  user: UserDTO;
}

const TOKEN_KEY = 'mcp_auth_token';

export function useAuth(loginErrorMessage: string) {
  const [authToken, setAuthToken] = useState<string | null>(() => sessionStorage.getItem(TOKEN_KEY));
  const [currentUser, setCurrentUser] = useState<UserDTO | null>(null);
  const [loginError, setLoginError] = useState('');
  const logout = useCallback(async () => {
    const token = authToken;
    setAuthToken(null);
    setCurrentUser(null);
    sessionStorage.removeItem(TOKEN_KEY);
    if (!token) return;
    try {
      await apiRequest<{ status: string }>('/api/auth/logout', token, { method: 'POST' });
    } catch {
      // Local logout remains authoritative when the gateway is unavailable.
    }
  }, [authToken]);
  const login = useCallback(async (username: string, password: string) => {
    setLoginError('');
    try {
      const result = await apiRequest<LoginResponse>('/api/auth/login', null, {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      sessionStorage.setItem(TOKEN_KEY, result.token);
      setAuthToken(result.token);
      setCurrentUser(result.user);
      return true;
    } catch {
      setLoginError(loginErrorMessage);
      return false;
    }
  }, [loginErrorMessage]);
  useEffect(() => {
    if (!authToken || currentUser) return;
    let active = true;
    apiRequest<UserDTO>('/api/auth/me', authToken)
      .then((user) => { if (active) setCurrentUser(user); })
      .catch((error: unknown) => {
        if (!(error instanceof ApiError) || error.status === 401) {
          if (active) void logout();
        }
      });
    return () => { active = false; };
  }, [authToken, currentUser, logout]);
  return { authToken, currentUser, loginError, login, logout };
}

export type Lang = 'zh' | 'en';

export interface UserDTO {
  id: string;
  username: string;
  role: string;
}

export interface AccountKey {
  id: string;
  name: string;
  key_masked: string;
  is_active: boolean;
  quota_exhausted: boolean;
  paused_until: string | null;
  weight: number;
  fail_count: number;
  requests_count: number;
  last_used: string | null;
  monthly_quota: number;
  used_this_month: number;
}

export interface ServiceResponse {
  id: string;
  name: string;
  upstream_url: string;
  provider_type: string;
  auth_header: string;
  auth_prefix: string;
  total_keys: number;
  active_keys: number;
  status: 'active' | 'degraded' | 'unavailable' | string;
  keys: AccountKey[];
}

export interface RequestLogItem {
  id: string;
  service_name: string;
  timestamp: string;
  method: string;
  path: string;
  mcp_method: string | null;
  key_id: string | null;
  key_name: string | null;
  client_key_name: string | null;
  client_ip: string | null;
  status_code: number;
  signal_kind: string;
  duration_ms: number;
  failover_chain: string[];
}

export interface TestResultItem {
  step: string;
  success: boolean;
  message: string;
  duration_ms: number;
}

export interface ClientApiKey {
  id: string;
  name: string;
  api_key_masked: string;
  is_active: boolean;
  created_at: string;
}

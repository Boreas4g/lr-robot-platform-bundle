export type LocalUser = {
  name: string;
  role: string;
  username: string;
};

type AuthResponse = { token: string; user: LocalUser };
type CurrentUserResponse = { user: LocalUser };

const TOKEN_KEY = 'lr-web-token';
const USER_KEY = 'lr-web-user';

export function getAuthToken(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  return window.localStorage.getItem(TOKEN_KEY) || undefined;
}

export function getCurrentUser(): LocalUser | undefined {
  if (typeof window === 'undefined') return undefined;
  const cached = window.localStorage.getItem(USER_KEY);
  if (!cached) return undefined;
  try {
    return JSON.parse(cached) as LocalUser;
  } catch {
    clearSession();
    return undefined;
  }
}

export function storeSession(session: AuthResponse) {
  window.localStorage.setItem(TOKEN_KEY, session.token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(session.user));
}

export function clearSession() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export async function signOut() {
  const token = getAuthToken();
  try {
    if (token) await fetch('/api/v1/auth/logout', {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
    });
  } finally {
    clearSession();
  }
}

export async function signIn(username: string, password: string): Promise<LocalUser> {
  const response = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const payload = (await response.json().catch(() => null)) as
    | AuthResponse
    | { detail?: string }
    | null;
  if (!response.ok || !payload || !('token' in payload)) {
    throw new Error(
      payload && 'detail' in payload && payload.detail
        ? payload.detail
        : `登录失败（${response.status}）`,
    );
  }
  storeSession(payload);
  return payload.user;
}

export async function refreshCurrentUser(): Promise<LocalUser | undefined> {
  const token = getAuthToken();
  if (!token) {
    clearSession();
    return undefined;
  }
  try {
    const response = await fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
    if (response.status === 401) {
      clearSession();
      return undefined;
    }
    if (!response.ok) return getCurrentUser();
    const payload = (await response.json()) as CurrentUserResponse;
    window.localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
    return payload.user;
  } catch {
    return getCurrentUser();
  }
}

export function isMaintainer(user?: LocalUser): boolean {
  return user?.role === '系统管理员' || user?.role === '维护人员';
}

export async function authenticatedFetch(input: RequestInfo | URL, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  const token = getAuthToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(input, { ...options, headers });
  if (response.status === 401) {
    clearSession();
    if (window.location.pathname !== '/login') {
      window.location.replace(`/login?redirect=${encodeURIComponent(window.location.pathname)}`);
    }
  }
  return response;
}

export function websocketAuthProtocols(): string[] {
  const token = getAuthToken();
  return token ? [`lr-auth.${token}`] : [];
}

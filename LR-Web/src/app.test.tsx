import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockHistory = {
  location: { pathname: '/overview/dashboard', search: '', hash: '' },
  replace: vi.fn(),
};

vi.mock('@umijs/max', () => ({
  history: mockHistory,
  Link: ({ children }: { children: unknown }) => children,
  useModel: () => ({ initialState: undefined, setInitialState: vi.fn() }),
}));

vi.mock('./services/libraryRobot', () => ({
  getRobotRealtimeState: () => ({ connected: false }),
  startRobotRealtime: vi.fn(),
  stopRobotRealtime: vi.fn(),
  subscribeRobotRealtime: () => () => undefined,
}));

vi.mock('../config/defaultSettings', () => ({
  default: { navTheme: 'light' },
}));

vi.mock('./services/auth', () => ({
  refreshCurrentUser: vi.fn(),
  getCurrentUser: vi.fn(),
  isMaintainer: vi.fn(() => false),
  signOut: vi.fn(),
}));

describe('app getInitialState', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHistory.location = {
      pathname: '/overview/dashboard',
      search: '',
      hash: '',
    };
  });

  it('redirects an unauthenticated visitor to login', async () => {
    const { getInitialState } = await import('./app');

    const state = await getInitialState();

    expect(state.currentUser).toBeUndefined();
    expect(state.settings).toEqual({ navTheme: 'light' });
    expect(state.settingDrawerOpen).toBe(false);
    expect(await state.fetchUserInfo()).toEqual(state.currentUser);
    expect(mockHistory.replace).toHaveBeenCalledWith('/login?redirect=%2Foverview%2Fdashboard');
  });

  it('loads the identity returned by the authenticated session', async () => {
    const { refreshCurrentUser } = await import('./services/auth');
    const user = { username: 'reader', name: '操作员', role: '图书馆操作员' };
    vi.mocked(refreshCurrentUser).mockResolvedValueOnce(user);
    const { getInitialState } = await import('./app');
    expect((await getInitialState()).currentUser).toEqual(user);
    expect(mockHistory.replace).not.toHaveBeenCalled();
  });
});

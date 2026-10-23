import { describe, expect, it } from 'vitest';
import access from './access';

describe('public and maintenance permissions', () => {
  it('allows an operator to use public modules without debug access', () => {
    const permissions = access({ currentUser: { username: 'reader', name: '操作员', role: '图书馆操作员' } });
    expect(permissions.canDispatch).toBe(true);
    expect(permissions.canAdmin).toBe(false);
    expect(permissions.canDebug).toBe(false);
  });

  it.each(['系统管理员', '维护人员'])('allows %s to access debugging', (role) => {
    expect(access({ currentUser: { username: 'maintainer', name: '维护员', role } }).canDebug).toBe(true);
  });

  it('does not grant capabilities before login', () => {
    expect(Object.values(access(undefined)).every((value) => !value)).toBe(true);
  });
});

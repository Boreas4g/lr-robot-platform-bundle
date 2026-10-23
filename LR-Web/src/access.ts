import { isMaintainer, type LocalUser } from './services/auth';

export default function access(initialState?: { currentUser?: LocalUser }) {
  const user = initialState?.currentUser;
  return {
    canAdmin: user?.role === '系统管理员',
    canDispatch: Boolean(user),
    canMaintain: isMaintainer(user),
    canConfigure: isMaintainer(user),
    canDebug: isMaintainer(user),
  };
}

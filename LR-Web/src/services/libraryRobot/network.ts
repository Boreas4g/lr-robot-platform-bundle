import { apiRequest } from './index';

export type WifiSecurity = 'open' | 'wpa-psk' | 'sae' | 'unsupported';
export type WifiNetwork = { ssid: string; security: WifiSecurity; signal: number; frequency: number };
export type NetworkOperation = {
  id: string; phase: string; interface: string; ssid: string; message: string;
  rollback_at: number; addresses: string[]; local_url: string;
};
export type NetworkStatus = {
  wireless_enabled: boolean; hardware_enabled: boolean; local_url: string; rollback_seconds: number; switch_delay: number;
  devices: { interface: string; managed: boolean; state: number; mode: string; ssid: string; addresses: string[]; hotspots: { uuid: string; ssid: string }[] }[];
  operation: NetworkOperation | null;
};
export type NetworkConnect = {
  request_id: string; interface: string; acknowledged: true;
  ssid?: string; password?: string; security?: Exclude<WifiSecurity, 'unsupported'>; hidden?: boolean; hotspot_uuid?: string;
};
const base = '/api/v1/system/network';
export const getNetworkStatus = () => apiRequest<NetworkStatus>(base, { signal: AbortSignal.timeout(10000) });
export const scanWifi = (name: string, refresh: boolean) => apiRequest<{ networks: WifiNetwork[]; cached: boolean; message: string }>(base + '/scan', {
  method: 'POST', body: JSON.stringify({ interface: name, refresh }), signal: AbortSignal.timeout(20000),
});
export const connectWifi = (body: NetworkConnect) => apiRequest<NetworkOperation>(base + '/connect', {
  method: 'POST', body: JSON.stringify(body), signal: AbortSignal.timeout(25000),
});
export const confirmWifi = (id: string) => apiRequest<NetworkOperation>(base + '/confirm', { method: 'POST', body: JSON.stringify({ id }), signal: AbortSignal.timeout(25000) });

// randomUUID requires HTTPS; getRandomValues is also available on local HTTP.
export function networkRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}
export const isNetworkPending = (operation?: NetworkOperation | null) => Boolean(operation && ['scheduled', 'connecting', 'awaiting_confirmation', 'confirming', 'restoring', 'unknown'].includes(operation.phase));

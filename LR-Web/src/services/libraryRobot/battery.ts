import { useSyncExternalStore } from 'react';
import { apiRequest } from './index';

export type BatteryTelemetry = {
  source: string;
  robotId: string;
  status: 'online' | 'offline';
  percent: number | null;
  lastPercent: number | null;
  capacityAh: number | null;
  nominalVoltageV: number | null;
  remainingAh: number | null;
  consumedAh: number;
  consumedWh: number;
  voltageV: number | null;
  currentA: number | null;
  powerW: number | null;
  updatedAt: string | null;
  calibratedAt: string | null;
  quality: 'estimated' | 'gap' | 'uncalibrated';
  gapSeconds: number;
  sampleCount: number;
  deviceSerial: string | null;
  error: string | null;
};

type BatteryState = { data: BatteryTelemetry | null; connected: boolean };
const empty: BatteryState = { data: null, connected: false };
let state = empty;
let socket: WebSocket | undefined;
let reconnect: ReturnType<typeof setTimeout> | undefined;
let watchdog: ReturnType<typeof setInterval> | undefined;
let lastReceived = 0;
let started = false;
let generation = 0;
const listeners = new Set<() => void>();

function emit(next: BatteryState) {
  state = next;
  for (const listener of listeners) listener();
}

function accept(data: BatteryTelemetry) {
  lastReceived = Date.now();
  emit({ data, connected: true });
}

function offline() {
  if (!state.connected) return;
  emit({ connected: false, data: state.data ? {
    ...state.data, status: 'offline', percent: null, remainingAh: null,
    voltageV: null, currentA: null, powerW: null,
    error: '实时连接中断，正在重连',
  } : null });
}

function realtimeUrl() {
  const configured = process.env.LR_REALTIME_API_ORIGIN?.replace(/^"(.*)"$/, '$1');
  const url = new URL(configured || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = '/api/v1/realtime/battery';
  url.search = '';
  return url.toString();
}

function connect() {
  if (!started) return;
  const current = new WebSocket(realtimeUrl());
  socket = current;
  current.onmessage = (event) => {
    if (socket !== current || !started) return;
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'battery.updated' && ['online', 'offline'].includes(payload.battery?.status)) {
        accept(payload.battery);
      }
    } catch { /* Malformed packets never replace a valid measurement. */ }
  };
  current.onerror = () => current.close();
  current.onclose = () => {
    if (socket !== current) return;
    offline();
    if (started) reconnect = setTimeout(connect, 2000);
  };
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!started && typeof window !== 'undefined') {
    started = true;
    const currentGeneration = ++generation;
    const requestedAt = Date.now();
    void apiRequest<BatteryTelemetry>('/api/v1/power/battery', { cache: 'no-store' })
      .then((data) => {
        if (started && generation === currentGeneration && lastReceived <= requestedAt) accept(data);
      }).catch(() => { /* The socket reconnects independently. */ });
    connect();
    watchdog = setInterval(() => { if (Date.now() - lastReceived > 5000) offline(); }, 1000);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size) {
      started = false;
      generation += 1;
      clearTimeout(reconnect);
      clearInterval(watchdog);
      const previous = socket;
      socket = undefined;
      previous?.close();
      state = empty;
    }
  };
}

export function useBatteryTelemetry() {
  return useSyncExternalStore(subscribe, () => state, () => empty);
}

export async function calibrateBatteryFull() {
  const result = await apiRequest<BatteryTelemetry>('/api/v1/power/battery/calibrate-full', {
    method: 'POST', body: JSON.stringify({ confirmFull: true, confirmUnplugged: true }),
  });
  accept(result);
}

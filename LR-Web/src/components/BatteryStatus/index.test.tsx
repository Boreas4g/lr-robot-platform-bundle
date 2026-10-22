import { cleanup, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import BatteryStatus from './index';

const telemetry = vi.hoisted(() => ({
  data: {
    robotId: 'LR-01',
    status: 'online',
    percent: null as number | null,
    lastPercent: null as number | null,
    updatedAt: null as string | null,
    quality: 'uncalibrated',
  } as {
    robotId: string;
    status: 'online' | 'offline';
    percent: number | null;
    lastPercent: number | null;
    updatedAt: string | null;
    quality: string;
  } | null,
  connected: true,
}));
vi.mock('@/services/libraryRobot/battery', () => ({
  useBatteryTelemetry: () => telemetry,
  calibrateBatteryFull: vi.fn(),
}));
afterEach(() => {
  cleanup();
  telemetry.data = {
    robotId: 'LR-01',
    status: 'online',
    percent: null,
    lastPercent: null,
    updatedAt: null,
    quality: 'uncalibrated',
  };
  telemetry.connected = true;
});
describe('inline robot battery', () => {
  it('shows unknown battery level without extra charging controls', () => {
    render(<BatteryStatus robotId="LR-01" />);
    expect(screen.getByRole('img', { name: '电量未知' })).toBeTruthy();
    expect(screen.getByTestId('battery-percentage').textContent).toBe('—');
  });
  it('keeps a placeholder visible before the first telemetry response', () => {
    telemetry.data = null;
    render(<BatteryStatus robotId="LR-01" />);
    expect(screen.getByRole('button', { name: '等待电量数据' })).toBeTruthy();
    expect(screen.getByTestId('battery-percentage').textContent).toBe('—');
  });
  it('does not attach the USB battery to another robot', () => {
    render(<BatteryStatus robotId="LR-02" />);
    expect(screen.queryByTestId('robot-battery')).toBeNull();
  });
  it('shows the last recorded percentage as stale after connection loss', () => {
    telemetry.connected = false;
    telemetry.data = {
      robotId: 'LR-01',
      status: 'offline',
      percent: null,
      lastPercent: 94.6,
      updatedAt: '2026-10-21T19:10:54.718+00:00',
      quality: 'gap',
    };
    render(<BatteryStatus robotId="LR-01" />);
    expect(screen.getByRole('img', { name: '电量未知' })).toBeTruthy();
    expect(
      screen.getByRole('button', {
        name: /电量数据离线，显示上次记录电量 94.6%/,
      }),
    ).toBeTruthy();
    expect(screen.getByTestId('battery-percentage').textContent).toBe('94.6%*');
  });
  it('shows four segments and a precise numeric estimate during discharge', () => {
    telemetry.data = {
      robotId: 'LR-01',
      status: 'online',
      percent: 82.34,
      lastPercent: 82.34,
      updatedAt: null,
      quality: 'estimated',
    };
    render(<BatteryStatus robotId="LR-01" />);
    expect(screen.getByRole('img', { name: '电池：4/4 格' })).toBeTruthy();
    expect(screen.getByTestId('battery-percentage').textContent).toBe('82.3%');
  });
});

import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import BatteryStatus from './index';

const telemetry = vi.hoisted(() => ({
  data: {
    robotId: 'LR-01',
    status: 'online',
    percent: null as number | null,
    quality: 'uncalibrated',
  },
  connected: true,
}));
vi.mock('@/services/libraryRobot/battery', () => ({
  useBatteryTelemetry: () => telemetry,
  calibrateBatteryFull: vi.fn(),
}));
afterEach(() => {
  cleanup();
  Object.assign(telemetry.data, {
    status: 'online',
    percent: null,
    quality: 'uncalibrated',
  });
  telemetry.connected = true;
});
describe('inline robot battery', () => {
  it('shows unknown battery level without extra charging controls', () => {
    render(<BatteryStatus robotId="LR-01" />);
    expect(screen.getByRole('img', { name: '电量未知' })).toBeTruthy();
    expect(screen.getByTestId('battery-percentage').textContent).toBe('—');
  });
  it('does not attach the USB battery to another robot', () => {
    render(<BatteryStatus robotId="LR-02" />);
    expect(screen.queryByTestId('robot-battery')).toBeNull();
  });
  it('hides a stale percentage on connection loss', () => {
    telemetry.connected = false;
    telemetry.data.percent = 95;
    render(<BatteryStatus robotId="LR-01" />);
    expect(screen.getByRole('img', { name: '电量未知' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '电量数据离线' })).toBeTruthy();
    expect(screen.getByTestId('battery-percentage').textContent).toBe('—');
  });
  it('shows four segments and a precise numeric estimate during discharge', () => {
    Object.assign(telemetry.data, {
      percent: 82.34,
      quality: 'estimated',
    });
    render(<BatteryStatus robotId="LR-01" />);
    expect(screen.getByRole('img', { name: '电池：4/4 格' })).toBeTruthy();
    expect(screen.getByTestId('battery-percentage').textContent).toBe('82.3%');
  });
});

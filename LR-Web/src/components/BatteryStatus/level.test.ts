import { describe, expect, it } from 'vitest';
import { batteryLevel } from './level';
describe('four-quarter battery display', () => {
  it.each([
    [0, 0],
    [0.1, 1],
    [25, 1],
    [25.1, 2],
    [50, 2],
    [50.1, 3],
    [75, 3],
    [75.1, 4],
    [100, 4],
  ])('shows %s%% as %s segments', (percent, segments) => {
    expect(batteryLevel(percent).segments).toBe(segments);
  });
  it('retains numeric precision independently of segments', () => {
    expect(batteryLevel(83.72)).toMatchObject({
      segments: 4,
      label: '83.7%',
      tone: 'high',
    });
    expect(batteryLevel(24.1).tone).toBe('low');
    expect(batteryLevel(48.5).tone).toBe('medium');
  });
  it('distinguishes unknown from empty battery', () => {
    expect(batteryLevel(null)).toMatchObject({
      segments: 0,
      label: '—',
      tone: 'unknown',
    });
    expect(batteryLevel(Number.NaN).label).toBe('—');
    expect(batteryLevel(0).label).toBe('0.0%');
  });
});

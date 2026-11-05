import { describe, expect, it, vi } from 'vitest';

vi.mock('../../circulation/components/TuningPanel', () => ({
  JOINT_SCALE: 180 / Math.PI,
}));

import { midreturnSteps } from './midreturnSteps';
import { midtakeoutSteps } from './midtakeoutSteps';
import { takeSteps } from './takeSteps';

describe('中位还书调参步骤', () => {
  it('删除机械臂横移并将推杆归位调整到再次推回之前', () => {
    expect(midreturnSteps).toHaveLength(35);
    expect(midreturnSteps[9].title).toBe('推杆归位');
    expect(midreturnSteps[10].title).toBe('再次推回');
    expect(midreturnSteps[10].hint).toContain('当前实际末端位姿');
    expect(midreturnSteps[10].hint).toContain('仅叠加 X 偏移');
    expect(midreturnSteps[14].title).toBe('书本前移');
    expect(midreturnSteps.some((step) => step.title === '机械臂横移')).toBe(
      false,
    );
  });
});

describe('中位取书调参步骤', () => {
  it('将机械臂上移提前到第 10 步并顺延推杆归位与再次推回', () => {
    expect(midtakeoutSteps).toHaveLength(21);
    expect(midtakeoutSteps.slice(0, 9)).toEqual(midreturnSteps.slice(0, 9));
    expect(midtakeoutSteps[9].title).toBe('机械臂上移');
    expect(midtakeoutSteps[9].hint).toContain('仅叠加 Z 偏移');
    expect(midtakeoutSteps[9].fields.map((field) => field.path)).toEqual([
      'raise_z_offset_cm',
      'raise_duration_s',
    ]);
    expect(midtakeoutSteps[10]).toEqual(midreturnSteps[9]);
    expect(midtakeoutSteps[11]).toEqual(midreturnSteps[10]);
    expect(midtakeoutSteps[10].title).toBe('推杆归位');
    expect(midtakeoutSteps[11].title).toBe('再次推回');
    expect(midtakeoutSteps.slice(12)).toEqual(takeSteps.slice(7));
    expect(midtakeoutSteps[12].title).toBe('闭合夹爪');
    expect(midtakeoutSteps[13].title).toBe('抓取后撤');
    expect(midtakeoutSteps[14].fields.map((field) => field.path)).toContain(
      'return_debug_duration_s',
    );
    expect(takeSteps[9].fields[0].fallback).toBe(5);
  });
});

import { describe, expect, it, vi } from 'vitest';

vi.mock('../../circulation/components/TuningPanel', () => ({
  JOINT_SCALE: 180 / Math.PI,
}));

import { midreturnSteps } from './midreturnSteps';
import { midtakeoutSteps } from './midtakeoutSteps';
import { takeSteps } from './takeSteps';

describe('中位取书调参步骤', () => {
  it('按指定边界组合步骤并插入机械臂上移', () => {
    expect(midtakeoutSteps.slice(0, 10)).toEqual(midreturnSteps.slice(0, 10));
    expect(midtakeoutSteps[10].title).toBe('机械臂上移');
    expect(midtakeoutSteps[11]).toEqual(midreturnSteps[10]);
    expect(midtakeoutSteps[10].fields.map((field) => field.path)).toEqual([
      'raise_z_offset_cm',
      'raise_duration_s',
    ]);
    expect(midtakeoutSteps[13].title).toBe('完全闭合夹爪');
    expect(midtakeoutSteps.slice(14)).toEqual(takeSteps.slice(8));
    expect(midtakeoutSteps[15].fields.map((field) => field.path)).toContain(
      'return_debug_duration_s',
    );
  });

  it('下降步骤支持六维偏移', () => {
    const paths = midtakeoutSteps[12].fields.map((field) => field.path);
    expect(paths).toContain('lower_offset_cm');
    expect(paths).toContain('lower_rpy_offset_deg');
    expect(paths).toContain('lower_duration_s');
    expect(midtakeoutSteps[12].fields[0].components).toEqual(['x', 'y', 'z']);
    expect(midtakeoutSteps[12].fields[1].components).toEqual([
      'rx',
      'ry',
      'rz',
    ]);
  });
});

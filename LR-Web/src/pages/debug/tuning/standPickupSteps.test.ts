import { describe, expect, it, vi } from 'vitest';

vi.mock('../../circulation/components/TuningPanel', () => ({
  JOINT_SCALE: 180 / Math.PI,
}));

import { midreturnSteps } from './midreturnSteps';
import { returnSteps } from './returnSteps';

const titles = (steps: typeof returnSteps) => steps.map((step) => step.title);

describe('书槽取书的轻闭与深度调整步骤', () => {
  it('末尾还书在运动到书槽后依次执行轻闭、深度调整和正式闭合', () => {
    expect(returnSteps).toHaveLength(15);
    expect(titles(returnSteps).slice(4, 9)).toEqual([
      '运动到书槽',
      '轻闭夹爪',
      '调整夹书深度',
      '闭合夹爪',
      '回调试位',
    ]);
    expect(returnSteps[5].fields[0].path).toBe('pickup_light_close_deg');
    expect(returnSteps[6].fields.map((field) => field.path)).toEqual([
      'pickup_light_close_down_cm',
      'pickup_light_close_rpy_offset_deg',
    ]);
    expect(returnSteps[6].hint).toContain('当前实际末端位姿');
  });

  it('中位还书复用相同逻辑并保留书槽推杆归位步骤', () => {
    expect(midreturnSteps).toHaveLength(35);
    const slotIndex = titles(midreturnSteps).indexOf('运动到书槽');
    expect(titles(midreturnSteps).slice(slotIndex, slotIndex + 6)).toEqual([
      '运动到书槽',
      '推杆归位',
      '轻闭夹爪（书槽）',
      '调整夹书深度',
      '闭合夹爪（书槽）',
      '回调试位',
    ]);
    expect(midreturnSteps[slotIndex + 2].fields[0].path).toBe(
      'pickup_light_close_deg',
    );
    expect(
      midreturnSteps[slotIndex + 3].fields.map((field) => field.path),
    ).toEqual([
      'pickup_light_close_down_cm',
      'pickup_light_close_rpy_offset_deg',
    ]);
    expect(midreturnSteps[slotIndex + 3].hint).toContain('当前实际末端位姿');
  });
});

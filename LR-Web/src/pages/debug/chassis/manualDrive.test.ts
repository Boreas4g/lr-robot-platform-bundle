import { describe, expect, it } from 'vitest';

import { directionalMotion, withMovingTurnRule } from './manualDrive';

describe('底盘手动控制方式', () => {
  it('差速模式保留原地左右转', () => {
    expect(directionalMotion('left', 0.12, 0.4, false)).toEqual({
      linear: 0,
      angular: 0.4,
    });
    expect(directionalMotion('right', 0.12, 0.4, false)).toEqual({
      linear: 0,
      angular: -0.4,
    });
  });

  it('类阿克曼模式的左右按钮自动带前进', () => {
    expect(directionalMotion('left', 0.12, 0.4, true)).toEqual({
      linear: 0.12,
      angular: 0.4,
    });
    expect(directionalMotion('right', 0.12, 0.4, true)).toEqual({
      linear: 0.12,
      angular: -0.4,
    });
  });

  it('线速度为零时禁止角速度，前进和后退转向不受影响', () => {
    expect(withMovingTurnRule(0, 0.4, true)).toEqual({
      linear: 0,
      angular: 0,
    });
    expect(withMovingTurnRule(0.12, 0.4, true)).toEqual({
      linear: 0.12,
      angular: 0.4,
    });
    expect(withMovingTurnRule(-0.12, -0.4, true)).toEqual({
      linear: -0.12,
      angular: -0.4,
    });
    expect(directionalMotion('left', 0, 0.4, true)).toEqual({
      linear: 0,
      angular: 0,
    });
  });

  it('类阿克曼模式不改变直行和后退按钮', () => {
    expect(directionalMotion('forward', 0.12, 0.4, true)).toEqual({
      linear: 0.12,
      angular: 0,
    });
    expect(directionalMotion('backward', 0.12, 0.4, true)).toEqual({
      linear: -0.12,
      angular: 0,
    });
  });
});

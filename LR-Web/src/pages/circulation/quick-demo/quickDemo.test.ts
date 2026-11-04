import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  QUICK_DEMO_INTERVAL_MS,
  runQuickTakeReturnDemo,
  waitForNextDemoRound,
} from './quickDemo';

afterEach(() => {
  vi.useRealTimers();
});

describe('runQuickTakeReturnDemo', () => {
  it('复用取还步骤并在每轮失能后等待 60 秒', async () => {
    const events: string[] = [];
    let completedRounds = 0;

    await runQuickTakeReturnDemo({
      shouldStop: () => completedRounds >= 2,
      takeout: async () => {
        events.push('takeout');
      },
      returnBook: async () => {
        events.push('return');
      },
      disableArm: async () => {
        completedRounds += 1;
        events.push('disable');
      },
      onWait: () => undefined,
      waitForInterval: async () => {
        events.push(`wait-${QUICK_DEMO_INTERVAL_MS}`);
      },
    });

    expect(events).toEqual([
      'takeout',
      'return',
      'disable',
      'wait-60000',
      'takeout',
      'return',
      'disable',
    ]);
  });

  it('步骤失败时不继续失能或开始下一轮', async () => {
    const disableArm = vi.fn();
    await expect(
      runQuickTakeReturnDemo({
        shouldStop: () => false,
        takeout: async () => {
          throw new Error('取书失败');
        },
        returnBook: async () => undefined,
        disableArm,
        onWait: () => undefined,
      }),
    ).rejects.toThrow('取书失败');
    expect(disableArm).not.toHaveBeenCalled();
  });
});

describe('waitForNextDemoRound', () => {
  it('倒计时完整 60 秒后结束等待', async () => {
    vi.useFakeTimers();
    const updates: number[] = [];
    const waiting = waitForNextDemoRound(
      () => false,
      (remaining) => updates.push(remaining),
    );

    await vi.advanceTimersByTimeAsync(QUICK_DEMO_INTERVAL_MS);
    await waiting;

    expect(updates[0]).toBe(60_000);
    expect(updates.at(-1)).toBe(0);
  });

  it('手动停止可立即打断倒计时', async () => {
    vi.useFakeTimers();
    let stopped = false;
    const waiting = waitForNextDemoRound(
      () => stopped,
      () => undefined,
    );

    await vi.advanceTimersByTimeAsync(1_000);
    stopped = true;
    await vi.advanceTimersByTimeAsync(200);
    await expect(waiting).resolves.toBeUndefined();
  });
});

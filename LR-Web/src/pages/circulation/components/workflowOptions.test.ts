import { beforeEach, describe, expect, it } from 'vitest';

import {
  loadReturnOptions,
  loadTakeoutOptions,
  saveReturnOptions,
  saveTakeoutOptions,
} from './workflowOptions';

beforeEach(() => {
  window.localStorage.clear();
});

describe('快速取还书选项保存', () => {
  it('分别保存并恢复取书和还书选项', () => {
    const takeoutOptions = {
      robotId: 'LR-01',
      bookId: 'BOOK-TAKE',
      annotationId: 'POINT-1',
      manualMode: false,
      manualTarget: { x: 1, y: 2, yaw: 0.5 },
      liftHeightMm: 800,
      destinationSlot: 2,
      takeoutMode: 'mid' as const,
      sendNavigation: false,
    };
    const returnOptions = {
      robotId: 'LR-02',
      bookId: 'BOOK-RETURN',
      annotationId: 'POINT-2',
      manualMode: true,
      manualTarget: { x: 3, y: 4, yaw: -0.5 },
      liftHeightMm: 900,
      sourceSlot: 3,
      returnMode: 'end' as const,
      sendNavigation: true,
    };

    expect(saveTakeoutOptions(takeoutOptions)).toBe(true);
    expect(saveReturnOptions(returnOptions)).toBe(true);

    expect(loadTakeoutOptions()).toEqual(takeoutOptions);
    expect(loadReturnOptions()).toEqual(returnOptions);
  });

  it('没有保存或数据损坏时不恢复选项', () => {
    expect(loadTakeoutOptions()).toBeUndefined();
    expect(loadReturnOptions()).toBeUndefined();

    window.localStorage.setItem('lr-web-quick-takeout-options', '{bad json');
    window.localStorage.setItem('lr-web-quick-return-options', '[]');

    expect(loadTakeoutOptions()).toBeUndefined();
    expect(loadReturnOptions()).toBeUndefined();
  });
});

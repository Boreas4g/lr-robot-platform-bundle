import { beforeEach, describe, expect, it } from 'vitest';

import { loadQuickDemoOptions, saveQuickDemoOptions } from './quickDemoOptions';

beforeEach(() => {
  window.localStorage.clear();
});

describe('快速演示配置保存', () => {
  it('保存并恢复两种演示模式的全部配置', () => {
    const options = {
      demoMode: 'shelf_internal' as const,
      robotId: 'LR-02',
      takeBookId: 'BOOK-1',
      referenceBookId: 'BOOK-2',
      referenceBook2Id: 'BOOK-3',
      shelf1AnnotationId: 'ANN-1',
      shelf2AnnotationId: 'ANN-2',
      takeoutMode: 'mid' as const,
      slot: 3,
      liftHeightMm: 600,
      shelf1LiftHeightMm: 650,
      shelf2LiftHeightMm: 950,
      moveSpeedMps: 0.08,
      enableVehicleAlignment: false,
      liftSpeedLevel: 3,
      intervalSeconds: 45,
    };

    expect(saveQuickDemoOptions(options)).toBe(true);
    expect(loadQuickDemoOptions()).toEqual(options);
  });

  it('没有保存或数据损坏时不恢复配置', () => {
    expect(loadQuickDemoOptions()).toBeUndefined();
    window.localStorage.setItem('lr-web-quick-demo-options', '{bad json');
    expect(loadQuickDemoOptions()).toBeUndefined();
    window.localStorage.setItem('lr-web-quick-demo-options', '[]');
    expect(loadQuickDemoOptions()).toBeUndefined();
  });
});

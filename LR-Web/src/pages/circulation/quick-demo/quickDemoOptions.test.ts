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
      takeBook2Id: 'BOOK-4',
      referenceBookId: 'BOOK-2',
      referenceBook2Id: 'BOOK-3',
      shelf1AnnotationId: 'ANN-1',
      shelf2AnnotationId: 'ANN-2',
      takeoutMode: 'mid' as const,
      book1TakeoutMode: 'mid' as const,
      book2TakeoutMode: 'standard' as const,
      book1ReturnMode: 'end' as const,
      book2ReturnMode: 'mid' as const,
      slot: 3,
      liftHeightMm: 600,
      book1LiftHeightMm: 610,
      book2LiftHeightMm: 620,
      referenceBook1LiftHeightMm: 630,
      referenceBook2LiftHeightMm: 640,
      loopMode: true,
      takeBook3Id: 'BOOK-5',
      takeBook4Id: 'BOOK-7',
      referenceBook3Id: 'BOOK-6',
      referenceBook4Id: 'BOOK-8',
      book3TakeoutMode: 'standard' as const,
      book4TakeoutMode: 'mid' as const,
      book3ReturnMode: 'end' as const,
      book4ReturnMode: 'mid' as const,
      book3LiftHeightMm: 650,
      book4LiftHeightMm: 660,
      referenceBook3LiftHeightMm: 670,
      referenceBook4LiftHeightMm: 680,
      moveSpeedMps: 0.08,
      enableVehicleAlignment: false,
      navigationOnly: true,
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

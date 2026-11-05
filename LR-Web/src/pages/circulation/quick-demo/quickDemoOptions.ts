import type { ReturnMode, TakeoutMode } from '@/services/libraryRobot/types';

export type QuickDemoMode = 'loop' | 'shelf_internal';

export type QuickDemoOptions = {
  demoMode: QuickDemoMode;
  robotId?: string;
  takeBookId?: string;
  takeBook2Id?: string;
  referenceBookId?: string;
  referenceBook2Id?: string;
  shelf1AnnotationId?: string;
  shelf2AnnotationId?: string;
  takeoutMode: TakeoutMode;
  book1TakeoutMode: TakeoutMode;
  book2TakeoutMode: TakeoutMode;
  book1ReturnMode: ReturnMode;
  book2ReturnMode: ReturnMode;
  slot: number;
  liftHeightMm: number;
  book1LiftHeightMm: number;
  book2LiftHeightMm: number;
  referenceBook1LiftHeightMm: number;
  referenceBook2LiftHeightMm: number;
  shelf1LiftHeightMm?: number;
  shelf2LiftHeightMm?: number;
  loopMode: boolean;
  takeBook3Id?: string;
  takeBook4Id?: string;
  referenceBook3Id?: string;
  referenceBook4Id?: string;
  book3TakeoutMode: TakeoutMode;
  book4TakeoutMode: TakeoutMode;
  book3ReturnMode: ReturnMode;
  book4ReturnMode: ReturnMode;
  book3LiftHeightMm: number;
  book4LiftHeightMm: number;
  referenceBook3LiftHeightMm: number;
  referenceBook4LiftHeightMm: number;
  moveSpeedMps: number;
  enableVehicleAlignment: boolean;
  navigationOnly: boolean;
  liftSpeedLevel: number;
  intervalSeconds: number;
};

const QUICK_DEMO_OPTIONS_KEY = 'lr-web-quick-demo-options';

export function loadQuickDemoOptions(): Partial<QuickDemoOptions> | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    const value = JSON.parse(
      window.localStorage.getItem(QUICK_DEMO_OPTIONS_KEY) || 'null',
    );
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return undefined;
    }
    return value as Partial<QuickDemoOptions>;
  } catch {
    return undefined;
  }
}

export function saveQuickDemoOptions(options: QuickDemoOptions): boolean {
  try {
    window.localStorage.setItem(
      QUICK_DEMO_OPTIONS_KEY,
      JSON.stringify(options),
    );
    return true;
  } catch {
    return false;
  }
}

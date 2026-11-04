import type { TakeoutMode } from '@/services/libraryRobot/types';

export type QuickDemoMode = 'loop' | 'shelf_internal';

export type QuickDemoOptions = {
  demoMode: QuickDemoMode;
  robotId?: string;
  takeBookId?: string;
  referenceBookId?: string;
  referenceBook2Id?: string;
  shelf1AnnotationId?: string;
  shelf2AnnotationId?: string;
  takeoutMode: TakeoutMode;
  slot: number;
  liftHeightMm: number;
  shelf1LiftHeightMm: number;
  shelf2LiftHeightMm: number;
  moveSpeedMps: number;
  enableVehicleAlignment: boolean;
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

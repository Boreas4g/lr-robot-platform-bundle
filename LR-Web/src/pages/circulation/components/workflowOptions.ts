import type { ReturnMode, TakeoutMode } from '@/services/libraryRobot/types';

export type WorkflowManualTarget = { x: number; y: number; yaw: number };

export type SavedTakeoutOptions = {
  robotId?: string;
  bookId?: string;
  annotationId?: string;
  manualMode?: boolean;
  manualTarget?: WorkflowManualTarget;
  liftHeightMm?: number;
  destinationSlot?: number;
  takeoutMode?: TakeoutMode;
  sendNavigation?: boolean;
};

export type SavedReturnOptions = {
  robotId?: string;
  bookId?: string;
  annotationId?: string;
  manualMode?: boolean;
  manualTarget?: WorkflowManualTarget;
  liftHeightMm?: number;
  sourceSlot?: number;
  returnMode?: ReturnMode;
  sendNavigation?: boolean;
};

const TAKEOUT_OPTIONS_KEY = 'lr-web-quick-takeout-options';
const RETURN_OPTIONS_KEY = 'lr-web-quick-return-options';

function loadOptions<T>(key: string): Partial<T> | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || 'null');
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return undefined;
    }
    return value as Partial<T>;
  } catch {
    return undefined;
  }
}

function storeOptions(key: string, options: object): boolean {
  try {
    window.localStorage.setItem(key, JSON.stringify(options));
    return true;
  } catch {
    return false;
  }
}

export function loadTakeoutOptions() {
  return loadOptions<SavedTakeoutOptions>(TAKEOUT_OPTIONS_KEY);
}

export function saveTakeoutOptions(options: SavedTakeoutOptions): boolean {
  return storeOptions(TAKEOUT_OPTIONS_KEY, options);
}

export function loadReturnOptions() {
  return loadOptions<SavedReturnOptions>(RETURN_OPTIONS_KEY);
}

export function saveReturnOptions(options: SavedReturnOptions): boolean {
  return storeOptions(RETURN_OPTIONS_KEY, options);
}

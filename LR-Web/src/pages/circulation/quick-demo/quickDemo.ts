export const QUICK_DEMO_INTERVAL_MS = 60_000;
const WAIT_TICK_MS = 200;

type Sleep = (durationMs: number) => Promise<void>;

const sleep: Sleep = (durationMs) =>
  new Promise((resolve) => {
    setTimeout(resolve, durationMs);
  });

export async function waitForNextDemoRound(
  shouldStop: () => boolean,
  onRemaining: (remainingMs: number) => void,
  durationMs = QUICK_DEMO_INTERVAL_MS,
  wait: Sleep = sleep,
): Promise<void> {
  const deadline = Date.now() + durationMs;
  let previousSeconds: number | undefined;
  while (!shouldStop()) {
    const remainingMs = Math.max(0, deadline - Date.now());
    const seconds = Math.ceil(remainingMs / 1000);
    if (seconds !== previousSeconds) {
      onRemaining(remainingMs);
      previousSeconds = seconds;
    }
    if (remainingMs === 0) return;
    await wait(Math.min(WAIT_TICK_MS, remainingMs));
  }
}

export async function runQuickTakeReturnDemo(options: {
  shouldStop: () => boolean;
  takeout: () => Promise<void>;
  returnBook: () => Promise<void>;
  disableArm: () => Promise<void>;
  onWait: (remainingMs: number) => void;
  intervalMs?: number;
  waitForInterval?: (
    shouldStop: () => boolean,
    onRemaining: (remainingMs: number) => void,
  ) => Promise<void>;
}): Promise<void> {
  const waitForInterval =
    options.waitForInterval ??
    ((shouldStop: () => boolean, onRemaining: (remainingMs: number) => void) =>
      waitForNextDemoRound(
        shouldStop,
        onRemaining,
        options.intervalMs ?? QUICK_DEMO_INTERVAL_MS,
      ));
  while (!options.shouldStop()) {
    await options.takeout();
    if (options.shouldStop()) return;
    await options.returnBook();
    if (options.shouldStop()) return;
    await options.disableArm();
    if (!options.shouldStop()) {
      await waitForInterval(options.shouldStop, options.onWait);
    }
  }
}

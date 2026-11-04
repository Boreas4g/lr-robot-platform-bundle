import { useEffect, useState } from 'react';

import { sendMappingJog } from '@/services/libraryRobot';
import { isZeroVelocity, type JogVelocity, ZERO_VELOCITY } from './gamepad';

const CONTROL_KEYS = new Set([
  'w',
  'a',
  's',
  'd',
  'arrowup',
  'arrowdown',
  'arrowleft',
  'arrowright',
]);

export function mappingKeyboardVelocity(
  keys: ReadonlySet<string>,
  controlMode: 'differential' | 'ackermann',
  linearSpeed = 0.2,
  angularSpeed = 0.5,
): JogVelocity {
  const forward = keys.has('w') || keys.has('arrowup');
  const backward = keys.has('s') || keys.has('arrowdown');
  const left = keys.has('a') || keys.has('arrowleft');
  const right = keys.has('d') || keys.has('arrowright');
  const angular = ((left ? 1 : 0) + (right ? -1 : 0)) * angularSpeed;
  let linear = ((forward ? 1 : 0) + (backward ? -1 : 0)) * linearSpeed;
  if (controlMode === 'ackermann' && angular !== 0 && linear === 0) {
    linear = linearSpeed;
  }
  return { linear, angular };
}

function isEditableTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null;
  return Boolean(
    element?.isContentEditable ||
      ['INPUT', 'TEXTAREA', 'SELECT'].includes(element?.tagName ?? ''),
  );
}

export function useMappingKeyboard({
  robotId,
  active,
  controlMode,
}: {
  robotId?: string;
  active: boolean;
  controlMode: 'differential' | 'ackermann';
}) {
  const [output, setOutput] = useState<JogVelocity>(ZERO_VELOCITY);

  useEffect(() => {
    if (!robotId || !active) return;
    const heldKeys = new Set<string>();
    let lastSent: JogVelocity = ZERO_VELOCITY;

    const send = (velocity: JogVelocity) => {
      lastSent = velocity;
      void sendMappingJog(robotId, velocity).catch(() => undefined);
    };
    const update = () => {
      const velocity = mappingKeyboardVelocity(heldKeys, controlMode);
      setOutput((previous) =>
        previous.linear === velocity.linear &&
        previous.angular === velocity.angular
          ? previous
          : velocity,
      );
      if (isZeroVelocity(velocity)) {
        if (!isZeroVelocity(lastSent)) send(ZERO_VELOCITY);
      } else {
        send(velocity);
      }
    };
    const stop = () => {
      heldKeys.clear();
      setOutput(ZERO_VELOCITY);
      if (!isZeroVelocity(lastSent)) send(ZERO_VELOCITY);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === ' ') {
        event.preventDefault();
        stop();
        return;
      }
      if (!CONTROL_KEYS.has(key)) return;
      event.preventDefault();
      heldKeys.add(key);
      update();
    };
    const onKeyUp = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (!CONTROL_KEYS.has(key)) return;
      event.preventDefault();
      heldKeys.delete(key);
      update();
    };
    const onVisibilityChange = () => {
      if (document.hidden) stop();
    };

    const timer = window.setInterval(() => {
      if (heldKeys.size > 0) update();
    }, 100);
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', stop);
    window.addEventListener('pagehide', stop);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', stop);
      window.removeEventListener('pagehide', stop);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      stop();
    };
  }, [robotId, active, controlMode]);

  return { output };
}

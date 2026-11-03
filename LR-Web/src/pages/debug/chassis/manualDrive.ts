export type JogDirection = 'forward' | 'backward' | 'left' | 'right';

export function withMovingTurnRule(
  linear: number,
  angular: number,
  movingTurnOnly: boolean,
) {
  return {
    linear,
    angular: movingTurnOnly && linear === 0 ? 0 : angular,
  };
}

export function directionalMotion(
  direction: JogDirection,
  linearSpeed: number,
  angularSpeed: number,
  movingTurnOnly: boolean,
) {
  switch (direction) {
    case 'forward':
      return { linear: linearSpeed, angular: 0 };
    case 'backward':
      return { linear: -linearSpeed, angular: 0 };
    case 'left':
      return withMovingTurnRule(
        movingTurnOnly ? linearSpeed : 0,
        angularSpeed,
        movingTurnOnly,
      );
    case 'right':
      return withMovingTurnRule(
        movingTurnOnly ? linearSpeed : 0,
        -angularSpeed,
        movingTurnOnly,
      );
  }
}

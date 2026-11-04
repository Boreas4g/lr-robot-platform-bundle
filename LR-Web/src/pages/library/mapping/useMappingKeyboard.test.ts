import { describe, expect, it } from 'vitest';

import { mappingKeyboardVelocity } from './useMappingKeyboard';

describe('mappingKeyboardVelocity', () => {
  it('maps WASD and arrow keys to differential motion', () => {
    expect(mappingKeyboardVelocity(new Set(['w']), 'differential')).toEqual({
      linear: 0.2,
      angular: 0,
    });
    expect(mappingKeyboardVelocity(new Set(['s']), 'differential')).toEqual({
      linear: -0.2,
      angular: 0,
    });
    expect(
      mappingKeyboardVelocity(new Set(['arrowleft']), 'differential'),
    ).toEqual({
      linear: 0,
      angular: 0.5,
    });
    expect(
      mappingKeyboardVelocity(new Set(['arrowright']), 'differential'),
    ).toEqual({
      linear: 0,
      angular: -0.5,
    });
  });

  it('supports combined forward and reverse turns', () => {
    expect(
      mappingKeyboardVelocity(new Set(['w', 'a']), 'differential'),
    ).toEqual({
      linear: 0.2,
      angular: 0.5,
    });
    expect(mappingKeyboardVelocity(new Set(['s', 'd']), 'ackermann')).toEqual({
      linear: -0.2,
      angular: -0.5,
    });
  });

  it('adds forward motion for Ackermann turn-only keys', () => {
    expect(mappingKeyboardVelocity(new Set(['a']), 'ackermann')).toEqual({
      linear: 0.2,
      angular: 0.5,
    });
  });

  it('cancels opposing keys and returns zero for no keys', () => {
    expect(
      mappingKeyboardVelocity(new Set(['w', 's', 'a', 'd']), 'differential'),
    ).toEqual({ linear: 0, angular: 0 });
    expect(mappingKeyboardVelocity(new Set(), 'ackermann')).toEqual({
      linear: 0,
      angular: 0,
    });
  });
});

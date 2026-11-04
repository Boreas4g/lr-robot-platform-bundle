import { describe, expect, it } from 'vitest';

import { brushMapPoints, mapPointFromClient } from './mapEditorUtils';

describe('mapEditorUtils', () => {
  it('creates occupied and erased brush points inside map bounds', () => {
    const points = brushMapPoints(1, 1, 1, 3, 3, 100);
    expect(points).toHaveLength(5);
    expect(points).toContainEqual({ x: 1, y: 1, value: 100 });
    expect(brushMapPoints(0, 0, 1, 3, 3, 0)).toHaveLength(3);
  });

  it('converts browser coordinates to bottom-origin map coordinates', () => {
    expect(
      mapPointFromClient(
        50,
        25,
        { left: 0, top: 0, width: 100, height: 100 },
        200,
        100,
      ),
    ).toEqual({ x: 100, y: 74 });
  });

  it('rejects points outside the image', () => {
    expect(
      mapPointFromClient(
        -1,
        20,
        { left: 0, top: 0, width: 100, height: 100 },
        200,
        100,
      ),
    ).toBeUndefined();
  });
});

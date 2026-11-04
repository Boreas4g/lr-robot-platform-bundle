export type MapEditPoint = { x: number; y: number; value: 0 | 100 };

export function brushMapPoints(
  centerX: number,
  centerY: number,
  radius: number,
  width: number,
  height: number,
  value: 0 | 100,
): MapEditPoint[] {
  const points: MapEditPoint[] = [];
  for (let y = centerY - radius; y <= centerY + radius; y += 1) {
    for (let x = centerX - radius; x <= centerX + radius; x += 1) {
      if (x < 0 || y < 0 || x >= width || y >= height) continue;
      if ((x - centerX) ** 2 + (y - centerY) ** 2 > radius ** 2) continue;
      points.push({ x, y, value });
    }
  }
  return points;
}

export function mapPointFromClient(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
  mapWidth: number,
  mapHeight: number,
) {
  if (rect.width <= 0 || rect.height <= 0) return undefined;
  const x = Math.floor(((clientX - rect.left) / rect.width) * mapWidth);
  const topY = Math.floor(((clientY - rect.top) / rect.height) * mapHeight);
  if (x < 0 || topY < 0 || x >= mapWidth || topY >= mapHeight) return undefined;
  return { x, y: mapHeight - 1 - topY };
}

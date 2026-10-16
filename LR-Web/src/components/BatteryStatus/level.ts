export function batteryLevel(percent: number | null) {
  const value =
    percent !== null && Number.isFinite(percent)
      ? Math.max(0, Math.min(100, percent))
      : null;
  return {
    value,
    segments: value === null ? 0 : Math.ceil(value / 25),
    tone:
      value === null
        ? 'unknown'
        : value <= 25
          ? 'low'
          : value <= 50
            ? 'medium'
            : 'high',
    label: value === null ? '—' : value.toFixed(1) + '%',
  } as const;
}

import { Popconfirm, message, theme } from 'antd';
import { useState } from 'react';
import {
  calibrateBatteryFull,
  useBatteryTelemetry,
} from '@/services/libraryRobot/battery';
import { batteryLevel } from './level';
import { useStyles } from './style';

export function BatteryIcon({ percent }: { percent: number | null }) {
  const { token } = theme.useToken();
  const level = batteryLevel(percent);
  const color =
    level.tone === 'low'
      ? token.colorError
      : level.tone === 'medium'
        ? token.colorWarning
        : level.tone === 'high'
          ? token.colorSuccess
          : token.colorTextQuaternary;
  return (
    <svg
      width="29"
      height="16"
      viewBox="0 0 48 25"
      role="img"
      aria-label={
        percent === null ? '电量未知' : `电池：${level.segments}/4 格`
      }
      style={{ flexShrink: 0 }}
    >
      <rect
        x="1"
        y="2"
        width="42"
        height="21"
        rx="4"
        fill="none"
        stroke={color}
        strokeWidth="1.8"
      />
      <rect x="44.5" y="8" width="3" height="9" rx="1.5" fill={color} />
      {[0, 1, 2, 3].map((segment) => (
        <rect
          key={segment}
          x={5 + segment * 9}
          y="6"
          width="7"
          height="13"
          rx="1.2"
          fill={color}
          opacity={segment < level.segments ? 1 : 0.14}
        />
      ))}
    </svg>
  );
}

export default function BatteryStatus({ robotId }: { robotId: string }) {
  const { styles } = useStyles();
  const { data, connected } = useBatteryTelemetry();
  const [busy, setBusy] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();
  if (!data || data.robotId !== robotId) return null;
  const online = connected && data.status === 'online';
  const percent = online ? data.percent : null;
  const level = batteryLevel(percent);
  const status = !online
    ? '电量数据离线'
    : percent === null
      ? '电量待校准'
      : `剩余电量约 ${level.label}`;
  async function update(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      messageApi.success('电池状态已更新');
    } catch (error) {
      messageApi.error(
        error instanceof Error ? error.message : '更新失败，请重试',
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {contextHolder}
      <Popconfirm
        title="确认电池已充满，且已拔下充电器？"
        description="将以 100% 为基准，重新累计放电量。"
        placement="bottom"
        okText="确认满电"
        cancelText="取消"
        onConfirm={() => update(calibrateBatteryFull)}
        disabled={!online || busy}
      >
        <button
          type="button"
          className={styles.badge}
          aria-label={status}
          title={status + (online ? '，点击校准满电' : '')}
          disabled={!online || busy}
          data-testid="robot-battery"
        >
          <BatteryIcon percent={percent} />
          <span data-testid="battery-percentage">{level.label}</span>
        </button>
      </Popconfirm>
    </>
  );
}

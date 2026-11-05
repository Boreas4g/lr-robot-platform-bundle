import { useState } from 'react';

import type { TuningKind } from '@/services/libraryRobot/tuning';
import TuningPanel, {
  type TuningStepDef,
} from '../../circulation/components/TuningPanel';
import { midreturnSteps } from './midreturnSteps';
import { midtakeoutSteps } from './midtakeoutSteps';
import { returnSteps } from './returnSteps';
import { takeSteps } from './takeSteps';

type TuningFlow = {
  tab: string;
  pageTitle: string;
  pageContent: string;
  steps: TuningStepDef[];
};

const FLOWS: Record<TuningKind, TuningFlow> = {
  take: {
    tab: '取书',
    pageTitle: '取书调参',
    pageContent:
      '调整取书运动计划参数，并按步骤单步执行验证；保存后立即热生效并持久化到机器人本机服务配置文件。',
    steps: takeSteps,
  },
  midtakeout: {
    tab: '中位取书',
    pageTitle: '中位取书调参',
    pageContent:
      '沿用中位还书前 9 步，随后依次执行机械臂上移、推杆归位、再次推回，再从普通取书第 8 步开始闭合夹爪，依次执行抓取后撤、回调试位和书立放置链；机械臂上移按当前末端位置仅叠加 Z 偏移，再次推回按当前末端位置仅叠加 X 偏移；运动参数与书立放置槽位均独立保存并热生效。',
    steps: midtakeoutSteps,
  },
  return: {
    tab: '末尾还书',
    pageTitle: '末尾还书调参',
    pageContent:
      '调整末尾还书运动计划参数，并按步骤单步执行验证；保存后立即热生效并持久化到机器人本机服务配置文件。',
    steps: returnSteps,
  },
  midreturn: {
    tab: '中位还书',
    pageTitle: '中位还书调参',
    pageContent:
      '前半段抓出旧书、晃缝推回并松爪撤出，再从书立取回槽位抓取待还书；后半段沿用末尾还书流程：闭合取书、回调试位、预插入、插入、推回、松爪回抽并回调试位，参数与末尾还书一致；保存后立即热生效并持久化到机器人本机服务配置文件。',
    steps: midreturnSteps,
  },
};

const KINDS = Object.keys(FLOWS) as TuningKind[];

export default function TuningPage() {
  const [kind, setKind] = useState<TuningKind>('take');
  const flow = FLOWS[kind];
  return (
    <TuningPanel
      kind={kind}
      pageTitle={flow.pageTitle}
      pageContent={flow.pageContent}
      steps={flow.steps}
      slotValues={[1, 2, 3, 4, 5]}
      tabList={KINDS.map((key) => ({ key, tab: FLOWS[key].tab }))}
      tabActiveKey={kind}
      onTabChange={(key) => setKind(key as TuningKind)}
    />
  );
}

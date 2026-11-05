import type { TuningStepDef } from '../../circulation/components/TuningPanel';
import { midreturnSteps } from './midreturnSteps';
import { takeSteps } from './takeSteps';

export const midtakeoutSteps: TuningStepDef[] = [
  ...midreturnSteps.slice(0, 9),
  {
    title: '机械臂上移',
    hint: '在推杆归位前，按当前末端位置仅叠加 Z 偏移（正值向上）；X/Y 与姿态保持不变，不重新计算其他位置数据。',
    fields: [
      {
        path: 'raise_z_offset_cm',
        label: '上移偏移 z',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      {
        path: 'raise_duration_s',
        label: '运动时长',
        unit: 's',
        min: 0.5,
        step: 0.5,
        precision: 1,
      },
    ],
  },
  midreturnSteps[9],
  midreturnSteps[10],
  ...takeSteps.slice(7),
];

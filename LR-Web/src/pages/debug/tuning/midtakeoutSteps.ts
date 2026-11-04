import type { TuningStepDef } from '../../circulation/components/TuningPanel';
import { midreturnSteps } from './midreturnSteps';
import { takeSteps } from './takeSteps';

export const midtakeoutSteps: TuningStepDef[] = [
  ...midreturnSteps.slice(0, 10),
  {
    title: '机械臂上移',
    hint: '在再次推回后、推杆归位前，相对当前位置沿 Z 轴上移（正值向上）。',
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
  { ...midreturnSteps[10] },
  {
    ...midreturnSteps[11],
    hint: '以上移后的位姿为基准，设置 X/Y/Z 与 Rx/Ry/Rz 六维偏移，仅影响中位取书。',
    fields: [
      {
        path: 'lower_offset_cm',
        label: '下降位置偏移',
        unit: 'cm',
        components: ['x', 'y', 'z'],
        step: 0.5,
        precision: 1,
      },
      {
        path: 'lower_rpy_offset_deg',
        label: '下降姿态偏移',
        unit: 'deg',
        components: ['rx', 'ry', 'rz'],
        step: 1,
        precision: 1,
      },
      ...midreturnSteps[11].fields.filter(
        (field) => field.path === 'lower_duration_s',
      ),
    ],
  },
  {
    ...midreturnSteps[13],
    title: '完全闭合夹爪',
    hint: '跳过中位还书的「全部张开」，直接完全闭合夹住待取出的书。',
  },
  ...takeSteps.slice(8),
];

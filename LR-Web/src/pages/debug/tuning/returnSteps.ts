import {
  JOINT_SCALE,
  type TuningStepDef,
} from '../../circulation/components/TuningPanel';

const JOINTS = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6'];
const XY = ['x', 'y'];
const RPY = ['rx', 'ry', 'rz'];

const durationField = (path: string, label: string) => ({
  path,
  label,
  unit: 's',
  min: 0.5,
  step: 0.5,
  precision: 1,
});

const openSpeedField = {
  path: 'gripper.open_speed_deg_s',
  label: '开爪速度',
  unit: 'deg·s⁻¹',
  min: 0.1,
  step: 1,
  precision: 1,
};

const openDegField = (path: string, label: string) => ({
  path,
  label,
  unit: 'deg',
  min: 0,
  max: 120,
  step: 1,
  precision: 1,
});

const debugFields = [
  {
    path: 'debug_joint',
    label: '调试位关节角',
    unit: 'deg',
    components: JOINTS,
    scale: JOINT_SCALE,
    step: 1,
    precision: 1,
  },
  durationField('debug_duration_s', '运动时长'),
];

export const returnSteps: TuningStepDef[] = [
  {
    title: '调试位',
    fields: [
      {
        path: 'debug_joint',
        label: '调试位关节角',
        unit: 'deg',
        components: JOINTS,
        scale: JOINT_SCALE,
        step: 1,
        precision: 1,
      },
      durationField('debug_duration_s', '运动时长'),
    ],
  },
  {
    title: '张开夹爪',
    hint: '抓取链开始前张开夹爪。',
    fields: [openDegField('pickup_open_deg', '开爪角度'), openSpeedField],
  },
  {
    title: '推杆归零',
    hint: '在识别目标书前将推杆收回归零，避免推杆遮挡相机或干扰后续取还书动作。',
    fields: [
      {
        path: 'rod_home_deg',
        label: '归零到达位置',
        unit: 'deg',
        min: -100,
        max: 90,
        step: 1,
        precision: 1,
      },
      {
        path: 'rod_speed',
        label: '推杆速度',
        min: 1,
        step: 100,
        precision: 1,
      },
      {
        path: 'rod_acceleration',
        label: '推杆加速度',
        min: 1,
        step: 10,
        precision: 1,
      },
      {
        path: 'rod_tolerance_deg',
        label: '推杆到位容差',
        unit: 'deg',
        min: 0.1,
        step: 0.1,
        precision: 1,
      },
      {
        path: 'rod_timeout_s',
        label: '推杆超时',
        unit: 's',
        min: 1,
        step: 1,
        precision: 0,
      },
    ],
  },
  {
    title: '识别目标书',
    hint: '推杆归零后识别目标书并提供机械臂基座坐标系中的目标点；后续预插入、插入和推回步骤的末端 X/Y 由该目标点叠加各步 XY 偏移得到，Z 使用各步设定的基座绝对高度。',
    fields: [],
  },
  {
    title: '运动到书槽',
    hint: '使用下方「书立取回槽位」卡片中所选格口的 pre_grasp/grasp 位姿与时长：先 MovePByJ 到 pre_grasp，再 MoveL 到 grasp。依赖「准备」选择的格口。',
    fields: [],
  },
  {
    title: '轻闭夹爪',
    hint: '书槽到位后先轻闭夹爪，为后续深度调整提供稳定接触；此步不是最终正式夹紧。',
    fields: [openDegField('pickup_light_close_deg', '轻闭角度')],
  },
  {
    title: '调整夹书深度',
    hint: '读取当前实际末端位姿，叠加 Z 与 Rx/Ry/Rz 偏移，X/Y 保持不变；Z 正值向下、负值向上，运动时长使用所选槽位的 grasp_duration_s。',
    fields: [
      {
        path: 'pickup_light_close_down_cm',
        label: '向下调整量',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      {
        path: 'pickup_light_close_rpy_offset_deg',
        label: '姿态偏移',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
        fallback: [0, 0, 0],
      },
    ],
  },
  {
    title: '闭合夹爪',
    hint: '轻闭并完成深度调整后，正式夹住书立上的待还书。',
    fields: [],
  },
  {
    title: '回调试位',
    hint: '先 MoveL 撤到所选格口的 pre_grasp（撤回时长在槽位卡片编辑），再 MoveJ 回调试位。',
    fields: debugFields,
  },
  {
    title: '预插入位',
    hint: '末端 X = 识别目标 X + 本步 X 偏移，末端 Y = 识别目标 Y + 本步 Y 偏移，末端 Z = 本步绝对 Z；姿态使用本步独立设定的 Rx/Ry/Rz。',
    fields: [
      {
        path: 'pre_insert_xy_offset_m',
        label: '预插入 XY 偏移（相对识别目标）',
        unit: 'm',
        components: XY,
        step: 0.01,
        precision: 3,
      },
      {
        path: 'pre_insert_z_m',
        label: '预插入 Z（基座绝对高度）',
        unit: 'm',
        step: 0.01,
        precision: 3,
      },
      {
        path: 'pre_insert_rpy_deg',
        label: '预插入姿态',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
      },
      durationField('pre_insert_duration_s', '运动时长'),
    ],
  },
  {
    title: '运动到插入位',
    hint: '末端 X/Y = 识别目标 X/Y + 本步 XY 偏移，末端 Z = 本步绝对 Z；从预插入位短直线 MoveL 到位。',
    fields: [
      {
        path: 'insert_xy_offset_m',
        label: '插入 XY 偏移（相对识别目标）',
        unit: 'm',
        components: XY,
        step: 0.01,
        precision: 3,
      },
      {
        path: 'insert_z_m',
        label: '插入 Z（基座绝对高度）',
        unit: 'm',
        step: 0.01,
        precision: 3,
      },
      {
        path: 'insert_rpy_deg',
        label: '插入姿态',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
      },
      durationField('insert_duration_s', '运动时长'),
    ],
  },
  {
    title: '推回书架',
    hint: '末端 X/Y = 识别目标 X/Y + 本步 XY 偏移，末端 Z = 本步绝对 Z；rx/ry/rz 为相对插入姿态的偏移。',
    fields: [
      {
        path: 'push_xy_offset_m',
        label: '推回 XY 偏移（相对识别目标）',
        unit: 'm',
        components: XY,
        step: 0.01,
        precision: 3,
      },
      {
        path: 'push_z_m',
        label: '推回 Z（基座绝对高度）',
        unit: 'm',
        step: 0.01,
        precision: 3,
      },
      {
        path: 'push_rpy_deg',
        label: '推入姿态偏移',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
        fallback: [0, 0, 0],
      },
      durationField('push_duration_s', '运动时长'),
    ],
  },
  {
    title: '张开夹爪',
    hint: '松开书本即可，不是全开。',
    fields: [openDegField('release_open_deg', '松爪开角'), openSpeedField],
  },
  {
    title: '回抽',
    hint: '基于推回位只变 x 把夹爪抽出书架（正值向架外）；姿态固定为 rx 90° / ry 0° / rz 90°，不随插入与推回姿态变化。',
    fields: [
      {
        path: 'retract_x_offset_cm',
        label: '回抽偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('retract_duration_s', '运动时长'),
    ],
  },
  {
    title: '回调试位',
    fields: debugFields,
  },
];

import {
  JOINT_SCALE,
  type TuningStepDef,
} from '../../circulation/components/TuningPanel';

const JOINTS = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6'];
const XY = ['x', 'y'];
const XYZ = ['x', 'y', 'z'];
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

const gripperCloseFields = [
  {
    path: 'gripper.close_deg',
    label: '闭爪角度',
    unit: 'deg',
    min: 0,
    max: 120,
    step: 1,
    precision: 1,
  },
  {
    path: 'gripper.close_speed_deg_s',
    label: '闭爪速度',
    unit: 'deg·s⁻¹',
    min: 0.1,
    step: 1,
    precision: 1,
  },
  {
    path: 'gripper.effort',
    label: '夹持力度',
    min: 0,
    max: 1,
    step: 0.05,
    precision: 2,
  },
  {
    path: 'gripper.kp',
    label: '比例增益 kp',
    min: 0,
    step: 1,
    precision: 1,
  },
  {
    path: 'gripper.kd',
    label: '微分增益 kd',
    min: 0,
    step: 0.5,
    precision: 1,
  },
  {
    path: 'gripper.timeout_s',
    label: '夹爪超时',
    unit: 's',
    min: 1,
    step: 1,
    precision: 0,
  },
  {
    path: 'gripper.carry_effort',
    label: '携持力度',
    min: 0,
    max: 1,
    step: 0.05,
    precision: 2,
  },
  {
    path: 'gripper.carry_lead_deg',
    label: '携持提前角',
    unit: 'deg',
    min: 0,
    step: 0.5,
    precision: 1,
  },
];

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

export const midreturnSteps: TuningStepDef[] = [
  {
    title: '张开夹爪',
    hint: '抓取链开始前张开夹爪。',
    fields: [openDegField('pickup_open_deg', '开爪角度'), openSpeedField],
  },
  {
    title: '推杆归零',
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
    title: '预抓取位',
    hint: '依赖「准备」识别的目标位姿。',
    fields: [
      {
        path: 'pregrasp_offset_cm',
        label: '预抓取偏移',
        unit: 'cm',
        components: XYZ,
        step: 0.5,
        precision: 1,
      },
      {
        path: 'grasp_rpy_deg',
        label: '抓取姿态',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
      },
      durationField('pregrasp_duration_s', '运动时长'),
    ],
  },
  {
    title: '逼近目标',
    hint: '依赖「准备」识别的目标位姿。直线逼近段一般只调 X 分量（沿抓取方向的过渡距离）。',
    fields: [
      {
        path: 'approach_offset_cm',
        label: '逼近偏移',
        unit: 'cm',
        components: XYZ,
        step: 0.5,
        precision: 1,
      },
      durationField('approach_duration_s', '运动时长'),
    ],
  },
  {
    title: '推杆拨书',
    fields: [
      {
        path: 'rod_grasp_deg',
        label: '拨书角度',
        unit: 'deg',
        step: 1,
        precision: 1,
      },
      {
        path: 'rod_speed',
        label: '推杆速度',
        min: 1,
        step: 100,
        precision: 0,
      },
      {
        path: 'rod_acceleration',
        label: '推杆加速度',
        min: 1,
        step: 10,
        precision: 0,
      },
    ],
  },
  {
    title: '精抓',
    fields: [
      {
        path: 'fine_grasp_offset_cm',
        label: '精抓偏移',
        unit: 'cm',
        components: XYZ,
        step: 0.5,
        precision: 1,
      },
      {
        path: 'fine_grasp_rpy_deg',
        label: '精抓姿态',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
      },
      durationField('fine_grasp_duration_s', '运动时长'),
    ],
  },
  {
    title: '闭合夹爪',
    fields: gripperCloseFields,
  },
  {
    title: '推回',
    hint: '把抓出的书沿 X 轴推回架内（负值向架内）。',
    fields: [
      {
        path: 'push_in_x_offset_cm',
        label: '推入偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('push_in_duration_s', '运动时长'),
    ],
  },
  {
    title: '松开一点夹爪',
    hint: '松开书本即可，不是全开。',
    fields: [openDegField('partial_release_deg', '松爪开角'), openSpeedField],
  },
  {
    title: '推杆归位',
    hint: '再次推回前推杆运动到指定位置，为后续下降清出空间；到位容差与超时复用「推杆归零」卡片。',
    fields: [
      {
        path: 'rod_putback_deg',
        label: '归位到达位置',
        unit: 'deg',
        min: -100,
        max: 90,
        step: 1,
        precision: 1,
      },
    ],
  },
  {
    title: '再次推回',
    hint: '读取当前实际末端位姿，仅叠加 X 偏移（负值向架内），Y/Z 与姿态保持不变，不依赖精抓或首次推回参数。',
    fields: [
      {
        path: 're_push_x_offset_cm',
        label: '再推偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('re_push_duration_s', '运动时长'),
    ],
  },
  {
    title: '机械臂下降',
    hint: '相对当前位置沿 Z 轴下降（负值向下）。',
    fields: [
      {
        path: 'lower_z_offset_cm',
        label: '下降偏移 z',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('lower_duration_s', '运动时长'),
    ],
  },
  {
    title: '完全张开夹爪',
    hint: '下降放稳后完全张开，撑开书缝为还书让出空间。',
    fields: [openDegField('full_open_deg', '全开角度'), openSpeedField],
  },
  {
    title: '闭合夹爪',
    hint: '复用「闭合夹爪」卡片的闭爪参数；重新夹紧书本，前移时带着书走。',
    fields: [],
  },
  {
    title: '书本前移',
    hint: '夹爪保持闭合，基于当前末端位置仅叠加 X 偏移（正值向架外），到便于摄像头识别的位置。',
    fields: [
      {
        path: 'carry_forward_x_offset_cm',
        label: '前移偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('carry_forward_duration_s', '运动时长'),
    ],
  },
  {
    title: '松开一点夹爪',
    hint: '书本前移到位后轻微松开卸力，不是全开。',
    fields: [openDegField('partial_release_deg', '松爪开角'), openSpeedField],
  },
  {
    title: '机械臂前移',
    hint: '相对当前位置沿 X 轴前移（正值向架外）。',
    fields: [
      {
        path: 'forward_x_offset_cm',
        label: '前移偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('forward_duration_s', '运动时长'),
    ],
  },
  {
    title: '回调试位（放回后）',
    fields: debugFields,
  },
  {
    title: '张开夹爪（取书槽前）',
    hint: '复用「张开夹爪」卡片的同一个开爪角度。',
    fields: [openDegField('pickup_open_deg', '开爪角度'), openSpeedField],
  },
  {
    title: '识别目标书（插入前）',
    hint: '放回旧书后、书槽取书前，用「准备」的同一书脊模板重新识别目标书；后续预插入位/插入位均基于这次识别的目标点计算。',
    fields: [],
  },
  {
    title: '运动到书槽',
    hint: '使用下方「书立取回槽位」卡片中所选格口的 pre_grasp/grasp 位姿与时长：先 MovePByJ 到 pre_grasp，再 MoveL 到 grasp。依赖「准备」选择的格口。',
    fields: [],
  },
  {
    title: '推杆归位',
    hint: '书槽取书阶段独立参数：运动到书槽后先把推杆收回归位，再轻闭、调整夹书深度并正式夹紧；与前期推杆归位角度互不影响。',
    fields: [
      {
        path: 'pickup_rod_home_deg',
        label: '书槽取书归位位置',
        unit: 'deg',
        min: -100,
        max: 90,
        step: 1,
        precision: 1,
      },
    ],
  },
  {
    title: '轻闭夹爪（书槽）',
    hint: '与末尾还书一致：书槽到位后先轻闭夹爪，为后续深度调整提供稳定接触；此步不是最终正式夹紧。',
    fields: [openDegField('pickup_light_close_deg', '轻闭角度')],
  },
  {
    title: '调整夹书深度',
    hint: '与末尾还书一致：读取当前实际末端位姿，叠加 Z 与 Rx/Ry/Rz 偏移，X/Y 保持不变；Z 正值向下、负值向上，运动时长使用所选槽位的 grasp_duration_s。',
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
    title: '闭合夹爪（书槽）',
    hint: '与末尾还书一致：轻闭并完成深度调整后，正式夹住书立上的待还书。',
    fields: [],
  },
  {
    title: '回调试位',
    hint: '与末尾还书一致：先 MoveL 撤到所选格口的 pre_grasp（撤回时长在槽位卡片编辑），再 MoveJ 回调试位。',
    fields: debugFields,
  },
  {
    title: '预插入位',
    hint: '与末尾还书一致：末端 X = 识别目标 X + 本步 X 偏移，末端 Y = 识别目标 Y + 本步 Y 偏移，末端 Z = 本步绝对 Z；姿态使用本步独立设定的 Rx/Ry/Rz，不再进行 X 自动搜索。',
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
    hint: '与末尾还书一致：末端 X/Y = 识别目标 X/Y + 本步 XY 偏移，末端 Z = 本步绝对 Z；从预插入位短直线 MoveL 到位。',
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
    hint: '与末尾还书一致：末端 X/Y = 识别目标 X/Y + 本步 XY 偏移，末端 Z = 本步绝对 Z；rx/ry/rz 为相对插入姿态的偏移。回抽及其后的压书链保持推回后的高度。',
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
        path: 'push_z_offset_m',
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
    title: '稍微张开夹爪',
    hint: '松开书本即可，不是全开。',
    fields: [openDegField('release_open_deg', '松爪开角'), openSpeedField],
  },
  {
    title: '回抽',
    hint: '基于推回位沿 x 回抽（正值向架外），姿态固定使用与末尾还书一致的 Rx 90° / Ry 0° / Rz 90°，避免继承推回的高角度姿态导致 IK 不可达。',
    fields: [
      {
        path: 'retract_x_offset_cm',
        label: '回抽偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      {
        path: 'retract_rpy_deg',
        label: '回抽姿态',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
        fallback: [90, 0, 90],
      },
      durationField('retract_duration_s', '运动时长'),
    ],
  },

  {
    title: '旋转',
    hint: '基于回抽位转腕：rx/ry/rz 为相对回抽姿态的偏移（默认绕 Y 转 90°），让空爪侧对书脊；z 偏移默认 0，保持回抽高度。',
    fields: [
      {
        path: 'rotate_z_offset_cm',
        label: '旋转偏移 z',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      {
        path: 'rotate_rpy_deg',
        label: '旋转姿态偏移',
        unit: 'deg',
        components: RPY,
        step: 1,
        precision: 1,
        fallback: [0, 90, 0],
      },
      durationField('rotate_duration_s', '运动时长'),
    ],
  },
  {
    title: '压书',
    hint: '旋转后基于旋转位只变 x，把空爪推回架内压平书脊（负值向架内）。',
    fields: [
      {
        path: 'press_x_offset_cm',
        label: '压书偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('press_duration_s', '运动时长'),
    ],
  },
  {
    title: '二次回抽',
    hint: '压书后基于压书位只变 x，把夹爪抽出书架（正值向架外），随后回调试位。',
    fields: [
      {
        path: 'press_retract_x_offset_cm',
        label: '二次回抽偏移 x',
        unit: 'cm',
        step: 0.5,
        precision: 1,
      },
      durationField('press_retract_duration_s', '运动时长'),
    ],
  },
  {
    title: '回调试位（完成）',
    fields: debugFields,
  },
];

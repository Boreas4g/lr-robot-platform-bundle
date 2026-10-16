import {
  ArrowDownOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
  SaveOutlined,
} from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';

import {
  cancelCompleteReturn,
  cancelCompleteTakeout,
  createCompleteReturn,
  createCompleteTakeout,
  getRobotRealtimeState,
  getRobots,
  listBooks,
  pollTasks,
  sendManualJog,
  subscribeRobotRealtime,
} from '@/services/libraryRobot';
import {
  createStressTestTemplate,
  deleteStressTestTemplate,
  listStressTestTemplates,
  type StressTestTemplate,
  type StressTestTemplateConfig,
  updateStressTestTemplate,
  validateStressTestActions,
} from '@/services/libraryRobot/stressTestTemplates';
import {
  disableArm,
  getHardwareStatus,
  type HardwareStatus,
  moveLift,
} from '@/services/libraryRobot/studio';
import type {
  Book,
  DispatchTask,
  RobotSummary,
} from '@/services/libraryRobot/types';
import { errorMessage } from '@/utils/errorText';

const TERMINAL_STATES = [
  'completed',
  'failed',
  'cancelled',
  'recovery_required',
];

/** Calibrated onboard book-stand slots (see the bookarm slot calibration). */
const BOOK_STAND_SLOTS = [1, 2, 3, 4, 5];

type Phase = 'idle' | 'takeout' | 'return' | 'park';

const PHASE_META: Record<Phase, { text: string; color: string }> = {
  idle: { text: '空闲（等待手动确认）', color: 'default' },
  takeout: { text: '快速取书', color: 'gold' },
  return: { text: '中位还书（还到目标书左边）', color: 'gold' },
  park: { text: '收拢（失能+降台）', color: 'cyan' },
};

/** 收拢后升降台停放高度（mm）：每轮取还书结束后降到该高度，便于安全手动挪车。 */
const PARK_LIFT_HEIGHT_MM = 10;

/** 手动控制车辆的点动参数：与「机器人控制」页同一租约/续发节拍。
 * 快速档留出服务端安全上限（0.3 m/s、0.8 rad/s）的余量；慢速档用于精细对位。 */
const DRIVE_PAD_SPEEDS = {
  slow: { linear: 0.1, angular: 0.2, label: '慢速（0.1 m/s）' },
  fast: { linear: 0.25, angular: 0.5, label: '快速（0.25 m/s）' },
} as const;
type DrivePadSpeedKey = keyof typeof DRIVE_PAD_SPEEDS;
const DRIVE_PAD_JOG_DURATION_MS = 750;
const DRIVE_PAD_REFRESH_MS = 250;

/** 一键运行的默认压测任务（书籍按注册信息解析；速度档 3）。
 * 每轮 2 取 2 还：取「杜拉拉」→2 号槽、取「风洞」→1 号槽、还 1 号槽（还到
 * NET 左边）、还 2 号槽（还到风洞左边）。还 2 号槽以风洞为定位目标，依赖
 * 还 1 号槽先把风洞还回架上，顺序不可调换。 */
const DEFAULT_TASK = {
  takeouts: [
    { bookName: '杜拉拉', destinationSlot: 2 },
    { bookName: '风洞', destinationSlot: 1 },
  ],
  returns: [
    { sourceSlot: 1, referenceBookName: 'NET' },
    { sourceSlot: 2, referenceBookName: '风洞' },
  ],
  liftSpeedLevel: 3,
} as const;

const ROBOT_STATUS_TEXT: Record<RobotSummary['status'], string> = {
  idle: '空闲',
  navigating: '导航中',
  charging: '充电中',
  manual: '手动控制',
  fault: '故障',
  offline: '离线',
  busy: '机械臂作业中',
  mapping: '建图中',
};

const LOCALIZATION_TEXT: Record<string, string> = {
  starting: '启动中',
  restoring_saved_pose: '恢复位姿中',
  global_localizing: '全局定位中',
  manual_initializing: '手动初始化中',
  localized: '已定位',
  manual_required: '需手动定位',
  unknown: '未知',
};

const HEALTH_ITEMS: { key: keyof RobotSummary['health']; label: string }[] = [
  { key: 'navigation', label: '导航' },
  { key: 'chassis', label: '底盘' },
  { key: 'arm', label: '机械臂' },
  { key: 'rod', label: '推杆' },
  { key: 'imu', label: 'IMU' },
  { key: 'lift', label: '升降台' },
  { key: 'camera', label: '相机' },
];

type RoundLog = {
  round: number;
  result: 'success' | 'failed' | 'stopped';
  durationS: number;
  message: string;
  at: string;
};

/** 一次取书动作：把书取到书立的指定槽位。 */
type TakeoutAction = {
  book: Book;
  destinationSlot: number;
  liftHeightMm: number;
};

/** 一次中位还书动作：从书立槽位取回该书，识别目标书后还到其左边。 */
type ReturnAction = {
  sourceSlot: number;
  referenceBook: Book;
};

/** 取书动作表单行：书未选时只带槽位，校验在 buildConfig 完成。 */
type TakeoutRow = {
  bookId?: string;
  destinationSlot: number;
};

/** 还书动作表单行。 */
type ReturnRow = {
  sourceSlot: number;
  referenceBookId?: string;
};

type LoopConfig = {
  robotId: string;
  takeouts: TakeoutAction[];
  returns: ReturnAction[];
  liftSpeedLevel: number;
};

function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}

function fmtDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = String(Math.floor(total / 3600)).padStart(2, '0');
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
  const s = String(total % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

/** Poll a dispatch task until it reaches a terminal state; resolves on
 * completed, rejects on failed/cancelled/recovery_required or when `halted`
 * (page closed). */
function waitTaskTerminal(
  taskId: string,
  onUpdate: (task: DispatchTask) => void,
  halted: () => boolean,
): Promise<DispatchTask> {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      if (halted()) {
        reject(new Error('页面已关闭'));
        return;
      }
      try {
        const tasks = await pollTasks();
        const task = tasks.find((item) => item.id === taskId);
        if (task) {
          onUpdate(task);
          if (TERMINAL_STATES.includes(task.status)) {
            if (task.status === 'completed') {
              resolve(task);
            } else {
              reject(
                new Error(
                  task.failureReason ||
                    (task.status === 'cancelled'
                      ? '任务已取消'
                      : task.status === 'recovery_required'
                        ? '机械臂需人工确认恢复（可能夹着书停在半路）'
                        : '任务失败'),
                ),
              );
            }
            return;
          }
        }
      } catch {
        // 轮询失败保持重试。
      }
      // 500 ms 一拍：动作结束到页面感知最多差半秒，再大就拖慢循环节奏。
      window.setTimeout(() => void tick(), 500);
    };
    void tick();
  });
}

export default function StressTestPage() {
  const { message } = App.useApp();
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [books, setBooks] = useState<Book[]>([]);
  const [robots, setRobots] = useState<RobotSummary[]>([]);

  const [robotId, setRobotId] = useState<string>();
  const [takeoutRows, setTakeoutRows] = useState<TakeoutRow[]>([
    { destinationSlot: 1 },
  ]);
  const [returnRows, setReturnRows] = useState<ReturnRow[]>([
    { sourceSlot: 1 },
  ]);
  const [templates, setTemplates] = useState<StressTestTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>();
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [saveTemplateName, setSaveTemplateName] = useState('');
  const [templateSaving, setTemplateSaving] = useState(false);
  const [liftSpeedLevel, setLiftSpeedLevel] = useState<number>(3);

  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle');
  /** 当前动作的简短说明（哪本书/哪个槽位），随阶段标签展示。 */
  const [phaseDetail, setPhaseDetail] = useState('');
  const [currentTask, setCurrentTask] = useState<DispatchTask>();
  const [round, setRound] = useState(0);
  const [successCount, setSuccessCount] = useState(0);
  const [failCount, setFailCount] = useState(0);
  const [logs, setLogs] = useState<RoundLog[]>([]);
  const [startedAt, setStartedAt] = useState<number>();
  const [finishedAt, setFinishedAt] = useState<number>();
  const [tick, setTick] = useState(Date.now());
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);

  const stopRef = useRef(false);
  const unmountedRef = useRef(false);
  const currentTaskRef = useRef<{
    phase: Phase;
    taskId: string;
    robotId: string;
  } | null>(null);

  /** 手动控制车辆：按住按键时的续发定时器与当前机器人。 */
  const driveTimerRef = useRef<number | undefined>(undefined);
  const driveActiveRef = useRef(false);
  const robotIdRef = useRef(robotId);
  robotIdRef.current = robotId;
  const runningRef = useRef(running);
  runningRef.current = running;
  /** 手动控制速度档：默认快速档（按住期间的帧沿用按下时刻的档位）。 */
  const [drivePadSpeed, setDrivePadSpeed] = useState<DrivePadSpeedKey>('fast');

  const realtimeState = useSyncExternalStore(
    subscribeRobotRealtime,
    getRobotRealtimeState,
    getRobotRealtimeState,
  );

  const robot =
    realtimeState.robots.find((item) => item.id === robotId) ??
    robots.find((item) => item.id === robotId);

  /** 松开/切走即停车：清掉续发定时器并补一帧零速度（车端看门狗再兜底）。 */
  function stopDrivePad() {
    if (driveTimerRef.current !== undefined) {
      window.clearInterval(driveTimerRef.current);
      driveTimerRef.current = undefined;
    }
    if (driveActiveRef.current) {
      driveActiveRef.current = false;
      const id = robotIdRef.current;
      if (id) {
        void sendManualJog(id, {
          linear: 0,
          angular: 0,
          durationMs: 100,
        }).catch(() => undefined);
      }
    }
  }

  /** 按住开始移动：固定节拍续发点动帧保持车端手动控制租约。
   * linear/angular 为方向（-1/0/1），速度按当前档位换算。 */
  function startDrivePad(linearDir: -1 | 0 | 1, angularDir: -1 | 0 | 1) {
    stopDrivePad();
    const id = robotIdRef.current;
    if (!id || runningRef.current) return;
    const speed = DRIVE_PAD_SPEEDS[drivePadSpeed];
    const linear = linearDir * speed.linear;
    const angular = angularDir * speed.angular;
    driveActiveRef.current = true;
    const send = () => {
      void sendManualJog(id, {
        linear,
        angular,
        durationMs: DRIVE_PAD_JOG_DURATION_MS,
      }).catch(() => undefined);
    };
    send();
    driveTimerRef.current = window.setInterval(send, DRIVE_PAD_REFRESH_MS);
  }

  // 页面卸载时确保车辆停住。
  useEffect(
    () => () => {
      stopDrivePad();
      unmountedRef.current = true;
      stopRef.current = true;
    },
    [],
  );

  // 初始加载书籍/机器人选项。
  useEffect(() => {
    (async () => {
      try {
        const [bookList, robotList] = await Promise.all([
          listBooks(),
          getRobots(),
        ]);
        setBooks(bookList);
        setRobots(robotList);
        const first = robotList[0];
        if (first) setRobotId(first.id);
      } catch (error) {
        message.error(errorMessage(error, '无法加载压测选项。'));
      } finally {
        setLoadingOptions(false);
      }
    })();
  }, [message]);

  // 模板列表单独加载：模板接口异常不影响压测主选项。
  useEffect(() => {
    (async () => {
      try {
        setTemplates(await listStressTestTemplates());
      } catch (error) {
        message.error(errorMessage(error, '无法加载压测模板列表。'));
      }
    })();
  }, [message]);

  // 机器人列表轮询（实时 WebSocket 断开时兜底）。
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await getRobots();
        if (!cancelled) setRobots(list);
      } catch {
        // 轮询失败保持旧状态。
      }
    };
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const refreshHardware = useCallback(async () => {
    try {
      setHardware(await getHardwareStatus());
    } catch {
      setHardware(null);
    }
  }, []);

  // 机械臂/升降台等硬件状态轮询。
  useEffect(() => {
    void refreshHardware();
    const timer = window.setInterval(() => void refreshHardware(), 3000);
    return () => window.clearInterval(timer);
  }, [refreshHardware]);

  // 已运行时长的秒级刷新。
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  function pushLog(entry: RoundLog) {
    setLogs((prev) => [entry, ...prev].slice(0, 50));
  }

  /** 把取书/还书表单行解析成动作序列；返回字符串表示校验失败信息。 */
  function resolveActions():
    | { takeouts: TakeoutAction[]; returns: ReturnAction[] }
    | string {
    const shapeError = validateStressTestActions(takeoutRows, returnRows);
    if (shapeError) return shapeError;
    const takeouts: TakeoutAction[] = [];
    for (const [index, row] of takeoutRows.entries()) {
      const book = books.find((item) => item.id === row.bookId);
      if (!book) return `取书动作 ${index + 1}：请选择要取的书`;
      // 升降杆高度跟着书籍登记信息走。
      takeouts.push({
        book,
        destinationSlot: row.destinationSlot,
        liftHeightMm: book.heightMm,
      });
    }
    const bookBySlot = new Map(
      takeouts.map((takeout) => [takeout.destinationSlot, takeout.book]),
    );
    const returns: ReturnAction[] = [];
    for (const [index, row] of returnRows.entries()) {
      const referenceBook = books.find(
        (item) => item.id === row.referenceBookId,
      );
      if (!referenceBook) return `还书动作 ${index + 1}：请选择还书目标书`;
      const takenBook = bookBySlot.get(row.sourceSlot);
      if (takenBook && takenBook.id === referenceBook.id)
        return `还书动作 ${index + 1}：目标书与 ${row.sourceSlot} 号槽取入的书相同，无法作为定位目标`;
      returns.push({ sourceSlot: row.sourceSlot, referenceBook });
    }
    return { takeouts, returns };
  }

  function buildConfig(): LoopConfig | string {
    if (!robotId) return '请选择机器人';
    const actions = resolveActions();
    if (typeof actions === 'string') return actions;
    if (robot && robot.status !== 'idle')
      return `机器人当前状态为「${ROBOT_STATUS_TEXT[robot.status]}」，需空闲才能开始压测`;
    return {
      robotId,
      takeouts: actions.takeouts,
      returns: actions.returns,
      liftSpeedLevel,
    };
  }

  /** 当前表单的任务定义（存模板用；不校验机器人状态，只存书籍/槽位 id）。 */
  function buildTemplateConfig(): StressTestTemplateConfig | string {
    const actions = resolveActions();
    if (typeof actions === 'string') return actions;
    return {
      takeouts: actions.takeouts.map((takeout) => ({
        bookId: takeout.book.id,
        destinationSlot: takeout.destinationSlot,
      })),
      returns: actions.returns.map((action) => ({
        sourceSlot: action.sourceSlot,
        referenceBookId: action.referenceBook.id,
      })),
      liftSpeedLevel,
    };
  }

  function updateTakeoutRow(index: number, patch: Partial<TakeoutRow>) {
    setTakeoutRows((prev) =>
      prev.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...patch } : row,
      ),
    );
  }

  function addTakeoutRow() {
    setTakeoutRows((prev) => {
      const used = new Set(prev.map((row) => row.destinationSlot));
      const free = BOOK_STAND_SLOTS.find((slot) => !used.has(slot)) ?? 1;
      return [...prev, { destinationSlot: free }];
    });
  }

  function removeTakeoutRow(index: number) {
    setTakeoutRows((prev) => prev.filter((_, rowIndex) => rowIndex !== index));
  }

  function updateReturnRow(index: number, patch: Partial<ReturnRow>) {
    setReturnRows((prev) =>
      prev.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...patch } : row,
      ),
    );
  }

  function addReturnRow() {
    setReturnRows((prev) => {
      const used = new Set(prev.map((row) => row.sourceSlot));
      const free = takeoutRows.find((row) => !used.has(row.destinationSlot));
      return [...prev, { sourceSlot: free?.destinationSlot ?? 1 }];
    });
  }

  function removeReturnRow(index: number) {
    setReturnRows((prev) => prev.filter((_, rowIndex) => rowIndex !== index));
  }

  /** 应用模板：按当前库解析书籍 id 并回填表单；任一引用失效即报错不动表单。 */
  async function applyTemplate(template: StressTestTemplate) {
    const config = template.config;
    const missing: string[] = [];
    const takeoutRowsNext: TakeoutRow[] = [];
    for (const [index, action] of config.takeouts.entries()) {
      if (books.some((item) => item.id === action.bookId)) {
        takeoutRowsNext.push({
          bookId: action.bookId,
          destinationSlot: action.destinationSlot,
        });
      } else {
        missing.push(`取书动作 ${index + 1} 的书`);
      }
    }
    const returnRowsNext: ReturnRow[] = [];
    for (const [index, action] of config.returns.entries()) {
      if (books.some((item) => item.id === action.referenceBookId)) {
        returnRowsNext.push({
          sourceSlot: action.sourceSlot,
          referenceBookId: action.referenceBookId,
        });
      } else {
        missing.push(`还书动作 ${index + 1} 的目标书`);
      }
    }
    if (missing.length > 0) {
      message.error(
        `模板「${template.name}」引用的${missing.join('、')}已不存在`,
      );
      return;
    }
    setTakeoutRows(takeoutRowsNext);
    setReturnRows(returnRowsNext);
    setLiftSpeedLevel(config.liftSpeedLevel);
    setSelectedTemplateId(template.id);
    message.success(`已应用模板「${template.name}」，确认无误后点开始压测`);
  }

  function openSaveModal() {
    const config = buildTemplateConfig();
    if (typeof config === 'string') {
      message.error(config);
      return;
    }
    const selected = templates.find((item) => item.id === selectedTemplateId);
    setSaveTemplateName(selected?.name ?? '');
    setSaveModalOpen(true);
  }

  async function saveTemplate() {
    const name = saveTemplateName.trim();
    if (!name) {
      message.error('请填写模板名称');
      return;
    }
    const config = buildTemplateConfig();
    if (typeof config === 'string') {
      message.error(config);
      return;
    }
    // 同名模板直接覆盖（模态框内已提示）。
    const existing = templates.find((item) => item.name === name);
    setTemplateSaving(true);
    try {
      const saved = existing
        ? await updateStressTestTemplate(existing.id, { name, config })
        : await createStressTestTemplate({ name, config });
      setTemplates(await listStressTestTemplates());
      setSelectedTemplateId(saved.id);
      setSaveModalOpen(false);
      message.success(`模板「${name}」已保存`);
    } catch (error) {
      message.error(errorMessage(error, '保存模板失败'));
    } finally {
      setTemplateSaving(false);
    }
  }

  async function removeTemplate() {
    const selected = templates.find((item) => item.id === selectedTemplateId);
    if (!selected) return;
    try {
      await deleteStressTestTemplate(selected.id);
      setTemplates(await listStressTestTemplates());
      setSelectedTemplateId(undefined);
      message.success(`模板「${selected.name}」已删除`);
    } catch (error) {
      message.error(errorMessage(error, '删除模板失败'));
    }
  }

  async function runPhase(
    phase: Exclude<Phase, 'idle'>,
    label: string,
    create: () => Promise<DispatchTask>,
  ): Promise<DispatchTask> {
    if (stopRef.current || unmountedRef.current) throw new Error('已手动停止');
    setPhase(phase);
    setPhaseDetail(label);
    setCurrentTask(undefined);
    const task = await create();
    currentTaskRef.current = { phase, taskId: task.id, robotId: task.robotId };
    setCurrentTask(task);
    try {
      return await waitTaskTerminal(
        task.id,
        setCurrentTask,
        () => unmountedRef.current,
      );
    } finally {
      currentTaskRef.current = null;
    }
  }

  /** 手动逐轮执行：把车手动开到作业位后点确认，执行一轮「按序取书入槽 →
   * 按序中位还书 → 收拢（失能+降台，便于安全挪车）」。没有自动移动与自动循环。 */
  async function runRound(config: LoopConfig) {
    stopRef.current = false;
    setRunning(true);
    setPhase('idle');
    setPhaseDetail('');
    setCurrentTask(undefined);
    const roundNo = round + 1;
    setRound(roundNo);
    const roundStart = Date.now();
    if (startedAt === undefined) {
      setStartedAt(roundStart);
      setTick(roundStart);
    }
    setFinishedAt(undefined);
    /** 当前动作说明：失败时写进轮次日志，运行中随阶段标签展示。 */
    let actionLabel = '';
    try {
      // 槽位→该槽位里的书：还书时据此回填 bookId。
      const bookBySlot = new Map<number, Book>();
      const actionNotes: string[] = [];
      for (const takeout of config.takeouts) {
        actionLabel = `取「${takeout.book.name}」→ ${takeout.destinationSlot} 号槽`;
        await runPhase('takeout', actionLabel, () =>
          createCompleteTakeout({
            robotId: config.robotId,
            templateId: takeout.book.templateId,
            bookId: takeout.book.id,
            liftHeightMm: takeout.liftHeightMm,
            destinationSlot: takeout.destinationSlot,
            liftSpeedLevel: config.liftSpeedLevel,
            sendNavigation: false,
          }),
        );
        bookBySlot.set(takeout.destinationSlot, takeout.book);
        actionNotes.push(actionLabel);
      }
      // 中位还书：识别目标书，抓出左邻书晃缝后还到目标书左边。
      for (const returnAction of config.returns) {
        // 手动单取单还允许两槽位不同：查不到时退回第一个取书动作的书，
        // 与旧的单取单还行为一致（默认任务的槽位均能查到）。
        const takenBook =
          bookBySlot.get(returnAction.sourceSlot) ?? config.takeouts[0]?.book;
        actionLabel = `还 ${returnAction.sourceSlot} 号槽（目标「${returnAction.referenceBook.name}」左边）`;
        await runPhase('return', actionLabel, () =>
          createCompleteReturn({
            robotId: config.robotId,
            templateId: returnAction.referenceBook.templateId,
            bookId: takenBook?.id,
            liftHeightMm: returnAction.referenceBook.heightMm,
            sourceSlot: returnAction.sourceSlot,
            liftSpeedLevel: config.liftSpeedLevel,
            sendNavigation: false,
            returnMode: 'mid',
          }),
        );
        actionNotes.push(actionLabel);
      }
      // 收拢：失能机械臂、升降台降到停放高度，便于手动挪车到下一个位置。
      actionLabel = '收拢（失能+降台）';
      setPhase('park');
      setPhaseDetail(actionLabel);
      setCurrentTask(undefined);
      try {
        await disableArm();
        await moveLift(PARK_LIFT_HEIGHT_MM, config.liftSpeedLevel);
      } catch (error) {
        throw new Error(errorMessage(error, '机械臂失能或升降台降下失败'));
      }
      setSuccessCount((count) => count + 1);
      pushLog({
        round: roundNo,
        result: 'success',
        durationS: (Date.now() - roundStart) / 1000,
        message: actionNotes.join('；'),
        at: new Date().toLocaleTimeString(),
      });
    } catch (error) {
      const stopped = stopRef.current || unmountedRef.current;
      pushLog({
        round: roundNo,
        result: stopped ? 'stopped' : 'failed',
        durationS: (Date.now() - roundStart) / 1000,
        message: stopped
          ? '手动停止'
          : `${actionLabel ? `${actionLabel}：` : ''}${errorMessage(error, '本轮执行失败')}`,
        at: new Date().toLocaleTimeString(),
      });
      if (!stopped) {
        setFailCount((count) => count + 1);
        message.error(errorMessage(error, `第 ${roundNo} 轮失败`));
      }
    } finally {
      currentTaskRef.current = null;
      setCurrentTask(undefined);
      setPhase('idle');
      setPhaseDetail('');
      setRunning(false);
      setFinishedAt(Date.now());
    }
  }

  /** 填入默认任务：按 DEFAULT_TASK 解析书籍并回填表单（不自动开跑：
   * 车辆位置由人工开到作业位后点「确认执行」）。 */
  function applyDefaultTask() {
    // 逐本解析 2 取 2 还涉及的书籍；缺哪本报哪本。
    const resolveBook = (name: string) =>
      books.find((item) => item.name.includes(name));
    const takeouts: TakeoutAction[] = [];
    for (const entry of DEFAULT_TASK.takeouts) {
      const book = resolveBook(entry.bookName);
      if (!book) {
        message.error(`默认任务：书籍「${entry.bookName}」不存在`);
        return;
      }
      takeouts.push({
        book,
        destinationSlot: entry.destinationSlot,
        liftHeightMm: book.heightMm,
      });
    }
    const bookBySlot = new Map(
      takeouts.map((takeout) => [takeout.destinationSlot, takeout.book]),
    );
    const returns: ReturnAction[] = [];
    for (const entry of DEFAULT_TASK.returns) {
      const referenceBook = resolveBook(entry.referenceBookName);
      if (!referenceBook) {
        message.error(
          `默认任务：还书目标书「${entry.referenceBookName}」不存在`,
        );
        return;
      }
      const takenBook = bookBySlot.get(entry.sourceSlot);
      if (!takenBook) {
        message.error(
          `默认任务：还 ${entry.sourceSlot} 号槽没有对应的取书动作`,
        );
        return;
      }
      if (takenBook.id === referenceBook.id) {
        message.error(
          `默认任务：还 ${entry.sourceSlot} 号槽的目标书「${entry.referenceBookName}」与该槽的书相同，无法作为定位目标`,
        );
        return;
      }
      returns.push({ sourceSlot: entry.sourceSlot, referenceBook });
    }
    // 只回填表单不自动开跑：车辆位置由人工开到作业位后点「确认执行」。
    setTakeoutRows(
      takeouts.map((takeout) => ({
        bookId: takeout.book.id,
        destinationSlot: takeout.destinationSlot,
      })),
    );
    setReturnRows(
      returns.map((action) => ({
        sourceSlot: action.sourceSlot,
        referenceBookId: action.referenceBook.id,
      })),
    );
    setLiftSpeedLevel(DEFAULT_TASK.liftSpeedLevel);
    setSelectedTemplateId(undefined);
    message.success('已填入默认任务配置，把车开到作业位后点「确认执行」');
  }

  function start() {
    const config = buildConfig();
    if (typeof config === 'string') {
      message.error(config);
      return;
    }
    void runRound(config);
  }

  function stop() {
    stopRef.current = true;
    stopDrivePad();
    const current = currentTaskRef.current;
    if (current) {
      const request =
        current.phase === 'takeout'
          ? cancelCompleteTakeout(current.taskId)
          : cancelCompleteReturn(current.taskId);
      request.catch(() => undefined);
    }
    message.info('已请求停止：当前动作取消后本轮结束。');
  }

  const phaseMeta = PHASE_META[phase];
  const elapsedMs =
    startedAt === undefined ? 0 : (finishedAt ?? tick) - startedAt;
  const thermal = hardware?.arm.thermal;
  const temperatureEntries = Object.entries(thermal?.temperatures_c ?? {}).sort(
    (a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }),
  );
  const pose = robot?.pose;
  const bookOptions = books.map((book) => ({
    value: book.id,
    label: `${book.name}（高度 ${book.heightMm} mm）`,
  }));
  const slotOptions = BOOK_STAND_SLOTS.map((slot) => ({
    value: slot,
    label: `槽位 ${slot}`,
  }));

  return (
    <PageContainer
      title="压力测试"
      content="手动把车开到作业位后点「确认执行」，执行一轮「按序取书入槽 → 按序中位还书（还到目标书左边）→ 收拢（失能机械臂+降升降台，便于安全挪车）」。每轮由人工确认触发，用于取还书稳定性验证。循环由本页面驱动：运行期间请保持页面打开；停止或关闭页面后当前动作取消、本轮结束。"
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        title="压测将真实驱动底盘、升降台与机械臂！"
        description="手动控制车辆时按住方向键移动、松开即停；执行取还书前请确认机构周边清场、实体急停可触达。「停止本轮」会取消当前动作；已完成的动作不会回退。"
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={10}>
          <Card title="压测配置" loading={loadingOptions}>
            <Space
              orientation="vertical"
              size="middle"
              style={{ width: '100%' }}
            >
              <div>
                <Typography.Text type="secondary">机器人</Typography.Text>
                <Select
                  style={{ width: '100%' }}
                  placeholder="选择机器人"
                  value={robotId}
                  onChange={setRobotId}
                  options={robots.map((item) => ({
                    value: item.id,
                    label: `${item.name}（${item.id}）`,
                  }))}
                  disabled={running}
                />
                {robot ? (
                  <Space wrap style={{ marginTop: 4 }}>
                    <Tag color={robot.status === 'idle' ? 'green' : 'orange'}>
                      {ROBOT_STATUS_TEXT[robot.status]}
                    </Tag>
                    <Tag
                      color={
                        robot.localizationStatus === 'localized'
                          ? 'green'
                          : 'orange'
                      }
                    >
                      {LOCALIZATION_TEXT[robot.localizationStatus ?? 'unknown']}
                    </Tag>
                  </Space>
                ) : null}
              </div>
              <div>
                <Typography.Text type="secondary">任务模板</Typography.Text>
                <Select
                  style={{ width: '100%' }}
                  placeholder="选择已保存的模板（应用后覆盖下方配置）"
                  value={selectedTemplateId}
                  onChange={(value: string) => {
                    const template = templates.find(
                      (item) => item.id === value,
                    );
                    if (template) void applyTemplate(template);
                  }}
                  options={templates.map((item) => ({
                    value: item.id,
                    label: item.name,
                  }))}
                  showSearch={{ optionFilterProp: 'label' }}
                  disabled={running}
                  notFoundContent="暂无模板"
                />
                <Space style={{ marginTop: 8 }}>
                  <Button
                    icon={<SaveOutlined />}
                    onClick={openSaveModal}
                    disabled={running}
                  >
                    保存为模板
                  </Button>
                  <Popconfirm
                    title="删除任务模板？"
                    description={`将删除模板「${templates.find((item) => item.id === selectedTemplateId)?.name ?? ''}」，不影响正在运行的压测。`}
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => void removeTemplate()}
                    disabled={!selectedTemplateId || running}
                  >
                    <Button
                      danger
                      icon={<DeleteOutlined />}
                      disabled={!selectedTemplateId || running}
                    >
                      删除模板
                    </Button>
                  </Popconfirm>
                </Space>
              </div>
              <div>
                <Typography.Text type="secondary">
                  取书动作（按顺序执行；升降杆高度按书籍登记值自动带出）
                </Typography.Text>
                <Space
                  orientation="vertical"
                  size="small"
                  style={{ width: '100%' }}
                >
                  {takeoutRows.map((row, index) => (
                    // 行数少且无重排，用序号做 key 即可。
                    // biome-ignore lint/suspicious/noArrayIndexKey: 编辑行按位置更新
                    <Row gutter={8} key={index} wrap={false} align="middle">
                      <Col flex="auto">
                        <Select
                          style={{ width: '100%' }}
                          placeholder={`取书 ${index + 1}：选择要取的书`}
                          value={row.bookId}
                          onChange={(value: string) =>
                            updateTakeoutRow(index, { bookId: value })
                          }
                          options={bookOptions}
                          showSearch={{ optionFilterProp: 'label' }}
                          disabled={running}
                        />
                      </Col>
                      <Col flex="96px">
                        <Select
                          style={{ width: '100%' }}
                          value={row.destinationSlot}
                          onChange={(value: number) =>
                            updateTakeoutRow(index, { destinationSlot: value })
                          }
                          options={slotOptions}
                          disabled={running}
                        />
                      </Col>
                      <Col>
                        <Button
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          aria-label={`删除取书动作 ${index + 1}`}
                          disabled={running || takeoutRows.length <= 1}
                          onClick={() => removeTakeoutRow(index)}
                        />
                      </Col>
                    </Row>
                  ))}
                  <Button
                    type="dashed"
                    block
                    icon={<PlusOutlined />}
                    onClick={addTakeoutRow}
                    disabled={
                      running || takeoutRows.length >= BOOK_STAND_SLOTS.length
                    }
                  >
                    添加取书
                  </Button>
                </Space>
              </div>
              <div>
                <Typography.Text type="secondary">
                  还书动作（中位还书：识别目标书后还到其左边，按顺序执行）
                </Typography.Text>
                <Space
                  orientation="vertical"
                  size="small"
                  style={{ width: '100%' }}
                >
                  {returnRows.map((row, index) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: 编辑行按位置更新
                    <Row gutter={8} key={index} wrap={false} align="middle">
                      <Col flex="96px">
                        <Select
                          style={{ width: '100%' }}
                          value={row.sourceSlot}
                          onChange={(value: number) =>
                            updateReturnRow(index, { sourceSlot: value })
                          }
                          options={slotOptions}
                          disabled={running}
                        />
                      </Col>
                      <Col flex="auto">
                        <Select
                          style={{ width: '100%' }}
                          placeholder={`还书 ${index + 1}：选择目标书（还到其左边）`}
                          value={row.referenceBookId}
                          onChange={(value: string) =>
                            updateReturnRow(index, { referenceBookId: value })
                          }
                          options={bookOptions}
                          showSearch={{ optionFilterProp: 'label' }}
                          disabled={running}
                        />
                      </Col>
                      <Col>
                        <Button
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          aria-label={`删除还书动作 ${index + 1}`}
                          disabled={running}
                          onClick={() => removeReturnRow(index)}
                        />
                      </Col>
                    </Row>
                  ))}
                  <Button
                    type="dashed"
                    block
                    icon={<PlusOutlined />}
                    onClick={addReturnRow}
                    disabled={
                      running || returnRows.length >= takeoutRows.length
                    }
                  >
                    添加还书
                  </Button>
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  还书书格须是某个取书动作的目标槽位；目标书须留在架上，不能是该槽取入的书。
                </Typography.Text>
              </div>
              <div>
                <Typography.Text type="secondary">升降速度档位</Typography.Text>
                <Select
                  style={{ width: '100%' }}
                  value={liftSpeedLevel}
                  onChange={setLiftSpeedLevel}
                  options={[
                    { value: 1, label: '1（慢速）' },
                    { value: 2, label: '2（中速）' },
                    { value: 3, label: '3（快速）' },
                  ]}
                  disabled={running}
                />
              </div>
              <Typography.Text type="secondary">
                取书成功后书放入对应槽位；还书时从指定槽位取回该书，中位还书会识别目标书并还到其左边。每轮结束后自动收拢（失能机械臂、升降台降到停放高度），便于安全手动挪车。
              </Typography.Text>
              <Space wrap>
                <Button
                  onClick={applyDefaultTask}
                  disabled={running || loadingOptions}
                >
                  填入默认任务
                </Button>
                <Button type="primary" disabled={running} onClick={start}>
                  确认执行本轮取还书
                </Button>
                <Button danger disabled={!running} onClick={stop}>
                  停止本轮
                </Button>
              </Space>
            </Space>
          </Card>

          <Card title="手动控制车辆" style={{ marginTop: 16 }}>
            <Space
              orientation="vertical"
              size="small"
              style={{ width: '100%', alignItems: 'center' }}
            >
              <Radio.Group
                size="small"
                value={drivePadSpeed}
                onChange={(event) => {
                  // 切档时先停车：按住中的旧档位帧立即终止。
                  stopDrivePad();
                  setDrivePadSpeed(event.target.value as DrivePadSpeedKey);
                }}
                options={Object.entries(DRIVE_PAD_SPEEDS).map(
                  ([value, item]) => ({ value, label: item.label }),
                )}
                optionType="button"
                disabled={running || !robotId}
              />
              <Button
                icon={<ArrowUpOutlined />}
                disabled={running || !robotId}
                onPointerDown={(event) => {
                  event.preventDefault();
                  event.currentTarget.setPointerCapture(event.pointerId);
                  startDrivePad(1, 0);
                }}
                onPointerUp={stopDrivePad}
                onPointerLeave={stopDrivePad}
                onPointerCancel={stopDrivePad}
              >
                前进
              </Button>
              <Space>
                <Button
                  icon={<ArrowLeftOutlined />}
                  disabled={running || !robotId}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    startDrivePad(0, 1);
                  }}
                  onPointerUp={stopDrivePad}
                  onPointerLeave={stopDrivePad}
                  onPointerCancel={stopDrivePad}
                >
                  左转
                </Button>
                <Button
                  icon={<ArrowDownOutlined />}
                  disabled={running || !robotId}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    startDrivePad(-1, 0);
                  }}
                  onPointerUp={stopDrivePad}
                  onPointerLeave={stopDrivePad}
                  onPointerCancel={stopDrivePad}
                >
                  后退
                </Button>
                <Button
                  icon={<ArrowRightOutlined />}
                  disabled={running || !robotId}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    event.currentTarget.setPointerCapture(event.pointerId);
                    startDrivePad(0, -1);
                  }}
                  onPointerUp={stopDrivePad}
                  onPointerLeave={stopDrivePad}
                  onPointerCancel={stopDrivePad}
                >
                  右转
                </Button>
              </Space>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                按住移动、松开即停；取还书执行中不可用。快速档 0.25
                m/s，精细对位请切慢速档。把车开到作业位后点「确认执行本轮取还书」。
              </Typography.Text>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={14}>
          <Card
            title="运行状态"
            extra={
              running ? <Tag color="processing">运行中</Tag> : <Tag>未运行</Tag>
            }
          >
            <Space
              orientation="vertical"
              size="middle"
              style={{ width: '100%' }}
            >
              <Space wrap size="large">
                <Statistic title="已执行轮次" value={round} />
                <Statistic
                  title="成功轮次"
                  value={successCount}
                  styles={{ content: { color: '#3f8600' } }}
                />
                <Statistic
                  title="失败轮次"
                  value={failCount}
                  styles={{
                    content: { color: failCount > 0 ? '#cf1322' : undefined },
                  }}
                />
                <Statistic title="已运行时长" value={fmtDuration(elapsedMs)} />
              </Space>
              <div>
                当前阶段：
                <Tag color={phaseMeta.color}>{phaseMeta.text}</Tag>
                {phase !== 'idle' && phaseDetail ? (
                  <Typography.Text type="secondary">
                    {phaseDetail}
                    {'　'}
                  </Typography.Text>
                ) : null}
                {currentTask?.workflowMessage ? (
                  <Typography.Text type="secondary">
                    {currentTask.workflowMessage}
                  </Typography.Text>
                ) : null}
              </div>
              {currentTask ? (
                <Progress
                  percent={currentTask.progress}
                  size="small"
                  status={
                    currentTask.status === 'failed' ? 'exception' : 'active'
                  }
                />
              ) : null}
              <Table<RoundLog>
                size="small"
                rowKey={(record) =>
                  `${record.round}-${record.result}-${record.at}`
                }
                pagination={false}
                dataSource={logs.slice(0, 20)}
                locale={{ emptyText: '尚未运行' }}
                columns={[
                  { title: '轮次', dataIndex: 'round', width: 64 },
                  {
                    title: '结果',
                    dataIndex: 'result',
                    width: 80,
                    render: (value: RoundLog['result']) =>
                      value === 'success' ? (
                        <Tag color="green">成功</Tag>
                      ) : value === 'failed' ? (
                        <Tag color="red">失败</Tag>
                      ) : (
                        <Tag>已停止</Tag>
                      ),
                  },
                  {
                    title: '用时',
                    dataIndex: 'durationS',
                    width: 90,
                    render: (value: number) => `${value.toFixed(0)} s`,
                  },
                  {
                    title: '信息',
                    dataIndex: 'message',
                    render: (value: string) => value || '—',
                  },
                  { title: '时间', dataIndex: 'at', width: 100 },
                ]}
              />
            </Space>
          </Card>

          <Card
            title="机器人位置与健康"
            style={{ marginTop: 16 }}
            extra={
              realtimeState.connected ? (
                <Tag color="green">实时通道已连接</Tag>
              ) : (
                <Tag color="orange">实时通道未连接</Tag>
              )
            }
          >
            <Space
              orientation="vertical"
              size="middle"
              style={{ width: '100%' }}
            >
              {pose ? (
                <Row gutter={16}>
                  <Col span={6}>
                    <Statistic title="X (m)" value={pose.x} precision={3} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="Y (m)" value={pose.y} precision={3} />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="朝向 (°)"
                      value={(pose.yaw * 180) / Math.PI}
                      precision={1}
                    />
                  </Col>
                </Row>
              ) : (
                <Typography.Text type="secondary">
                  暂无位姿数据（机器人离线或未上报）
                </Typography.Text>
              )}
              <Space wrap>
                <span>
                  定位：
                  {LOCALIZATION_TEXT[robot?.localizationStatus ?? 'unknown']}
                </span>
                {pose ? (
                  <Typography.Text type="secondary">
                    更新于 {new Date(pose.capturedAt).toLocaleTimeString()}
                  </Typography.Text>
                ) : null}
              </Space>
              <Space wrap>
                {HEALTH_ITEMS.map((item) => (
                  <Tag
                    key={item.key}
                    color={robot?.health?.[item.key] ? 'green' : 'red'}
                  >
                    {item.label}
                  </Tag>
                ))}
              </Space>
            </Space>
          </Card>

          <Card title="机械臂与硬件" style={{ marginTop: 16 }}>
            {hardware === null ? (
              <Alert
                type="error"
                showIcon
                title="BookArm 服务不可用"
                description="无法读取机械臂/升降台状态，请确认 lr-bookarm-takeout 服务已启动。"
              />
            ) : (
              <Space
                orientation="vertical"
                size="middle"
                style={{ width: '100%' }}
              >
                <Space wrap size="large">
                  <Statistic
                    title="升降台高度"
                    value={hardware.lift.height_mm ?? '—'}
                    precision={0}
                    suffix="mm"
                  />
                  <Statistic
                    title="推杆角度"
                    value={hardware.rod.angle_deg ?? '—'}
                    precision={1}
                    suffix="°"
                  />
                  <Statistic
                    title="CAN 帧率"
                    value={hardware.arm.health?.can_fps ?? 0}
                    precision={1}
                    suffix="fps"
                  />
                </Space>
                <Space wrap>
                  <span>
                    CAN：
                    {hardware.can.up ? (
                      <Tag color="green">在线</Tag>
                    ) : (
                      <Tag color="red">离线</Tag>
                    )}
                  </span>
                  <span>
                    机械臂：
                    {hardware.arm.health?.enabled ? (
                      <Tag color="green">已使能</Tag>
                    ) : (
                      <Tag>未使能</Tag>
                    )}
                  </span>
                  <span>
                    反馈：
                    {hardware.arm.health == null ? (
                      <Tag>未知</Tag>
                    ) : hardware.arm.health.healthy_feedback ? (
                      <Tag color="green">正常</Tag>
                    ) : (
                      <Tag color="red">异常</Tag>
                    )}
                  </span>
                  <span>
                    升降台：
                    {hardware.lift.connected ? (
                      <Tag color="green">已连接</Tag>
                    ) : (
                      <Tag color="orange">未连接</Tag>
                    )}
                  </span>
                  <span>
                    推杆：
                    {hardware.rod.connected ? (
                      <Tag color="green">已连接</Tag>
                    ) : (
                      <Tag color="red">未连接</Tag>
                    )}
                  </span>
                  <span>
                    相机：
                    {hardware.camera.present ? (
                      <Tag color="green">已连接</Tag>
                    ) : (
                      <Tag color="red">未连接</Tag>
                    )}
                  </span>
                  <span>
                    夹爪：
                    {hardware.arm.gripper_carry_armed ? (
                      <Tag color="blue">夹持中</Tag>
                    ) : (
                      <Tag>空</Tag>
                    )}
                  </span>
                </Space>
                {thermal?.lockout ? (
                  <Alert
                    type="error"
                    showIcon
                    title="温度保护已锁存，需处理后清除才能再次使能"
                  />
                ) : null}
                {hardware.arm.gripper_thermal_warning ? (
                  <Alert
                    type="warning"
                    showIcon
                    title={hardware.arm.gripper_thermal_warning}
                  />
                ) : null}
                <Table
                  size="small"
                  rowKey="name"
                  pagination={false}
                  dataSource={temperatureEntries.map(([name, temp]) => ({
                    name,
                    temp,
                  }))}
                  locale={{ emptyText: '暂无温度数据' }}
                  columns={[
                    { title: '电机', dataIndex: 'name', width: 90 },
                    {
                      title: `温度 (°C，上限 ${thermal?.limit_c ?? '—'})`,
                      dataIndex: 'temp',
                      render: (value: number) => (
                        <Typography.Text
                          type={
                            thermal && value >= thermal.limit_c
                              ? 'danger'
                              : undefined
                          }
                        >
                          {fmt(value, 0)}
                        </Typography.Text>
                      ),
                    },
                  ]}
                />
              </Space>
            )}
          </Card>
        </Col>
      </Row>
      <Modal
        title="保存为任务模板"
        open={saveModalOpen}
        onOk={() => void saveTemplate()}
        onCancel={() => setSaveModalOpen(false)}
        okText={
          templates.some((item) => item.name === saveTemplateName.trim())
            ? '覆盖保存'
            : '保存'
        }
        okButtonProps={{
          danger: templates.some(
            (item) => item.name === saveTemplateName.trim(),
          ),
          loading: templateSaving,
        }}
        cancelText="取消"
      >
        <Space orientation="vertical" size="small" style={{ width: '100%' }}>
          <Typography.Text type="secondary">
            保存当前「取还书动作 / 速度档位」，下次可一键回填。
          </Typography.Text>
          <Input
            placeholder="模板名称，如：书架点 4 两取两还"
            maxLength={120}
            value={saveTemplateName}
            onChange={(event) => setSaveTemplateName(event.target.value)}
          />
          {templates.some((item) => item.name === saveTemplateName.trim()) ? (
            <Alert
              type="warning"
              showIcon
              title={`已存在同名模板，保存将覆盖「${saveTemplateName.trim()}」`}
            />
          ) : null}
        </Space>
      </Modal>
    </PageContainer>
  );
}

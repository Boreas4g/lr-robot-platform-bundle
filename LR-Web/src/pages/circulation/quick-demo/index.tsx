import { SaveOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  Alert,
  App,
  Button,
  Card,
  InputNumber,
  Progress,
  Radio,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';

import {
  cancelCompleteReturn,
  cancelCompleteTakeout,
  cancelShelfInternal,
  createCompleteReturn,
  createCompleteTakeout,
  createShelfInternal,
  DEFAULT_BOOK_HEIGHT_MM,
  getMapAnnotations,
  getRobots,
  listBooks,
  pollTasks,
} from '@/services/libraryRobot';
import { disableArm } from '@/services/libraryRobot/studio';
import type {
  Book,
  DispatchTask,
  MapAnnotation,
  ReturnMode,
  RobotSummary,
  TakeoutMode,
} from '@/services/libraryRobot/types';
import { errorMessage } from '@/utils/errorText';
import AnnotationTargetSelect from '../components/AnnotationTargetSelect';
import { QUICK_DEMO_INTERVAL_MS, runQuickTakeReturnDemo } from './quickDemo';
import {
  loadQuickDemoOptions,
  type QuickDemoMode,
  saveQuickDemoOptions,
} from './quickDemoOptions';

const TERMINAL_STATES: DispatchTask['status'][] = [
  'completed',
  'failed',
  'cancelled',
  'recovery_required',
];
const BOOK_STAND_SLOTS = [1, 2, 3, 4, 5];
const TAKEOUT_MODE_OPTIONS = [
  { value: 'standard', label: '普通取书' },
  { value: 'mid', label: '中位取书' },
];
const RETURN_MODE_OPTIONS = [
  { value: 'mid', label: '中位还书' },
  { value: 'end', label: '末尾还书' },
];

type DemoMode = QuickDemoMode;
type Phase =
  | 'idle'
  | 'takeout'
  | 'return'
  | 'shelf_internal'
  | 'disable'
  | 'wait';
type ActiveTask = {
  phase: 'takeout' | 'return' | 'shelf_internal';
  taskId: string;
};

const PHASE_TEXT: Record<Phase, string> = {
  idle: '未运行',
  takeout: '快速取书',
  return: '快速还书',
  shelf_internal: '架内取还书',
  disable: '机械臂失能',
  wait: '间歇等待（机械臂已失能）',
};

function waitTaskTerminal(
  taskId: string,
  onUpdate: (task: DispatchTask) => void,
  halted: () => boolean,
): Promise<DispatchTask> {
  return new Promise((resolve, reject) => {
    const tick = async () => {
      if (halted()) {
        reject(new Error('演示页面已关闭'));
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
                        ? '机械臂需人工确认恢复'
                        : '任务失败'),
                ),
              );
            }
            return;
          }
        }
      } catch {
        // 网络短暂异常时保留当前任务并继续轮询。
      }
      window.setTimeout(() => void tick(), 500);
    };
    void tick();
  });
}

function cancelTask(active: ActiveTask): Promise<DispatchTask> {
  if (active.phase === 'shelf_internal') {
    return cancelShelfInternal(active.taskId);
  }
  return active.phase === 'takeout'
    ? cancelCompleteTakeout(active.taskId)
    : cancelCompleteReturn(active.taskId);
}

export default function QuickTakeReturnDemoPage() {
  const { message } = App.useApp();
  const [books, setBooks] = useState<Book[]>([]);
  const [robots, setRobots] = useState<RobotSummary[]>([]);
  const [annotations, setAnnotations] = useState<MapAnnotation[]>([]);
  const [loading, setLoading] = useState(true);
  const [savedOptions] = useState(loadQuickDemoOptions);
  const [demoMode, setDemoMode] = useState<DemoMode>(
    savedOptions?.demoMode ?? 'loop',
  );
  const [robotId, setRobotId] = useState<string | undefined>(
    savedOptions?.robotId,
  );
  const [takeBookId, setTakeBookId] = useState<string | undefined>(
    savedOptions?.takeBookId,
  );
  const [takeBook2Id, setTakeBook2Id] = useState<string | undefined>(
    savedOptions?.takeBook2Id,
  );
  const [takeBook3Id, setTakeBook3Id] = useState<string | undefined>(
    savedOptions?.takeBook3Id,
  );
  const [takeBook4Id, setTakeBook4Id] = useState<string | undefined>(
    savedOptions?.takeBook4Id,
  );
  const [referenceBookId, setReferenceBookId] = useState<string | undefined>(
    savedOptions?.referenceBookId,
  );
  const [referenceBook2Id, setReferenceBook2Id] = useState<string | undefined>(
    savedOptions?.referenceBook2Id,
  );
  const [referenceBook3Id, setReferenceBook3Id] = useState<
    string | undefined
  >(savedOptions?.referenceBook3Id);
  const [referenceBook4Id, setReferenceBook4Id] = useState<
    string | undefined
  >(savedOptions?.referenceBook4Id);
  const [shelf1AnnotationId, setShelf1AnnotationId] = useState<
    string | undefined
  >(savedOptions?.shelf1AnnotationId);
  const [shelf2AnnotationId, setShelf2AnnotationId] = useState<
    string | undefined
  >(savedOptions?.shelf2AnnotationId);
  const [takeoutMode, setTakeoutMode] = useState<TakeoutMode>(
    savedOptions?.takeoutMode ?? 'standard',
  );
  const [book1TakeoutMode, setBook1TakeoutMode] = useState<TakeoutMode>(
    savedOptions?.book1TakeoutMode ?? savedOptions?.takeoutMode ?? 'standard',
  );
  const [book2TakeoutMode, setBook2TakeoutMode] = useState<TakeoutMode>(
    savedOptions?.book2TakeoutMode ?? savedOptions?.takeoutMode ?? 'standard',
  );
  const [book3TakeoutMode, setBook3TakeoutMode] = useState<TakeoutMode>(
    savedOptions?.book3TakeoutMode ?? 'standard',
  );
  const [book4TakeoutMode, setBook4TakeoutMode] = useState<TakeoutMode>(
    savedOptions?.book4TakeoutMode ?? 'standard',
  );
  const [book1ReturnMode, setBook1ReturnMode] = useState<ReturnMode>(
    savedOptions?.book1ReturnMode ?? 'mid',
  );
  const [book2ReturnMode, setBook2ReturnMode] = useState<ReturnMode>(
    savedOptions?.book2ReturnMode ?? 'mid',
  );
  const [book3ReturnMode, setBook3ReturnMode] = useState<ReturnMode>(
    savedOptions?.book3ReturnMode ?? 'mid',
  );
  const [book4ReturnMode, setBook4ReturnMode] = useState<ReturnMode>(
    savedOptions?.book4ReturnMode ?? 'mid',
  );
  const [slot, setSlot] = useState(savedOptions?.slot ?? 1);
  const [liftHeightMm, setLiftHeightMm] = useState(
    savedOptions?.liftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [book1LiftHeightMm, setBook1LiftHeightMm] = useState(
    savedOptions?.book1LiftHeightMm ??
      savedOptions?.shelf1LiftHeightMm ??
      DEFAULT_BOOK_HEIGHT_MM,
  );
  const [book2LiftHeightMm, setBook2LiftHeightMm] = useState(
    savedOptions?.book2LiftHeightMm ??
      savedOptions?.shelf2LiftHeightMm ??
      DEFAULT_BOOK_HEIGHT_MM,
  );
  const [book3LiftHeightMm, setBook3LiftHeightMm] = useState(
    savedOptions?.book3LiftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [book4LiftHeightMm, setBook4LiftHeightMm] = useState(
    savedOptions?.book4LiftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [referenceBook1LiftHeightMm, setReferenceBook1LiftHeightMm] = useState(
    savedOptions?.referenceBook1LiftHeightMm ??
      savedOptions?.shelf1LiftHeightMm ??
      DEFAULT_BOOK_HEIGHT_MM,
  );
  const [referenceBook2LiftHeightMm, setReferenceBook2LiftHeightMm] = useState(
    savedOptions?.referenceBook2LiftHeightMm ??
      savedOptions?.shelf2LiftHeightMm ??
      DEFAULT_BOOK_HEIGHT_MM,
  );
  const [referenceBook3LiftHeightMm, setReferenceBook3LiftHeightMm] = useState(
    savedOptions?.referenceBook3LiftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [referenceBook4LiftHeightMm, setReferenceBook4LiftHeightMm] = useState(
    savedOptions?.referenceBook4LiftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [moveSpeedMps, setMoveSpeedMps] = useState(
    savedOptions?.moveSpeedMps ?? 0.05,
  );
  const [enableVehicleAlignment, setEnableVehicleAlignment] = useState(
    savedOptions?.enableVehicleAlignment ?? true,
  );
  const [navigationOnly, setNavigationOnly] = useState(
    savedOptions?.navigationOnly ?? false,
  );
  const [loopMode, setLoopMode] = useState(savedOptions?.loopMode ?? false);
  const [liftSpeedLevel, setLiftSpeedLevel] = useState(
    savedOptions?.liftSpeedLevel ?? 2,
  );
  const [intervalSeconds, setIntervalSeconds] = useState(
    savedOptions?.intervalSeconds ?? QUICK_DEMO_INTERVAL_MS / 1000,
  );
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle');
  const [currentTask, setCurrentTask] = useState<DispatchTask>();
  const [round, setRound] = useState(0);
  const [completedRounds, setCompletedRounds] = useState(0);
  const [remainingMs, setRemainingMs] = useState<number>();
  const [lastError, setLastError] = useState<string>();

  const stopRef = useRef(false);
  const unmountedRef = useRef(false);
  const activeTaskRef = useRef<ActiveTask | null>(null);
  const previousRobotIdRef = useRef(robotId);

  function cancelActiveTask() {
    const active = activeTaskRef.current;
    if (active) void cancelTask(active).catch(() => undefined);
  }

  useEffect(() => {
    (async () => {
      try {
        const [bookList, robotList] = await Promise.all([
          listBooks(),
          getRobots(),
        ]);
        setBooks(bookList);
        setRobots(robotList);
        setRobotId((current) =>
          robotList.some((robot) => robot.id === current)
            ? current
            : robotList[0]?.id,
        );
      } catch (error) {
        message.error(errorMessage(error, '无法加载演示配置。'));
      } finally {
        setLoading(false);
      }
    })();
  }, [message]);

  useEffect(() => {
    if (previousRobotIdRef.current !== robotId) {
      previousRobotIdRef.current = robotId;
      setShelf1AnnotationId(undefined);
      setShelf2AnnotationId(undefined);
    }
  }, [robotId]);

  useEffect(() => {
    let cancelled = false;
    const mapId = robots.find((robot) => robot.id === robotId)?.mapId;
    setAnnotations([]);
    if (!mapId) return;
    getMapAnnotations(mapId)
      .then((items) => {
        if (!cancelled) setAnnotations(items);
      })
      .catch((error) => {
        if (!cancelled) {
          message.error(errorMessage(error, '无法加载书架点位。'));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [robotId, robots, message]);

  useEffect(
    () => () => {
      unmountedRef.current = true;
      stopRef.current = true;
      cancelActiveTask();
    },
    [],
  );

  async function runPhase(
    phase: ActiveTask['phase'],
    create: () => Promise<DispatchTask>,
  ) {
    if (stopRef.current || unmountedRef.current) throw new Error('演示已停止');
    setPhase(phase);
    setRemainingMs(undefined);
    setCurrentTask(undefined);
    const task = await create();
    const active = { phase, taskId: task.id };
    activeTaskRef.current = active;
    setCurrentTask(task);
    if (stopRef.current || unmountedRef.current) {
      await cancelTask(active).catch(() => undefined);
      throw new Error('演示已停止');
    }
    try {
      await waitTaskTerminal(
        task.id,
        setCurrentTask,
        () => unmountedRef.current,
      );
    } finally {
      activeTaskRef.current = null;
    }
  }

  async function start() {
    const takeBook = books.find((book) => book.id === takeBookId);
    const takeBook2 = books.find((book) => book.id === takeBook2Id);
    const takeBook3 = books.find((book) => book.id === takeBook3Id);
    const takeBook4 = books.find((book) => book.id === takeBook4Id);
    const referenceBook = books.find((book) => book.id === referenceBookId);
    const referenceBook2 = books.find((book) => book.id === referenceBook2Id);
    const referenceBook3 = books.find((book) => book.id === referenceBook3Id);
    const referenceBook4 = books.find((book) => book.id === referenceBook4Id);
    const navigationTest = demoMode === 'shelf_internal' && navigationOnly;
    const extendedShelfLoop =
      demoMode === 'shelf_internal' && !navigationTest && loopMode;
    if (!robotId || (!navigationTest && (!takeBook || !referenceBook))) {
      message.error('请选择机器人、目标书1和定位书1。');
      return;
    }
    if (
      demoMode === 'loop' &&
      takeBook &&
      referenceBook &&
      takeBook.id === referenceBook.id
    ) {
      message.error('还书定位书必须留在架上，不能与取书相同。');
      return;
    }
    if (demoMode === 'shelf_internal' && !navigationTest && !takeBook2) {
      message.error('请选择第二轮在书架2取出的目标书2。');
      return;
    }
    if (
      extendedShelfLoop &&
      (!takeBook3 || !takeBook4 || !referenceBook3 || !referenceBook4)
    ) {
      message.error('循环模式请选择第三、第四轮的目标书和定位书。');
      return;
    }
    const shelfBookIds = [
      takeBook?.id,
      takeBook2?.id,
      referenceBook?.id,
      referenceBook2Id,
      ...(extendedShelfLoop
        ? [takeBook3?.id, takeBook4?.id, referenceBook3Id, referenceBook4Id]
        : []),
    ];
    if (
      demoMode === 'shelf_internal' &&
      !navigationTest &&
      new Set(shelfBookIds).size !== shelfBookIds.length
    ) {
      message.error(
        extendedShelfLoop
          ? '四本目标书和四本定位书必须互不相同。'
          : '两本目标书和两本定位书必须互不相同。',
      );
      return;
    }
    if (
      demoMode === 'shelf_internal' &&
      shelf1AnnotationId &&
      shelf1AnnotationId === shelf2AnnotationId
    ) {
      message.error('书架1和书架2必须使用不同点位。');
      return;
    }
    const mapId = robots.find((robot) => robot.id === robotId)?.mapId;
    const toTarget = (annotationId?: string) => {
      const annotation = annotations.find((item) => item.id === annotationId);
      return annotation
        ? { x: annotation.mapX, y: annotation.mapY, yaw: annotation.yaw }
        : undefined;
    };
    const shelf1Target = toTarget(shelf1AnnotationId);
    const shelf2Target = toTarget(shelf2AnnotationId);
    const shelfConfig =
      demoMode === 'shelf_internal' && shelf1Target && shelf2Target && mapId
        ? {
            takeBook2,
            referenceBook2,
            shelf1Target,
            shelf2Target,
            mapId,
          }
        : undefined;
    if (demoMode === 'shelf_internal' && !shelfConfig) {
      message.error(
        navigationTest
          ? '请选择书架1、书架2的地图点位。'
          : '请选择目标书2、定位书2以及书架1、书架2的地图点位。',
      );
      return;
    }

    stopRef.current = false;
    setRunning(true);
    setPhase(shelfConfig ? 'shelf_internal' : 'takeout');
    setRound(0);
    setCompletedRounds(0);
    setRemainingMs(undefined);
    setLastError(undefined);
    setCurrentTask(undefined);

    try {
      if (shelfConfig) {
        setRound(1);
        await runPhase('shelf_internal', () =>
          createShelfInternal({
            robotId,
            bookId: takeBook?.id,
            book2Id: shelfConfig.takeBook2?.id,
            referenceBook1Id: referenceBook?.id,
            referenceBook2Id: shelfConfig.referenceBook2?.id,
            shelf1Target: shelfConfig.shelf1Target,
            shelf2Target: shelfConfig.shelf2Target,
            book1LiftHeightMm,
            book2LiftHeightMm,
            referenceBook1LiftHeightMm,
            referenceBook2LiftHeightMm,
            moveSpeedMps,
            enableVehicleAlignment,
            navigationOnly: navigationTest,
            bookStandSlot: slot,
            book1TakeoutMode,
            book2TakeoutMode,
            book1ReturnMode,
            book2ReturnMode,
            liftSpeedLevel,
            mapId: shelfConfig.mapId,
            shelf1AnnotationId,
            shelf2AnnotationId,
            ...(extendedShelfLoop
              ? {
                  enableLoopMode: true,
                  book3Id: takeBook3?.id,
                  book4Id: takeBook4?.id,
                  referenceBook3Id,
                  referenceBook4Id,
                  book3LiftHeightMm,
                  book4LiftHeightMm,
                  referenceBook3LiftHeightMm,
                  referenceBook4LiftHeightMm,
                  book3TakeoutMode,
                  book4TakeoutMode,
                  book3ReturnMode,
                  book4ReturnMode,
                }
              : {}),
          }),
        );
        if (stopRef.current || unmountedRef.current) return;
        if (!navigationTest) {
          setPhase('disable');
          setCurrentTask(undefined);
          await disableArm();
          setCompletedRounds(1);
        }
      } else {
        if (!takeBook || !referenceBook) {
          throw new Error('请选择目标书和定位书。');
        }
        await runQuickTakeReturnDemo({
          shouldStop: () => stopRef.current || unmountedRef.current,
          intervalMs: intervalSeconds * 1000,
          takeout: async () => {
            setRound((value) => value + 1);
            await runPhase('takeout', () =>
              createCompleteTakeout({
                robotId,
                templateId: takeBook.templateId,
                bookId: takeBook.id,
                liftHeightMm,
                destinationSlot: slot,
                takeoutMode,
                liftSpeedLevel,
                sendNavigation: false,
              }),
            );
          },
          returnBook: () =>
            runPhase('return', () =>
              createCompleteReturn({
                robotId,
                templateId: referenceBook.templateId,
                bookId: takeBook.id,
                liftHeightMm,
                sourceSlot: slot,
                liftSpeedLevel,
                sendNavigation: false,
                returnMode: 'mid',
              }),
            ),
          disableArm: async () => {
            setPhase('disable');
            setCurrentTask(undefined);
            await disableArm();
            setCompletedRounds((value) => value + 1);
          },
          onWait: (remaining) => {
            setPhase('wait');
            setRemainingMs(remaining);
          },
        });
      }
    } catch (error) {
      if (!stopRef.current && !unmountedRef.current) {
        const text = errorMessage(error, '演示执行失败');
        setLastError(text);
        message.error(text);
      }
    } finally {
      activeTaskRef.current = null;
      if (!unmountedRef.current) {
        setRunning(false);
        setPhase('idle');
        setCurrentTask(undefined);
        setRemainingMs(undefined);
      }
    }
  }

  function saveOptions() {
    const saved = saveQuickDemoOptions({
      demoMode,
      robotId,
      takeBookId,
      takeBook2Id,
      takeBook3Id,
      takeBook4Id,
      referenceBookId,
      referenceBook2Id,
      referenceBook3Id,
      referenceBook4Id,
      shelf1AnnotationId,
      shelf2AnnotationId,
      takeoutMode,
      book1TakeoutMode,
      book2TakeoutMode,
      book3TakeoutMode,
      book4TakeoutMode,
      book1ReturnMode,
      book2ReturnMode,
      book3ReturnMode,
      book4ReturnMode,
      slot,
      liftHeightMm,
      book1LiftHeightMm,
      book2LiftHeightMm,
      book3LiftHeightMm,
      book4LiftHeightMm,
      referenceBook1LiftHeightMm,
      referenceBook2LiftHeightMm,
      referenceBook3LiftHeightMm,
      referenceBook4LiftHeightMm,
      moveSpeedMps,
      enableVehicleAlignment,
      navigationOnly,
      loopMode,
      liftSpeedLevel,
      intervalSeconds,
    });
    if (saved) {
      message.success('演示配置已保存，下次打开本页将自动恢复。');
    } else {
      message.error('浏览器存储不可用，演示配置保存失败。');
    }
  }

  function stop() {
    stopRef.current = true;
    cancelActiveTask();
    message.info('已请求停止：当前动作将取消，间歇等待会立即结束。');
  }

  const bookOptions = books.map((book) => ({
    value: book.id,
    label: book.name,
  }));
  const configuredShelfBookIds = [
    takeBookId,
    takeBook2Id,
    referenceBookId,
    referenceBook2Id,
    ...(loopMode
      ? [takeBook3Id, takeBook4Id, referenceBook3Id, referenceBook4Id]
      : []),
  ];
  const selectionInvalid =
    demoMode === 'loop'
      ? Boolean(takeBookId && referenceBookId && takeBookId === referenceBookId)
      : !navigationOnly &&
        configuredShelfBookIds.every(Boolean) &&
        new Set(configuredShelfBookIds).size !== configuredShelfBookIds.length;
  const shelfTargetsInvalid = Boolean(
    shelf1AnnotationId && shelf1AnnotationId === shelf2AnnotationId,
  );
  const shelfConfigIncomplete =
    demoMode === 'shelf_internal' &&
    (!shelf1AnnotationId ||
      !shelf2AnnotationId ||
      shelfTargetsInvalid ||
      (!navigationOnly && (!takeBook2Id || !referenceBook2Id)) ||
      (loopMode &&
        !navigationOnly &&
        (!takeBook3Id ||
          !takeBook4Id ||
          !referenceBook3Id ||
          !referenceBook4Id)));
  const additionalRoundConfigs = [
    {
      round: 3,
      takeShelf: 1,
      returnShelf: 2,
      takeBookId: takeBook3Id,
      setTakeBookId: setTakeBook3Id,
      referenceBookId: referenceBook4Id,
      setReferenceBookId: setReferenceBook4Id,
      takeoutMode: book3TakeoutMode,
      setTakeoutMode: setBook3TakeoutMode,
      returnMode: book3ReturnMode,
      setReturnMode: setBook3ReturnMode,
      takeHeightMm: book3LiftHeightMm,
      setTakeHeightMm: setBook3LiftHeightMm,
      returnHeightMm: referenceBook4LiftHeightMm,
      setReturnHeightMm: setReferenceBook4LiftHeightMm,
    },
    {
      round: 4,
      takeShelf: 2,
      returnShelf: 1,
      takeBookId: takeBook4Id,
      setTakeBookId: setTakeBook4Id,
      referenceBookId: referenceBook3Id,
      setReferenceBookId: setReferenceBook3Id,
      takeoutMode: book4TakeoutMode,
      setTakeoutMode: setBook4TakeoutMode,
      returnMode: book4ReturnMode,
      setReturnMode: setBook4ReturnMode,
      takeHeightMm: book4LiftHeightMm,
      setTakeHeightMm: setBook4LiftHeightMm,
      returnHeightMm: referenceBook3LiftHeightMm,
      setReturnHeightMm: setReferenceBook3LiftHeightMm,
    },
  ];

  return (
    <PageContainer
      title="快速取还书演示"
      content={
        demoMode === 'loop'
          ? '复用原地快速取书和快速还书流程，按设定的固定升降杆高度持续循环演示。每轮取还完成后机械臂失能，等待 60 秒再自动开始下一轮。'
          : navigationOnly
            ? '仅测导航：不抓书，在两个书架点之间持续前后移动，每端到点静止 1 秒后直接返回，直到手动停止。'
            : loopMode
              ? '在两个位于同一直线的书架间执行四轮独立取还：现有两轮完成后，追加书架1取书3 → 书架2还书3并取书4 → 书架1还书4。每轮独立设置书籍和层高。'
              : '在两个位于同一直线的书架间执行两轮独立取还：书架1取书1 → 书架2还书1并取书2 → 书架1还书2。每轮独立设置书籍和层高，架内只前后移动。'
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        title="演示将真实驱动机器人机构"
        description={
          demoMode === 'loop'
            ? '开始前请确认机器人已位于作业位、机构周边清场且实体急停可触达。循环由本页面驱动，运行期间请保持页面打开；任一步失败会停止演示。'
            : '开始前请确认机器人已位于书架1作业位、两书架间直线通道清场且实体急停可触达。每次底盘移动前升降杆都会降至 10mm；运行期间请保持页面打开。'
        }
      />
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Card title="演示配置" loading={loading}>
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <div>
              <Typography.Text type="secondary">机器人</Typography.Text>
              <Select
                style={{ width: '100%' }}
                placeholder="选择机器人"
                value={robotId}
                onChange={setRobotId}
                options={robots.map((robot) => ({
                  value: robot.id,
                  label: `${robot.name}（${robot.id}）`,
                }))}
                disabled={running}
              />
            </div>
            <div>
              <Typography.Text type="secondary">演示模式</Typography.Text>
              <Radio.Group
                style={{ display: 'flex' }}
                value={demoMode}
                onChange={(event) =>
                  setDemoMode(event.target.value as DemoMode)
                }
                options={[
                  { value: 'loop', label: '原地循环取还书' },
                  { value: 'shelf_internal', label: '架内取还书' },
                ]}
                optionType="button"
                disabled={running}
              />
            </div>
            {demoMode === 'loop' ? (
              <div>
                <Typography.Text type="secondary">取书模式</Typography.Text>
                <Radio.Group
                  style={{ display: 'flex' }}
                  value={takeoutMode}
                  onChange={(event) =>
                    setTakeoutMode(event.target.value as TakeoutMode)
                  }
                  options={[
                    { value: 'standard', label: '普通取书' },
                    { value: 'mid', label: '中位取书' },
                  ]}
                  optionType="button"
                  disabled={running}
                />
              </div>
            ) : null}
            {demoMode === 'shelf_internal' ? (
              <div>
                <Space>
                  <Typography.Text type="secondary">仅测导航</Typography.Text>
                  <Switch
                    aria-label="仅测导航"
                    checked={navigationOnly}
                    onChange={setNavigationOnly}
                    checkedChildren="开启"
                    unCheckedChildren="关闭"
                    disabled={running}
                  />
                </Space>
                <div>
                  <Typography.Text type="secondary">
                    开启后不抓书，只在两个点位间循环前后移动，每端到点静止 1
                    秒后直接返回。
                  </Typography.Text>
                </div>
              </div>
            ) : null}
            {demoMode === 'shelf_internal' && !navigationOnly ? (
              <div>
                <Space>
                  <Typography.Text type="secondary">循环模式</Typography.Text>
                  <Switch
                    aria-label="循环模式"
                    checked={loopMode}
                    onChange={setLoopMode}
                    checkedChildren="开启"
                    unCheckedChildren="关闭"
                    disabled={running}
                  />
                </Space>
                <div>
                  <Typography.Text type="secondary">
                    开启后在现有两轮之后追加第三、第四轮取还；关闭时仍只执行现有两轮。
                  </Typography.Text>
                </div>
              </div>
            ) : null}
            {demoMode === 'shelf_internal' && !navigationOnly ? (
              <div>
                <Space>
                  <Typography.Text type="secondary">
                    车辆居中对齐服务
                  </Typography.Text>
                  <Switch
                    aria-label="车辆居中对齐服务"
                    checked={enableVehicleAlignment}
                    onChange={setEnableVehicleAlignment}
                    checkedChildren="开启"
                    unCheckedChildren="关闭"
                    disabled={running}
                  />
                </Space>
                <div>
                  <Typography.Text type="secondary">
                    关闭后仅跳过视觉居中车辆微调，架内移动仍执行。
                  </Typography.Text>
                </div>
              </div>
            ) : null}
            {demoMode === 'loop' || !navigationOnly ? (
              <div>
                <Typography.Text type="secondary">
                  {demoMode === 'loop'
                    ? '每轮取出的书'
                    : '目标书1（第一轮从书架1取出）'}
                </Typography.Text>
                <Select
                  style={{ width: '100%' }}
                  placeholder={
                    demoMode === 'loop'
                      ? '选择要反复取还的书'
                      : '选择第一轮取还的书1'
                  }
                  value={takeBookId}
                  onChange={(value) => {
                    setTakeBookId(value);
                    const annotationId = books.find(
                      (book) => book.id === value,
                    )?.annotationId;
                    if (annotationId) setShelf1AnnotationId(annotationId);
                  }}
                  options={bookOptions}
                  showSearch={{ optionFilterProp: 'label' }}
                  disabled={running}
                />
              </div>
            ) : null}
            {demoMode === 'shelf_internal' && !navigationOnly ? (
              <>
                <Space wrap size="middle">
                  <div>
                    <Typography.Text type="secondary">
                      书1取书模式　
                    </Typography.Text>
                    <Select
                      aria-label="书1取书模式"
                      value={book1TakeoutMode}
                      onChange={setBook1TakeoutMode}
                      options={TAKEOUT_MODE_OPTIONS}
                      style={{ width: 140 }}
                      disabled={running}
                    />
                  </div>
                  <div>
                    <Typography.Text type="secondary">
                      书1还书模式　
                    </Typography.Text>
                    <Select
                      aria-label="书1还书模式"
                      value={book1ReturnMode}
                      onChange={setBook1ReturnMode}
                      options={RETURN_MODE_OPTIONS}
                      style={{ width: 140 }}
                      disabled={running}
                    />
                  </div>
                </Space>
                <div>
                  <Typography.Text type="secondary">
                    书1取书升降高度　
                  </Typography.Text>
                  <InputNumber
                    min={10}
                    max={1700}
                    precision={0}
                    value={book1LiftHeightMm}
                    onChange={(value) =>
                      setBook1LiftHeightMm(
                        Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                      )
                    }
                    suffix="mm"
                    style={{ width: 140 }}
                    disabled={running}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">
                    目标书2（第二轮从书架2取出）
                  </Typography.Text>
                  <Select
                    style={{ width: '100%' }}
                    placeholder="选择第二轮取还的书2"
                    value={takeBook2Id}
                    onChange={(value) => {
                      setTakeBook2Id(value);
                      const annotationId = books.find(
                        (book) => book.id === value,
                      )?.annotationId;
                      if (annotationId) setShelf2AnnotationId(annotationId);
                    }}
                    options={bookOptions}
                    showSearch={{ optionFilterProp: 'label' }}
                    disabled={running}
                    status={selectionInvalid ? 'error' : undefined}
                  />
                </div>
                <Space wrap size="middle">
                  <div>
                    <Typography.Text type="secondary">
                      书2取书模式　
                    </Typography.Text>
                    <Select
                      aria-label="书2取书模式"
                      value={book2TakeoutMode}
                      onChange={setBook2TakeoutMode}
                      options={TAKEOUT_MODE_OPTIONS}
                      style={{ width: 140 }}
                      disabled={running}
                    />
                  </div>
                  <div>
                    <Typography.Text type="secondary">
                      书2还书模式　
                    </Typography.Text>
                    <Select
                      aria-label="书2还书模式"
                      value={book2ReturnMode}
                      onChange={setBook2ReturnMode}
                      options={RETURN_MODE_OPTIONS}
                      style={{ width: 140 }}
                      disabled={running}
                    />
                  </div>
                </Space>
                <div>
                  <Typography.Text type="secondary">
                    书2取书升降高度　
                  </Typography.Text>
                  <InputNumber
                    min={10}
                    max={1700}
                    precision={0}
                    value={book2LiftHeightMm}
                    onChange={(value) =>
                      setBook2LiftHeightMm(
                        Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                      )
                    }
                    suffix="mm"
                    style={{ width: 140 }}
                    disabled={running}
                  />
                </div>
              </>
            ) : null}
            {demoMode === 'loop' || !navigationOnly ? (
              <div>
                <Typography.Text type="secondary">
                  {demoMode === 'loop'
                    ? '还书定位书（还到其左边）'
                    : '书架1的定位书1（还到其左边）'}
                </Typography.Text>
                <Select
                  style={{ width: '100%' }}
                  placeholder="选择留在架上的定位书"
                  value={referenceBookId}
                  onChange={(value) => {
                    setReferenceBookId(value);
                    const annotationId = books.find(
                      (book) => book.id === value,
                    )?.annotationId;
                    if (annotationId) setShelf1AnnotationId(annotationId);
                  }}
                  options={bookOptions}
                  showSearch={{ optionFilterProp: 'label' }}
                  disabled={running}
                  status={selectionInvalid ? 'error' : undefined}
                />
                {selectionInvalid ? (
                  <Typography.Text type="danger">
                    {demoMode === 'loop'
                      ? '还书定位书不能与每轮取出的书相同。'
                      : loopMode
                        ? '四本目标书和四本定位书必须互不相同。'
                        : '两本目标书和两本定位书必须互不相同。'}
                  </Typography.Text>
                ) : null}
              </div>
            ) : null}
            {demoMode === 'shelf_internal' && !navigationOnly ? (
              <>
                <div>
                  <Typography.Text type="secondary">
                    定位书1还书升降高度（书2还到其旁）　
                  </Typography.Text>
                  <InputNumber
                    min={10}
                    max={1700}
                    precision={0}
                    value={referenceBook1LiftHeightMm}
                    onChange={(value) =>
                      setReferenceBook1LiftHeightMm(
                        Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                      )
                    }
                    suffix="mm"
                    style={{ width: 140 }}
                    disabled={running}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">
                    书架2的定位书2（还到其左边）
                  </Typography.Text>
                  <Select
                    style={{ width: '100%' }}
                    placeholder="选择留在书架2上的定位书"
                    value={referenceBook2Id}
                    onChange={(value) => {
                      setReferenceBook2Id(value);
                      const annotationId = books.find(
                        (book) => book.id === value,
                      )?.annotationId;
                      if (annotationId) setShelf2AnnotationId(annotationId);
                    }}
                    options={bookOptions}
                    showSearch={{ optionFilterProp: 'label' }}
                    disabled={running}
                    status={selectionInvalid ? 'error' : undefined}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">
                    定位书2还书升降高度（书1还到其旁）　
                  </Typography.Text>
                  <InputNumber
                    min={10}
                    max={1700}
                    precision={0}
                    value={referenceBook2LiftHeightMm}
                    onChange={(value) =>
                      setReferenceBook2LiftHeightMm(
                        Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                      )
                    }
                    suffix="mm"
                    style={{ width: 140 }}
                    disabled={running}
                  />
                </div>
              </>
            ) : null}
            {demoMode === 'shelf_internal' && !navigationOnly && loopMode
              ? additionalRoundConfigs.map((config) => (
                  <div key={config.round}>
                    <Typography.Text strong>
                      第{config.round}轮（追加）
                    </Typography.Text>
                    <div>
                      <Typography.Text type="secondary">
                        目标书{config.round}（第{config.round}轮从书架
                        {config.takeShelf}取出）
                      </Typography.Text>
                      <Select
                        style={{ width: '100%' }}
                        placeholder={`选择第${config.round}轮取还的书${config.round}`}
                        value={config.takeBookId}
                        onChange={(value) => {
                          config.setTakeBookId(value);
                          const annotationId = books.find(
                            (book) => book.id === value,
                          )?.annotationId;
                          if (annotationId && config.takeShelf === 1) {
                            setShelf1AnnotationId(annotationId);
                          }
                          if (annotationId && config.takeShelf === 2) {
                            setShelf2AnnotationId(annotationId);
                          }
                        }}
                        options={bookOptions}
                        showSearch={{ optionFilterProp: 'label' }}
                        disabled={running}
                        status={selectionInvalid ? 'error' : undefined}
                      />
                    </div>
                    <Space wrap size="middle">
                      <div>
                        <Typography.Text type="secondary">
                          书{config.round}取书模式　
                        </Typography.Text>
                        <Select
                          aria-label={`书${config.round}取书模式`}
                          value={config.takeoutMode}
                          onChange={config.setTakeoutMode}
                          options={TAKEOUT_MODE_OPTIONS}
                          style={{ width: 140 }}
                          disabled={running}
                        />
                      </div>
                      <div>
                        <Typography.Text type="secondary">
                          书{config.round}还书模式　
                        </Typography.Text>
                        <Select
                          aria-label={`书${config.round}还书模式`}
                          value={config.returnMode}
                          onChange={config.setReturnMode}
                          options={RETURN_MODE_OPTIONS}
                          style={{ width: 140 }}
                          disabled={running}
                        />
                      </div>
                    </Space>
                    <div>
                      <Typography.Text type="secondary">
                        书{config.round}取书升降高度　
                      </Typography.Text>
                      <InputNumber
                        min={10}
                        max={1700}
                        precision={0}
                        value={config.takeHeightMm}
                        onChange={(value) =>
                          config.setTakeHeightMm(
                            Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                          )
                        }
                        suffix="mm"
                        style={{ width: 140 }}
                        disabled={running}
                      />
                    </div>
                    <div>
                      <Typography.Text type="secondary">
                        书架{config.returnShelf}的定位书{config.round}
                        （书{config.round}还到其左边）
                      </Typography.Text>
                      <Select
                        style={{ width: '100%' }}
                        placeholder={`选择留在书架${config.returnShelf}上的定位书${config.round}`}
                        value={config.referenceBookId}
                        onChange={(value) => {
                          config.setReferenceBookId(value);
                          const annotationId = books.find(
                            (book) => book.id === value,
                          )?.annotationId;
                          if (annotationId && config.returnShelf === 1) {
                            setShelf1AnnotationId(annotationId);
                          }
                          if (annotationId && config.returnShelf === 2) {
                            setShelf2AnnotationId(annotationId);
                          }
                        }}
                        options={bookOptions}
                        showSearch={{ optionFilterProp: 'label' }}
                        disabled={running}
                        status={selectionInvalid ? 'error' : undefined}
                      />
                    </div>
                    <div>
                      <Typography.Text type="secondary">
                        定位书{config.round}还书升降高度（书{config.round}
                        还到其旁）　
                      </Typography.Text>
                      <InputNumber
                        min={10}
                        max={1700}
                        precision={0}
                        value={config.returnHeightMm}
                        onChange={(value) =>
                          config.setReturnHeightMm(
                            Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                          )
                        }
                        suffix="mm"
                        style={{ width: 140 }}
                        disabled={running}
                      />
                    </div>
                  </div>
                ))
              : null}
            {demoMode === 'shelf_internal' ? (
              <>
                <div>
                  <Typography.Text type="secondary">
                    书架1点位（机器人起始作业位）
                  </Typography.Text>
                  <AnnotationTargetSelect
                    annotations={annotations}
                    value={shelf1AnnotationId}
                    onChange={setShelf1AnnotationId}
                    loading={loading}
                    disabled={running}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">书架2点位</Typography.Text>
                  <AnnotationTargetSelect
                    annotations={annotations}
                    value={shelf2AnnotationId}
                    onChange={setShelf2AnnotationId}
                    loading={loading}
                    disabled={running}
                  />
                  {shelfTargetsInvalid ? (
                    <Typography.Text type="danger">
                      书架1和书架2必须使用不同点位。
                    </Typography.Text>
                  ) : null}
                </div>
              </>
            ) : null}
            <Space wrap size="middle">
              {demoMode === 'loop' || !navigationOnly ? (
                <div>
                  <Typography.Text type="secondary">书立槽位　</Typography.Text>
                  <Select
                    value={slot}
                    onChange={setSlot}
                    options={BOOK_STAND_SLOTS.map((value) => ({
                      value,
                      label: `${value} 号槽`,
                    }))}
                    disabled={running}
                  />
                </div>
              ) : null}
              {demoMode === 'loop' ? (
                <div>
                  <Typography.Text type="secondary">
                    固定升降杆高度　
                  </Typography.Text>
                  <InputNumber
                    min={10}
                    max={1700}
                    precision={0}
                    value={liftHeightMm}
                    onChange={(value) =>
                      setLiftHeightMm(Number(value ?? DEFAULT_BOOK_HEIGHT_MM))
                    }
                    suffix="mm"
                    style={{ width: 140 }}
                    disabled={running}
                  />
                </div>
              ) : null}
              <div>
                <Typography.Text type="secondary">升降速度　</Typography.Text>
                <Select
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
              {demoMode === 'shelf_internal' ? (
                <div>
                  <Typography.Text type="secondary">
                    架内移动速度　
                  </Typography.Text>
                  <InputNumber
                    min={0}
                    max={0.5}
                    step={0.01}
                    precision={2}
                    value={moveSpeedMps}
                    onChange={(value) => setMoveSpeedMps(Number(value ?? 0.05))}
                    suffix="m/s"
                    style={{ width: 140 }}
                    disabled={running}
                  />
                </div>
              ) : null}
              {demoMode === 'loop' ? (
                <div>
                  <Typography.Text type="secondary">取还间隔　</Typography.Text>
                  <InputNumber
                    min={1}
                    max={3600}
                    precision={0}
                    value={intervalSeconds}
                    onChange={(value) =>
                      setIntervalSeconds(
                        Number(value ?? QUICK_DEMO_INTERVAL_MS / 1000),
                      )
                    }
                    suffix="秒"
                    style={{ width: 140 }}
                    disabled={running}
                  />
                </div>
              ) : null}
            </Space>
            <Typography.Text type="secondary">
              {demoMode === 'loop'
                ? `取书和还书全程使用同一个固定升降杆高度，不再读取书籍登记高度。固定流程：快速取书到所选槽位 → 从该槽位快速还书 → 机械臂失能 → 等待 ${intervalSeconds} 秒 → 下一轮。`
                : navigationOnly
                  ? `不执行取书或还书。书架1 → 书架2 → 静止 1 秒 → 书架1 → 静止 1 秒，持续循环，移动速度 ${moveSpeedMps} m/s；每次移动前升降杆降至10mm。`
                  : `${loopMode ? '第一轮书架1取书1、书架2还书1，第二轮书架2取书2、书架1还书2，第三轮书架1取书3、书架2还书3，第四轮书架2取书4、书架1还书4' : '第一轮书架1取书1、书架2还书1，第二轮书架2取书2、书架1还书2'}；每本书可独立选择普通/中位取书、中位/末尾还书及各自高度。${loopMode ? '八' : '四'}次动作${enableVehicleAlignment ? '启用' : '禁用'}车辆居中对齐服务，架内移动速度为 ${moveSpeedMps} m/s；每次底盘移动前升降杆都降至10mm。`}
            </Typography.Text>
            <Space wrap>
              <Button
                icon={<SaveOutlined />}
                onClick={saveOptions}
                disabled={running}
              >
                保存配置
              </Button>
              <Button
                type="primary"
                onClick={() => void start()}
                disabled={
                  running ||
                  !robotId ||
                  ((demoMode === 'loop' || !navigationOnly) &&
                    (!takeBookId || !referenceBookId)) ||
                  selectionInvalid ||
                  shelfConfigIncomplete
                }
              >
                {demoMode === 'loop'
                  ? '开始循环演示'
                  : navigationOnly
                    ? '开始仅测导航'
                    : '开始架内取还书'}
              </Button>
              <Button danger onClick={stop} disabled={!running}>
                停止演示
              </Button>
            </Space>
          </Space>
        </Card>

        <Card title="运行状态">
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <Space wrap size="middle">
              <Tag color={running ? 'processing' : 'default'}>
                {phase === 'shelf_internal' && navigationOnly
                  ? '仅测导航'
                  : PHASE_TEXT[phase]}
              </Tag>
              <span>当前轮次：{round}</span>
              <span>已完成轮次：{completedRounds}</span>
              {phase === 'wait' && remainingMs !== undefined ? (
                <Typography.Text strong>
                  {Math.ceil(remainingMs / 1000)} 秒后开始下一轮
                </Typography.Text>
              ) : null}
            </Space>
            {currentTask?.workflowMessage ? (
              <Typography.Text type="secondary">
                {currentTask.workflowMessage}
              </Typography.Text>
            ) : null}
            {currentTask ? (
              <Progress
                percent={currentTask.progress}
                size="small"
                status={
                  currentTask.status === 'failed' ? 'exception' : 'active'
                }
              />
            ) : null}
            {lastError ? (
              <Alert type="error" showIcon title={lastError} />
            ) : null}
          </Space>
        </Card>
      </Space>
    </PageContainer>
  );
}

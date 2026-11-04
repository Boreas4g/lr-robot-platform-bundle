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
  const [referenceBookId, setReferenceBookId] = useState<string | undefined>(
    savedOptions?.referenceBookId,
  );
  const [referenceBook2Id, setReferenceBook2Id] = useState<string | undefined>(
    savedOptions?.referenceBook2Id,
  );
  const [shelf1AnnotationId, setShelf1AnnotationId] = useState<
    string | undefined
  >(savedOptions?.shelf1AnnotationId);
  const [shelf2AnnotationId, setShelf2AnnotationId] = useState<
    string | undefined
  >(savedOptions?.shelf2AnnotationId);
  const [takeoutMode, setTakeoutMode] = useState<TakeoutMode>(
    savedOptions?.takeoutMode ?? 'standard',
  );
  const [slot, setSlot] = useState(savedOptions?.slot ?? 1);
  const [liftHeightMm, setLiftHeightMm] = useState(
    savedOptions?.liftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [shelf1LiftHeightMm, setShelf1LiftHeightMm] = useState(
    savedOptions?.shelf1LiftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [shelf2LiftHeightMm, setShelf2LiftHeightMm] = useState(
    savedOptions?.shelf2LiftHeightMm ?? DEFAULT_BOOK_HEIGHT_MM,
  );
  const [moveSpeedMps, setMoveSpeedMps] = useState(
    savedOptions?.moveSpeedMps ?? 0.05,
  );
  const [enableVehicleAlignment, setEnableVehicleAlignment] = useState(
    savedOptions?.enableVehicleAlignment ?? true,
  );
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
    const referenceBook = books.find((book) => book.id === referenceBookId);
    const referenceBook2 = books.find((book) => book.id === referenceBook2Id);
    if (!robotId || !takeBook || !referenceBook) {
      message.error('请选择机器人、目标书和定位书1。');
      return;
    }
    if (demoMode === 'loop' && takeBook.id === referenceBook.id) {
      message.error('还书定位书必须留在架上，不能与取书相同。');
      return;
    }
    if (
      demoMode === 'shelf_internal' &&
      new Set([takeBook.id, referenceBook.id, referenceBook2Id]).size !== 3
    ) {
      message.error('目标书、定位书1和定位书2必须互不相同。');
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
      demoMode === 'shelf_internal' &&
      referenceBook2 &&
      shelf1Target &&
      shelf2Target &&
      mapId
        ? {
            referenceBook2,
            shelf1Target,
            shelf2Target,
            mapId,
          }
        : undefined;
    if (demoMode === 'shelf_internal' && !shelfConfig) {
      message.error('请选择定位书2以及书架1、书架2的地图点位。');
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
            bookId: takeBook.id,
            referenceBook1Id: referenceBook.id,
            referenceBook2Id: shelfConfig.referenceBook2.id,
            shelf1Target: shelfConfig.shelf1Target,
            shelf2Target: shelfConfig.shelf2Target,
            shelf1LiftHeightMm,
            shelf2LiftHeightMm,
            moveSpeedMps,
            enableVehicleAlignment,
            bookStandSlot: slot,
            takeoutMode,
            liftSpeedLevel,
            mapId: shelfConfig.mapId,
            shelf1AnnotationId,
            shelf2AnnotationId,
          }),
        );
        if (stopRef.current || unmountedRef.current) return;
        setPhase('disable');
        setCurrentTask(undefined);
        await disableArm();
        setCompletedRounds(1);
      } else {
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
      referenceBookId,
      referenceBook2Id,
      shelf1AnnotationId,
      shelf2AnnotationId,
      takeoutMode,
      slot,
      liftHeightMm,
      shelf1LiftHeightMm,
      shelf2LiftHeightMm,
      moveSpeedMps,
      enableVehicleAlignment,
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
  const selectionInvalid =
    demoMode === 'loop'
      ? Boolean(takeBookId && referenceBookId && takeBookId === referenceBookId)
      : Boolean(
          takeBookId &&
            referenceBookId &&
            referenceBook2Id &&
            new Set([takeBookId, referenceBookId, referenceBook2Id]).size !== 3,
        );
  const shelfTargetsInvalid = Boolean(
    shelf1AnnotationId && shelf1AnnotationId === shelf2AnnotationId,
  );
  const shelfConfigIncomplete =
    demoMode === 'shelf_internal' &&
    (!referenceBook2Id ||
      !shelf1AnnotationId ||
      !shelf2AnnotationId ||
      shelfTargetsInvalid);

  return (
    <PageContainer
      title="快速取还书演示"
      content={
        demoMode === 'loop'
          ? '复用原地快速取书和快速还书流程，按设定的固定升降杆高度持续循环演示。每轮取还完成后机械臂失能，等待 60 秒再自动开始下一轮。'
          : '在两个位于同一直线的书架间执行一次完整取还：书架1取书 → 书架2还书并再次取书 → 书架1还书。架内只前后移动。'
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
            {demoMode === 'shelf_internal' ? (
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
            <div>
              <Typography.Text type="secondary">
                {demoMode === 'loop' ? '每轮取出的书' : '目标书（全程同一本）'}
              </Typography.Text>
              <Select
                style={{ width: '100%' }}
                placeholder="选择要反复取还的书"
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
                    : '目标书、定位书1和定位书2必须互不相同。'}
                </Typography.Text>
              ) : null}
            </div>
            {demoMode === 'shelf_internal' ? (
              <>
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
                    书架1点位（机器人起始作业位）
                  </Typography.Text>
                  <AnnotationTargetSelect
                    annotations={annotations}
                    value={shelf1AnnotationId}
                    onChange={setShelf1AnnotationId}
                    loading={loading}
                    disabled={running}
                  />
                  <div style={{ marginTop: 8 }}>
                    <Typography.Text type="secondary">
                      书架1升降杆高度　
                    </Typography.Text>
                    <InputNumber
                      min={10}
                      max={1700}
                      precision={0}
                      value={shelf1LiftHeightMm}
                      onChange={(value) =>
                        setShelf1LiftHeightMm(
                          Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                        )
                      }
                      suffix="mm"
                      style={{ width: 140 }}
                      disabled={running}
                    />
                  </div>
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
                  <div style={{ marginTop: 8 }}>
                    <Typography.Text type="secondary">
                      书架2升降杆高度　
                    </Typography.Text>
                    <InputNumber
                      min={10}
                      max={1700}
                      precision={0}
                      value={shelf2LiftHeightMm}
                      onChange={(value) =>
                        setShelf2LiftHeightMm(
                          Number(value ?? DEFAULT_BOOK_HEIGHT_MM),
                        )
                      }
                      suffix="mm"
                      style={{ width: 140 }}
                      disabled={running}
                    />
                  </div>
                  {shelfTargetsInvalid ? (
                    <Typography.Text type="danger">
                      书架1和书架2必须使用不同点位。
                    </Typography.Text>
                  ) : null}
                </div>
              </>
            ) : null}
            <Space wrap size="middle">
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
                : `书架1取还使用书架1升降高度，书架2取还使用书架2升降高度；四次动作${enableVehicleAlignment ? '启用' : '禁用'}车辆居中对齐服务，架内移动速度为 ${moveSpeedMps} m/s。固定流程：书架1取书 → 升降杆降至10mm → 仅沿X移至书架2 → 还到定位书2旁边 → 再取同一本目标书 → 升降杆降至10mm → 仅沿X移回书架1 → 还到定位书1旁边 → 机械臂失能。`}
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
                  !takeBookId ||
                  !referenceBookId ||
                  selectionInvalid ||
                  shelfConfigIncomplete
                }
              >
                {demoMode === 'loop' ? '开始循环演示' : '开始架内取还书'}
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
                {PHASE_TEXT[phase]}
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

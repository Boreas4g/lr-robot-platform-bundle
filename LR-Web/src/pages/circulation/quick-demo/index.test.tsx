import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { App } from 'antd';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  Book,
  DispatchTask,
  RobotSummary,
} from '@/services/libraryRobot/types';
import QuickTakeReturnDemoPage from './index';
import { loadQuickDemoOptions } from './quickDemoOptions';

const mocks = vi.hoisted(() => ({
  cancelCompleteReturn: vi.fn(),
  cancelCompleteTakeout: vi.fn(),
  cancelShelfInternal: vi.fn(),
  createCompleteReturn: vi.fn(),
  createCompleteTakeout: vi.fn(),
  createShelfInternal: vi.fn(),
  disableArm: vi.fn(),
  getMapAnnotations: vi.fn(),
  getRobots: vi.fn(),
  listBooks: vi.fn(),
  pollTasks: vi.fn(),
  tasks: [] as DispatchTask[],
}));

vi.mock('@ant-design/pro-components', () => ({
  PageContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock('@/services/libraryRobot', () => ({
  cancelCompleteReturn: mocks.cancelCompleteReturn,
  cancelCompleteTakeout: mocks.cancelCompleteTakeout,
  cancelShelfInternal: mocks.cancelShelfInternal,
  createCompleteReturn: mocks.createCompleteReturn,
  createCompleteTakeout: mocks.createCompleteTakeout,
  createShelfInternal: mocks.createShelfInternal,
  DEFAULT_BOOK_HEIGHT_MM: 550,
  getMapAnnotations: mocks.getMapAnnotations,
  getRobots: mocks.getRobots,
  listBooks: mocks.listBooks,
  pollTasks: mocks.pollTasks,
}));

vi.mock('@/services/libraryRobot/studio', () => ({
  disableArm: mocks.disableArm,
}));

function task(id: string, type: DispatchTask['type']): DispatchTask {
  return {
    id,
    type,
    robotId: 'LR-01',
    target: '演示',
    status: 'running',
    progress: 0,
    updatedAt: '2026-01-01T00:00:00+00:00',
  };
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.tasks = [];
  mocks.listBooks.mockResolvedValue([
    {
      id: 'BOOK-1',
      name: '取还书',
      templateId: 'TPL-1',
      heightMm: 400,
      annotationId: 'ANN-SHELF-1',
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'BOOK-2',
      name: '定位书',
      templateId: 'TPL-2',
      heightMm: 900,
      annotationId: 'ANN-SHELF-1',
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'BOOK-3',
      name: '定位书2',
      templateId: 'TPL-3',
      heightMm: 700,
      annotationId: 'ANN-SHELF-2',
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'BOOK-4',
      name: '取还书2',
      templateId: 'TPL-4',
      heightMm: 600,
      annotationId: 'ANN-SHELF-2',
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'BOOK-5',
      name: '取还书3',
      templateId: 'TPL-5',
      heightMm: 650,
      annotationId: 'ANN-SHELF-1',
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'BOOK-6',
      name: '定位书3',
      templateId: 'TPL-6',
      heightMm: 670,
      annotationId: 'ANN-SHELF-1',
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'BOOK-7',
      name: '取还书4',
      templateId: 'TPL-7',
      heightMm: 660,
      annotationId: 'ANN-SHELF-2',
      createdAt: '',
      updatedAt: '',
    },
    {
      id: 'BOOK-8',
      name: '定位书4',
      templateId: 'TPL-8',
      heightMm: 680,
      annotationId: 'ANN-SHELF-2',
      createdAt: '',
      updatedAt: '',
    },
  ] satisfies Book[]);
  mocks.getRobots.mockResolvedValue([
    { id: 'LR-01', name: '机器人 1' } as RobotSummary,
  ]);
  mocks.getMapAnnotations.mockResolvedValue([
    {
      id: 'ANN-SHELF-1',
      mapId: 'MAP-1',
      kind: 'shelf',
      label: '测试书架1',
      pixelX: 10,
      pixelY: 10,
      mapX: 0,
      mapY: 0,
      yaw: 0,
      createdAt: '',
      createdBy: 'test',
    },
    {
      id: 'ANN-SHELF-2',
      mapId: 'MAP-1',
      kind: 'shelf',
      label: '测试书架2',
      pixelX: 20,
      pixelY: 20,
      mapX: 1.5,
      mapY: 0,
      yaw: 0,
      createdAt: '',
      createdBy: 'test',
    },
  ]);
  mocks.createCompleteTakeout.mockImplementation(async () => {
    const created = task('TSK-TAKE-1', 'takeout');
    mocks.tasks.push(created);
    return created;
  });
  mocks.createCompleteReturn.mockImplementation(async () => {
    const created = task('TSK-RETURN-1', 'return');
    mocks.tasks.push(created);
    return created;
  });
  mocks.createShelfInternal.mockImplementation(async () => {
    const created = task('TSK-SHELF-1', 'shelf_internal');
    mocks.tasks.push(created);
    return created;
  });
  mocks.pollTasks.mockImplementation(async () =>
    mocks.tasks.map((item) => ({
      ...item,
      status: 'completed',
      progress: 100,
    })),
  );
  mocks.disableArm.mockResolvedValue({ ok: true, enabled: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('快速取还书演示参数', () => {
  it('使用自定义固定高度和取还间隔', async () => {
    render(
      <App>
        <QuickTakeReturnDemoPage />
      </App>,
    );

    await screen.findByText('机器人 1（LR-01）');
    const selects = screen.getAllByRole('combobox');
    fireEvent.mouseDown(selects[1]);
    fireEvent.click(await screen.findByText('取还书'));
    fireEvent.mouseDown(selects[2]);
    const referenceOptions = await screen.findAllByText('定位书');
    fireEvent.click(referenceOptions.at(-1) as HTMLElement);
    fireEvent.click(screen.getByRole('radio', { name: '中位取书' }));
    const numericInputs = screen.getAllByRole('spinbutton');
    fireEvent.change(numericInputs[0], { target: { value: '800' } });
    fireEvent.change(numericInputs[1], { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: '开始循环演示' }));

    await waitFor(() => expect(mocks.disableArm).toHaveBeenCalledTimes(1));
    await screen.findByText('2 秒后开始下一轮');
    expect(mocks.createCompleteTakeout).toHaveBeenCalledWith(
      expect.objectContaining({ liftHeightMm: 800, takeoutMode: 'mid' }),
    );
    expect(mocks.createCompleteReturn).toHaveBeenCalledWith(
      expect.objectContaining({ liftHeightMm: 800 }),
    );

    fireEvent.click(screen.getByRole('button', { name: '停止演示' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始循环演示' }),
      ).toBeEnabled(),
    );
  });

  it('架内取还书提交两本目标书、两本定位书和两个书架点位', async () => {
    mocks.getRobots.mockResolvedValue([
      { id: 'LR-01', name: '机器人 1', mapId: 'MAP-1' } as RobotSummary,
    ]);
    render(
      <App>
        <QuickTakeReturnDemoPage />
      </App>,
    );

    await screen.findByText('机器人 1（LR-01）');
    fireEvent.click(screen.getByRole('radio', { name: '架内取还书' }));
    const selects = screen.getAllByRole('combobox');
    fireEvent.mouseDown(selects[1]);
    fireEvent.click(await screen.findByText('取还书'));
    fireEvent.mouseDown(selects[4]);
    const takeBook2Options = await screen.findAllByText('取还书2');
    fireEvent.click(takeBook2Options.at(-1) as HTMLElement);
    fireEvent.mouseDown(selects[7]);
    const reference1Options = await screen.findAllByText('定位书');
    fireEvent.click(reference1Options.at(-1) as HTMLElement);
    fireEvent.mouseDown(selects[8]);
    const reference2Options = await screen.findAllByText('定位书2');
    fireEvent.click(reference2Options.at(-1) as HTMLElement);
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '书1取书模式' }));
    fireEvent.click(
      (await screen.findAllByText('中位取书')).at(-1) as HTMLElement,
    );
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '书1还书模式' }));
    fireEvent.click(
      (await screen.findAllByText('末尾还书')).at(-1) as HTMLElement,
    );
    fireEvent.click(screen.getByRole('switch', { name: '车辆居中对齐服务' }));

    const heightInputs = screen.getAllByRole('spinbutton');
    expect(heightInputs).toHaveLength(5);
    expect(screen.queryByText('固定升降杆高度　')).not.toBeInTheDocument();
    fireEvent.change(heightInputs[0], { target: { value: '610' } });
    fireEvent.change(heightInputs[1], { target: { value: '620' } });
    fireEvent.change(heightInputs[2], { target: { value: '630' } });
    fireEvent.change(heightInputs[3], { target: { value: '640' } });
    fireEvent.change(heightInputs[4], { target: { value: '0.08' } });

    const startButton = screen.getByRole('button', {
      name: '开始架内取还书',
    });
    await waitFor(() => expect(startButton).toBeEnabled());
    fireEvent.click(startButton);

    await waitFor(() =>
      expect(mocks.createShelfInternal).toHaveBeenCalledTimes(1),
    );
    expect(mocks.createShelfInternal).toHaveBeenCalledWith({
      robotId: 'LR-01',
      bookId: 'BOOK-1',
      book2Id: 'BOOK-4',
      referenceBook1Id: 'BOOK-2',
      referenceBook2Id: 'BOOK-3',
      shelf1Target: { x: 0, y: 0, yaw: 0 },
      shelf2Target: { x: 1.5, y: 0, yaw: 0 },
      book1LiftHeightMm: 610,
      book2LiftHeightMm: 620,
      referenceBook1LiftHeightMm: 630,
      referenceBook2LiftHeightMm: 640,
      moveSpeedMps: 0.08,
      enableVehicleAlignment: false,
      navigationOnly: false,
      bookStandSlot: 1,
      book1TakeoutMode: 'mid',
      book2TakeoutMode: 'standard',
      book1ReturnMode: 'end',
      book2ReturnMode: 'mid',
      liftSpeedLevel: 2,
      mapId: 'MAP-1',
      shelf1AnnotationId: 'ANN-SHELF-1',
      shelf2AnnotationId: 'ANN-SHELF-2',
    });
    expect(mocks.createCompleteTakeout).not.toHaveBeenCalled();
    expect(mocks.createCompleteReturn).not.toHaveBeenCalled();
    await waitFor(() => expect(mocks.disableArm).toHaveBeenCalledTimes(1));
  });

  it('循环模式提交追加的第三第四轮配置', async () => {
    mocks.getRobots.mockResolvedValue([
      { id: 'LR-01', name: '机器人 1', mapId: 'MAP-1' } as RobotSummary,
    ]);
    window.localStorage.setItem(
      'lr-web-quick-demo-options',
      JSON.stringify({
        demoMode: 'shelf_internal',
        robotId: 'LR-01',
        takeBookId: 'BOOK-1',
        takeBook2Id: 'BOOK-4',
        takeBook3Id: 'BOOK-5',
        takeBook4Id: 'BOOK-7',
        referenceBookId: 'BOOK-2',
        referenceBook2Id: 'BOOK-3',
        referenceBook3Id: 'BOOK-6',
        referenceBook4Id: 'BOOK-8',
        shelf1AnnotationId: 'ANN-SHELF-1',
        shelf2AnnotationId: 'ANN-SHELF-2',
        loopMode: true,
        book1LiftHeightMm: 610,
        book2LiftHeightMm: 620,
        book3LiftHeightMm: 650,
        book4LiftHeightMm: 660,
        referenceBook1LiftHeightMm: 630,
        referenceBook2LiftHeightMm: 640,
        referenceBook3LiftHeightMm: 670,
        referenceBook4LiftHeightMm: 680,
        book3TakeoutMode: 'mid',
        book4TakeoutMode: 'standard',
        book3ReturnMode: 'end',
        book4ReturnMode: 'mid',
      }),
    );
    render(
      <App>
        <QuickTakeReturnDemoPage />
      </App>,
    );

    await screen.findByText('机器人 1（LR-01）');
    expect(screen.getByRole('switch', { name: '循环模式' })).toBeChecked();
    expect(screen.getByText(/目标书3/)).toBeInTheDocument();
    expect(screen.getByText(/目标书4/)).toBeInTheDocument();
    const startButton = screen.getByRole('button', {
      name: '开始架内取还书',
    });
    await waitFor(() => expect(startButton).toBeEnabled());
    fireEvent.click(startButton);

    await waitFor(() =>
      expect(mocks.createShelfInternal).toHaveBeenCalledTimes(1),
    );
    expect(mocks.createShelfInternal).toHaveBeenCalledWith(
      expect.objectContaining({
        enableLoopMode: true,
        book3Id: 'BOOK-5',
        book4Id: 'BOOK-7',
        referenceBook3Id: 'BOOK-6',
        referenceBook4Id: 'BOOK-8',
        book3LiftHeightMm: 650,
        book4LiftHeightMm: 660,
        referenceBook3LiftHeightMm: 670,
        referenceBook4LiftHeightMm: 680,
        book3TakeoutMode: 'mid',
        book4TakeoutMode: 'standard',
        book3ReturnMode: 'end',
        book4ReturnMode: 'mid',
      }),
    );
  });

  it('仅测导航只提交两个点位且不执行机械臂失能', async () => {
    mocks.getRobots.mockResolvedValue([
      { id: 'LR-01', name: '机器人 1', mapId: 'MAP-1' } as RobotSummary,
    ]);
    render(
      <App>
        <QuickTakeReturnDemoPage />
      </App>,
    );

    await screen.findByText('机器人 1（LR-01）');
    fireEvent.click(screen.getByRole('radio', { name: '架内取还书' }));
    fireEvent.click(screen.getByRole('switch', { name: '仅测导航' }));
    expect(
      screen.queryByText('目标书1（第一轮从书架1取出）'),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('switch', { name: '车辆居中对齐服务' }),
    ).not.toBeInTheDocument();

    const targetSelects = screen.getAllByRole('combobox');
    fireEvent.mouseDown(targetSelects[1]);
    fireEvent.click(await screen.findByText('测试书架1（书架）'));
    fireEvent.mouseDown(targetSelects[3]);
    fireEvent.click(
      (await screen.findAllByText('测试书架2（书架）')).at(-1) as HTMLElement,
    );
    const startButton = screen.getByRole('button', { name: '开始仅测导航' });
    await waitFor(() => expect(startButton).toBeEnabled());
    fireEvent.click(startButton);

    await waitFor(() =>
      expect(mocks.createShelfInternal).toHaveBeenCalledTimes(1),
    );
    const request = mocks.createShelfInternal.mock.calls[0][0];
    expect(request).toEqual(
      expect.objectContaining({
        robotId: 'LR-01',
        navigationOnly: true,
        shelf1Target: { x: 0, y: 0, yaw: 0 },
        shelf2Target: { x: 1.5, y: 0, yaw: 0 },
        shelf1AnnotationId: 'ANN-SHELF-1',
        shelf2AnnotationId: 'ANN-SHELF-2',
      }),
    );
    expect(request.bookId).toBeUndefined();
    expect(request.book2Id).toBeUndefined();
    expect(request.referenceBook1Id).toBeUndefined();
    expect(request.referenceBook2Id).toBeUndefined();
    expect(mocks.createCompleteTakeout).not.toHaveBeenCalled();
    expect(mocks.createCompleteReturn).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始仅测导航' }),
      ).toBeEnabled(),
    );
    expect(mocks.disableArm).not.toHaveBeenCalled();
  });

  it('保存当前配置并在重新打开页面时恢复', async () => {
    mocks.getRobots.mockResolvedValue([
      { id: 'LR-01', name: '机器人 1', mapId: 'MAP-1' } as RobotSummary,
    ]);
    const first = render(
      <App>
        <QuickTakeReturnDemoPage />
      </App>,
    );

    await screen.findByText('机器人 1（LR-01）');
    fireEvent.click(screen.getByRole('radio', { name: '架内取还书' }));
    const selects = screen.getAllByRole('combobox');
    fireEvent.mouseDown(selects[1]);
    fireEvent.click(await screen.findByText('取还书'));
    fireEvent.mouseDown(selects[4]);
    const takeBook2Options = await screen.findAllByText('取还书2');
    fireEvent.click(takeBook2Options.at(-1) as HTMLElement);
    fireEvent.mouseDown(selects[7]);
    const reference1Options = await screen.findAllByText('定位书');
    fireEvent.click(reference1Options.at(-1) as HTMLElement);
    fireEvent.mouseDown(selects[8]);
    const reference2Options = await screen.findAllByText('定位书2');
    fireEvent.click(reference2Options.at(-1) as HTMLElement);
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '书1取书模式' }));
    fireEvent.click(
      (await screen.findAllByText('中位取书')).at(-1) as HTMLElement,
    );
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '书1还书模式' }));
    fireEvent.click(
      (await screen.findAllByText('末尾还书')).at(-1) as HTMLElement,
    );
    fireEvent.click(screen.getByRole('switch', { name: '车辆居中对齐服务' }));
    const heightInputs = screen.getAllByRole('spinbutton');
    fireEvent.change(heightInputs[0], { target: { value: '610' } });
    fireEvent.change(heightInputs[1], { target: { value: '620' } });
    fireEvent.change(heightInputs[2], { target: { value: '630' } });
    fireEvent.change(heightInputs[3], { target: { value: '640' } });
    fireEvent.change(heightInputs[4], { target: { value: '0.08' } });
    fireEvent.click(screen.getByRole('button', { name: /保存配置/ }));

    await waitFor(() =>
      expect(loadQuickDemoOptions()).toEqual(
        expect.objectContaining({
          demoMode: 'shelf_internal',
          robotId: 'LR-01',
          takeBookId: 'BOOK-1',
          takeBook2Id: 'BOOK-4',
          referenceBookId: 'BOOK-2',
          referenceBook2Id: 'BOOK-3',
          shelf1AnnotationId: 'ANN-SHELF-1',
          shelf2AnnotationId: 'ANN-SHELF-2',
          takeoutMode: 'standard',
          book1TakeoutMode: 'mid',
          book2TakeoutMode: 'standard',
          book1ReturnMode: 'end',
          book2ReturnMode: 'mid',
          book1LiftHeightMm: 610,
          book2LiftHeightMm: 620,
          referenceBook1LiftHeightMm: 630,
          referenceBook2LiftHeightMm: 640,
          moveSpeedMps: 0.08,
          enableVehicleAlignment: false,
        }),
      ),
    );
    first.unmount();

    render(
      <App>
        <QuickTakeReturnDemoPage />
      </App>,
    );
    await screen.findByText('机器人 1（LR-01）');
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: '架内取还书' })).toBeChecked(),
    );
    expect(screen.getByTitle('中位取书')).toBeInTheDocument();
    expect(screen.getByTitle('末尾还书')).toBeInTheDocument();
    expect(
      screen.getByRole('switch', { name: '车辆居中对齐服务' }),
    ).not.toBeChecked();
    const restoredHeights = screen.getAllByRole('spinbutton');
    expect(restoredHeights[0]).toHaveValue('610');
    expect(restoredHeights[1]).toHaveValue('620');
    expect(restoredHeights[2]).toHaveValue('630');
    expect(restoredHeights[3]).toHaveValue('640');
    expect(restoredHeights[4]).toHaveValue('0.08');
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: '开始架内取还书' }),
      ).toBeEnabled(),
    );
  });
});

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { App } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Book } from '@/services/libraryRobot/types';
import CompleteReturnPanel from '../return/CompleteReturnPanel';
import CompleteTakeoutPanel from '../takeout/CompleteTakeoutPanel';
import { loadReturnOptions, loadTakeoutOptions } from './workflowOptions';

const mocks = vi.hoisted(() => ({
  getMapAnnotations: vi.fn(),
  getMapVersions: vi.fn(),
  getRobots: vi.fn(),
  listBooks: vi.fn(),
  listLibrary: vi.fn(),
}));

vi.mock('@/services/libraryRobot', () => ({
  cancelCompleteReturn: vi.fn(),
  cancelCompleteTakeout: vi.fn(),
  createCompleteReturn: vi.fn(),
  createCompleteTakeout: vi.fn(),
  DEFAULT_BOOK_HEIGHT_MM: 550,
  getMapAnnotations: mocks.getMapAnnotations,
  getMapVersions: mocks.getMapVersions,
  getRobots: mocks.getRobots,
  listBooks: mocks.listBooks,
  pollTasks: vi.fn(),
}));

vi.mock('@/services/libraryRobot/studio', () => ({
  listLibrary: mocks.listLibrary,
}));

vi.mock('./MapPosePreview', () => ({
  default: () => null,
}));

const book = {
  id: 'BOOK-1',
  name: '测试书',
  templateId: 'TPL-1',
  heightMm: 800,
  annotationId: 'POINT-1',
  preferredSlot: 2,
  createdAt: '',
  updatedAt: '',
} satisfies Book;

beforeEach(() => {
  window.localStorage.clear();
  mocks.listBooks.mockResolvedValue([book]);
  mocks.getRobots.mockResolvedValue([
    { id: 'LR-01', name: '机器人 1', mapId: 'MAP-1', status: 'idle' },
  ]);
  mocks.getMapVersions.mockResolvedValue([{ id: 'MAP-1', name: '测试地图' }]);
  mocks.getMapAnnotations.mockResolvedValue([]);
  mocks.listLibrary.mockResolvedValue({ items: [{ id: 'TPL-1' }] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('快速取还书页面选项保存', () => {
  it('取书页面保存当前选项并在重新打开时恢复', async () => {
    const first = render(
      <App>
        <CompleteTakeoutPanel />
      </App>,
    );

    fireEvent.mouseDown(screen.getAllByRole('combobox')[0]);
    fireEvent.click(await screen.findByText('测试书（高度 800 mm）'));
    fireEvent.click(screen.getByRole('button', { name: /保存选项参数/ }));

    await waitFor(() => {
      expect(loadTakeoutOptions()).toEqual(
        expect.objectContaining({
          robotId: 'LR-01',
          bookId: 'BOOK-1',
          liftHeightMm: 800,
          destinationSlot: 2,
          takeoutMode: 'standard',
        }),
      );
    });
    first.unmount();

    render(
      <App>
        <CompleteTakeoutPanel />
      </App>,
    );
    expect(
      await screen.findByText('测试书（高度 800 mm）'),
    ).toBeInTheDocument();
  });

  it('还书页面保存当前选项并在重新打开时恢复', async () => {
    const first = render(
      <App>
        <CompleteReturnPanel />
      </App>,
    );

    fireEvent.mouseDown(screen.getAllByRole('combobox')[0]);
    fireEvent.click(await screen.findByText('测试书（高度 800 mm）'));
    fireEvent.click(screen.getByRole('button', { name: /保存选项参数/ }));

    await waitFor(() => {
      expect(loadReturnOptions()).toEqual(
        expect.objectContaining({
          robotId: 'LR-01',
          bookId: 'BOOK-1',
          liftHeightMm: 800,
          sourceSlot: 2,
          returnMode: 'mid',
        }),
      );
    });
    first.unmount();

    render(
      <App>
        <CompleteReturnPanel />
      </App>,
    );
    expect(
      await screen.findByText('测试书（高度 800 mm）'),
    ).toBeInTheDocument();
  });
});

import { DeleteOutlined, SaveOutlined } from '@ant-design/icons';
import {
  App,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';

import {
  editLibraryMap,
  getMapPreview,
  getMapVersions,
} from '@/services/libraryRobot';
import type { MapVersion } from '@/services/libraryRobot/types';
import {
  brushMapPoints,
  type MapEditPoint,
  mapPointFromClient,
} from './mapEditorUtils';

export default function MapEditor() {
  const { message } = App.useApp();
  const [maps, setMaps] = useState<MapVersion[]>([]);
  const [mapId, setMapId] = useState<string>();
  const [previewUrl, setPreviewUrl] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<0 | 100>(0);
  const [brushSize, setBrushSize] = useState(8);
  const [name, setName] = useState('');
  const [drawing, setDrawing] = useState(false);
  const [editCount, setEditCount] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pointsRef = useRef(new Map<string, MapEditPoint>());
  const previewRef = useRef<string | undefined>(undefined);

  function replacePreview(url?: string) {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    previewRef.current = url;
    setPreviewUrl(url);
  }

  function clearBrush() {
    pointsRef.current.clear();
    setEditCount(0);
    const canvas = canvasRef.current;
    canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
  }

  useEffect(() => {
    void getMapVersions()
      .then((versions) => {
        setMaps(versions);
        setMapId((current) => current ?? versions[0]?.id);
      })
      .catch((error) =>
        message.error(
          error instanceof Error ? error.message : '读取地图列表失败',
        ),
      );
  }, [message]);

  useEffect(() => {
    if (!mapId) {
      replacePreview(undefined);
      return;
    }
    let cancelled = false;
    setLoading(true);
    clearBrush();
    setName('');
    void getMapPreview(mapId)
      .then((url) => {
        if (!cancelled) replacePreview(url);
      })
      .catch((error) =>
        message.error(
          error instanceof Error ? error.message : '读取地图预览失败',
        ),
      )
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mapId, message]);

  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    },
    [],
  );

  function applyBrush(event: React.PointerEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas || saving) return;
    const point = mapPointFromClient(
      event.clientX,
      event.clientY,
      canvas.getBoundingClientRect(),
      canvas.width,
      canvas.height,
    );
    if (!point) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.fillStyle = mode === 100 ? '#000000' : '#ffffff';
    for (const edit of brushMapPoints(
      point.x,
      point.y,
      brushSize,
      canvas.width,
      canvas.height,
      mode,
    )) {
      pointsRef.current.set(`${edit.x},${edit.y}`, edit);
      context.fillRect(edit.x, canvas.height - 1 - edit.y, 1, 1);
    }
    setEditCount(pointsRef.current.size);
  }

  async function saveAsNewVersion() {
    if (!mapId || editCount === 0) return;
    setSaving(true);
    try {
      const created = await editLibraryMap(mapId, {
        name: name.trim() || undefined,
        points: [...pointsRef.current.values()],
      });
      setMaps((current) => [created, ...current]);
      setMapId(created.id);
      clearBrush();
      message.success(`已保存为新地图版本：${created.name}`);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : '保存编辑地图失败',
      );
    } finally {
      setSaving(false);
    }
  }

  const selectedMap = maps.find((item) => item.id === mapId);

  return (
    <Card title="地图处理" style={{ marginTop: 16 }}>
      <Space orientation="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap size={12}>
          <Select
            style={{ minWidth: 280 }}
            value={mapId}
            placeholder="选择已保存地图"
            onChange={setMapId}
            options={maps.map((item) => ({
              value: item.id,
              label: `${item.name}（${item.id}）`,
            }))}
          />
          <Select
            value={mode}
            style={{ minWidth: 140 }}
            onChange={setMode}
            options={[
              { value: 0, label: '擦除障碍物' },
              { value: 100, label: '新增障碍物' },
            ]}
          />
          <span>
            <Typography.Text type="secondary">笔刷：</Typography.Text>
            <InputNumber
              min={1}
              max={50}
              value={brushSize}
              onChange={(value) => setBrushSize(value ?? 8)}
            />
            <Typography.Text type="secondary"> 像素</Typography.Text>
          </span>
          <Input
            style={{ minWidth: 220 }}
            value={name}
            maxLength={120}
            placeholder={
              selectedMap ? `${selectedMap.name} 编辑` : '新地图名称'
            }
            onChange={(event) => setName(event.target.value)}
          />
          <Button
            icon={<DeleteOutlined />}
            disabled={editCount === 0 || saving}
            onClick={clearBrush}
          >
            清除画笔
          </Button>
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            disabled={!mapId || editCount === 0}
            onClick={() => void saveAsNewVersion()}
          >
            另存为新版本
          </Button>
        </Space>
        <Typography.Text type="secondary">
          在地图上按住并拖动涂抹；白色擦除为可通行区域，黑色新增为障碍物。原图保持不变，仅已保存地图可编辑。
        </Typography.Text>
        {loading ? <Spin /> : null}
        {!loading && previewUrl ? (
          <div style={{ position: 'relative', lineHeight: 0, maxWidth: 1000 }}>
            <img
              src={previewUrl}
              alt="待编辑地图"
              style={{ display: 'block', width: '100%' }}
              onLoad={(event) => {
                const canvas = canvasRef.current;
                if (!canvas) return;
                canvas.width = event.currentTarget.naturalWidth;
                canvas.height = event.currentTarget.naturalHeight;
                clearBrush();
              }}
            />
            <canvas
              ref={canvasRef}
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                cursor: 'crosshair',
                touchAction: 'none',
              }}
              onPointerDown={(event) => {
                event.preventDefault();
                event.currentTarget.setPointerCapture(event.pointerId);
                setDrawing(true);
                applyBrush(event);
              }}
              onPointerMove={(event) => {
                if (drawing) applyBrush(event);
              }}
              onPointerUp={() => setDrawing(false)}
              onPointerCancel={() => setDrawing(false)}
            />
          </div>
        ) : null}
        {!loading && !previewUrl ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="请选择一张已保存地图"
          />
        ) : null}
      </Space>
    </Card>
  );
}

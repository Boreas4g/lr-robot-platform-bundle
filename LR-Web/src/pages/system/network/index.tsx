import { LinkOutlined, ReloadOutlined, WifiOutlined } from '@ant-design/icons';
import { PageContainer } from '@ant-design/pro-components';
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  confirmWifi,
  connectWifi,
  getNetworkStatus,
  isNetworkPending,
  type NetworkConnect,
  type NetworkOperation,
  type NetworkStatus,
  networkRequestId,
  scanWifi,
  type WifiNetwork,
} from '@/services/libraryRobot/network';
import { useStyles } from './style';

const PENDING_KEY = 'lr-network-pending';
const securityName = {
  open: '开放网络',
  'wpa-psk': 'WPA / WPA2 个人',
  sae: 'WPA3 个人',
  unsupported: '企业认证 / 不支持',
};
const explain = (error: unknown) =>
  error instanceof Error ? error.message : '网络服务暂不可用';
type SwitchError = { title: string; description: string };
function readPending(): NetworkOperation | undefined {
  if (typeof window === 'undefined') return undefined;
  try {
    return (
      JSON.parse(sessionStorage.getItem(PENDING_KEY) || 'null') || undefined
    );
  } catch {
    return undefined;
  }
}
const networkUrl = (ip: string) => `http://${ip}:8000/system/network`;

export default function NetworkPage() {
  const { styles } = useStyles();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [status, setStatus] = useState<NetworkStatus>();
  const [selected, setSelected] = useState('');
  const [networks, setNetworks] = useState<WifiNetwork[]>([]);
  const [scanNote, setScanNote] = useState('');
  const [error, setError] = useState('');
  const [switchError, setSwitchError] = useState<SwitchError>();
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [open, setOpen] = useState(false);
  const [hotspot, setHotspot] = useState<{ uuid: string; ssid: string }>();
  const [operation, setOperation] = useState<NetworkOperation | undefined>(
    readPending,
  );
  const [now, setNow] = useState(Date.now());
  const refreshInFlight = useRef(false);
  const submitInFlight = useRef(false);
  const security = Form.useWatch('security', form);
  const pending = isNetworkPending(operation);
  const device = status?.devices.find((d) => d.interface === selected);

  const refresh = useCallback(async () => {
    if (refreshInFlight.current || submitInFlight.current) return;
    refreshInFlight.current = true;
    try {
      const value = await getNetworkStatus();
      setStatus(value);
      setSelected((current) =>
        value.devices.some((d) => d.interface === current)
          ? current
          : value.devices.find((d) => d.managed)?.interface || '',
      );
      if (!submitInFlight.current) setOperation(value.operation || undefined);
      setError('');
    } catch (e) {
      setError(explain(e));
    } finally {
      setLoading(false);
      refreshInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, 4000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (operation && isNetworkPending(operation))
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(operation));
    else sessionStorage.removeItem(PENDING_KEY);
  }, [operation]);

  const scan = useCallback(async (name: string, rescan: boolean) => {
    if (!name) return;
    setScanning(true);
    try {
      const result = await scanWifi(name, rescan);
      setNetworks(result.networks);
      setScanNote(result.message);
    } catch (e) {
      setScanNote(explain(e));
    } finally {
      setScanning(false);
    }
  }, []);
  useEffect(() => {
    setNetworks([]);
    void scan(selected, false);
  }, [selected, scan]);

  function choose(network?: WifiNetwork, ap?: { uuid: string; ssid: string }) {
    form.resetFields();
    form.setFieldsValue({
      ssid: network?.ssid || '',
      security: network?.security || 'wpa-psk',
      hidden: false,
      acknowledged: false,
    });
    setHotspot(ap);
    setOpen(true);
  }

  async function submit() {
    let values: {
      ssid: string;
      password?: string;
      security: 'open' | 'wpa-psk' | 'sae';
      hidden?: boolean;
      acknowledged: boolean;
    };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const request: NetworkConnect = {
      request_id: networkRequestId(),
      interface: selected,
      acknowledged: true,
      ...(hotspot
        ? { hotspot_uuid: hotspot.uuid }
        : {
            ssid: values.ssid,
            password: values.security === 'open' ? '' : values.password || '',
            security: values.security,
            hidden: Boolean(values.hidden),
          }),
    };
    setSubmitting(true);
    setSwitchError(undefined);
    submitInFlight.current = true;
    const provisional: NetworkOperation = {
      id: request.request_id,
      phase: 'unknown',
      interface: selected,
      ssid: hotspot?.ssid || values.ssid,
      message:
        '切换请求已发送。如果页面断开，请先按下面步骤连接目标网络，不要重复提交。',
      addresses: [],
      rollback_at: Date.now() / 1000 + (status?.rollback_seconds || 300) + 5,
      local_url: hotspot ? networkUrl('192.168.4.1') : status?.local_url || '',
    };
    // Store only handoff instructions, never the Wi-Fi password.
    setOperation(provisional);
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(provisional));
    try {
      const result = await connectWifi(request);
      setOperation({
        ...result,
        local_url: provisional.local_url || result.local_url,
      });
      setOpen(false);
      form.resetFields();
    } catch (e) {
      setOpen(false);
      form.resetFields();
      const detail = explain(e);
      if (detail.startsWith('机器人仍在执行作业')) {
        setOperation(undefined);
        sessionStorage.removeItem(PENDING_KEY);
        setSwitchError({
          title: '网络切换未受理',
          description: `${detail}。本次请求未提交，当前网络没有切换。`,
        });
      } else {
        setSwitchError({
          title: '网络切换结果待确认',
          description: `${detail}。服务未能确认请求是否已执行，请勿重复提交；如果页面刚断开，请连接目标 Wi-Fi 后点击“进入新网址”查看状态。`,
        });
      }
    } finally {
      setSubmitting(false);
      submitInFlight.current = false;
    }
  }

  async function confirm() {
    if (!operation) return;
    setConfirming(true);
    try {
      const result = await confirmWifi(operation.id);
      setOperation(result);
      if (result.phase === 'confirmed') message.success('网络连接已保存');
      else message.warning(result.message);
      void refresh();
    } catch (e) {
      message.error(explain(e));
    } finally {
      setConfirming(false);
    }
  }

  const seconds = Math.max(
    0,
    Math.ceil((operation?.rollback_at || 0) - now / 1000),
  );
  const urls = device?.addresses.map((ip) => `http://${ip}:8000`) || [];
  const handoffUrl = operation?.addresses[0]
    ? networkUrl(operation.addresses[0])
    : operation?.local_url || '';
  return (
    <PageContainer
      title="网络连接"
      content="把机器人接入图书馆 Wi-Fi，让手机、平板和电脑通过同一局域网继续控制。"
    >
      <div className={styles.page}>
        {error && (
          <Alert
            type={pending ? 'warning' : 'error'}
            showIcon
            title={pending ? '连接正在交接' : '无法读取网络状态'}
            description={error}
            action={<Button onClick={() => void refresh()}>刷新状态</Button>}
          />
        )}
        {switchError && (
          <Alert
            type="warning"
            showIcon
            title={switchError.title}
            description={switchError.description}
            action={<Button onClick={() => setSwitchError(undefined)}>知道了</Button>}
          />
        )}
        {operation && (
          <Card
            title={pending ? '连接交接' : '最近一次切换'}
            extra={
              pending ? (
                <Tag color="processing">
                  {seconds > 0 ? `${seconds} 秒内确认` : '等待恢复结果'}
                </Tag>
              ) : undefined
            }
          >
            <div className={styles.stacked}>
              <Alert
                showIcon
                type={
                  operation.phase === 'confirmed'
                    ? 'success'
                    : operation.phase === 'recovery_required'
                      ? 'error'
                      : 'info'
                }
                title={operation.message}
              />
              {pending && (
                <>
                  <ol className={styles.steps}>
                    <li>
                      在当前手机或电脑的 Wi-Fi 设置中连接{' '}
                      <strong>{operation.ssid}</strong>，然后返回浏览器。
                    </li>
                    <li>
                      打开下面的入口，使用原网站账号重新登录，进入“系统 →
                      网络连接”。不同地址需要重新登录。
                    </li>
                    <li>
                      点击“确认保留此连接”。切换开始后约 5
                      分钟仍未确认时，机器人恢复原网络，请重新连接原热点或
                      Wi-Fi。
                    </li>
                  </ol>
                  {operation.local_url && (
                    <Typography.Paragraph
                      className={styles.address}
                      copyable={{ text: operation.local_url }}
                    >
                      <a href={operation.local_url}>{operation.local_url}</a>
                    </Typography.Paragraph>
                  )}
                  {operation.addresses.map((ip) => (
                    <Typography.Paragraph
                      key={ip}
                      className={styles.address}
                      copyable={{ text: networkUrl(ip) }}
                    >
                      <a href={networkUrl(ip)}>{networkUrl(ip)}</a>
                    </Typography.Paragraph>
                  ))}
                  {handoffUrl && (
                    <Button
                      type="primary"
                      icon={<LinkOutlined />}
                      href={handoffUrl}
                      target="_self"
                    >
                      进入新网址
                    </Button>
                  )}
                  <Typography.Text type="secondary">
                    若 .local 名称打不开，请在路由器客户端列表查找车载电脑的新
                    IP，并访问
                    http://新IP:8000；不需要互联网，但路由器必须允许设备互访。
                  </Typography.Text>
                  <Button
                    type="primary"
                    onClick={() => void confirm()}
                    loading={confirming}
                    disabled={operation.phase !== 'awaiting_confirmation'}
                  >
                    确认保留此连接
                  </Button>
                </>
              )}
            </div>
          </Card>
        )}
        <div className={styles.columns}>
          <Card
            title={
              <>
                <WifiOutlined /> 可用 Wi-Fi
              </>
            }
            extra={
              <Button
                icon={<ReloadOutlined />}
                loading={scanning}
                disabled={!selected || pending || submitting}
                onClick={() => void scan(selected, true)}
              >
                刷新
              </Button>
            }
          >
            <div className={styles.toolbar}>
              <Select
                aria-label="无线网卡"
                value={selected || undefined}
                placeholder="选择无线网卡"
                disabled={pending || submitting}
                onChange={setSelected}
                options={status?.devices.map((d) => ({
                  value: d.interface,
                  label: d.interface + (d.mode === 'ap' ? ' · 机器人热点' : ''),
                  disabled: !d.managed,
                }))}
              />
              <Button
                disabled={!device?.managed || pending || submitting}
                onClick={() => choose()}
              >
                手动添加网络
              </Button>
            </div>
            {scanNote && <Alert type="info" title={scanNote} showIcon />}
            {status &&
              (!status.wireless_enabled || !status.hardware_enabled) && (
                <Alert
                  type="warning"
                  title="无线网卡已关闭，请联系现场管理员开启。"
                  showIcon
                />
              )}
            <Spin spinning={loading || scanning}>
              {!networks.length && (
                <Empty
                  description={
                    loading
                      ? '正在读取网络'
                      : '暂无网络，刷新列表或手动添加 Wi-Fi'
                  }
                />
              )}
              {networks.map((n) => (
                <div className={styles.row} key={`${n.ssid}-${n.security}`}>
                  <div className={styles.identity}>
                    <span className={styles.icon}>
                      <WifiOutlined />
                    </span>
                    <div className={styles.details}>
                      <div className={styles.name}>
                        {n.ssid}{' '}
                        {device?.mode === 'infrastructure' &&
                          device.ssid === n.ssid && (
                            <Tag color="success">已连接</Tag>
                          )}
                      </div>
                      <div className={styles.meta}>
                        信号 {n.signal}% · {securityName[n.security]} ·{' '}
                        {n.frequency >= 5000 ? '5 GHz' : '2.4 GHz'}
                      </div>
                    </div>
                  </div>
                  <Button
                    disabled={
                      pending ||
                      submitting ||
                      n.security === 'unsupported' ||
                      !status?.wireless_enabled ||
                      !status?.hardware_enabled
                    }
                    onClick={() => choose(n)}
                  >
                    连接
                  </Button>
                </div>
              ))}
            </Spin>
          </Card>
          <div className={styles.stacked}>
            <Card
              title={
                <>
                  <LinkOutlined /> 当前连接
                </>
              }
            >
              <div className={styles.stacked}>
                <div>
                  <Typography.Text type="secondary">连接方式</Typography.Text>
                  <div className={styles.name}>
                    {device?.mode === 'ap'
                      ? '机器人热点'
                      : device?.ssid || '尚未连接'}{' '}
                    {device && <Tag>{device.interface}</Tag>}
                  </div>
                </div>
                {urls.map((url) => (
                  <Typography.Paragraph
                    key={url}
                    copyable={{ text: url }}
                    className={styles.address}
                  >
                    {url}
                  </Typography.Paragraph>
                ))}
                {status?.local_url && (
                  <div>
                    <Typography.Text type="secondary">
                      切换后可尝试的名称入口
                    </Typography.Text>
                    <Typography.Paragraph copyable className={styles.address}>
                      {status.local_url}
                    </Typography.Paragraph>
                  </div>
                )}
                {device?.hotspots.map((ap) => (
                  <Button
                    key={ap.uuid}
                    disabled={pending || submitting || device.mode === 'ap'}
                    onClick={() => choose(undefined, ap)}
                  >
                    切回机器人热点
                  </Button>
                ))}
              </div>
            </Card>
            <Card title="切换前须知">
              <ol className={styles.steps}>
                <li>结束取还书、导航和建图，确认机器人停止。</li>
                <li>
                  单无线网卡切换后，原热点会暂时消失；手机或电脑也需要连接目标
                  Wi-Fi。
                </li>
                <li>
                  确认成功后保存网络并优先自动连接。热点 IP 保留为
                  192.168.4.1，局域网地址由路由器分配。
                </li>
                <li>
                  支持开放网络及 WPA/WPA2/WPA3
                  个人网络。企业账号认证、网页认证和访客隔离网络请联系网络管理员。
                </li>
              </ol>
            </Card>
          </div>
        </div>
        <Modal
          title={hotspot ? '切回机器人热点' : '连接 Wi-Fi'}
          open={open}
          onCancel={() => {
            if (!submitting) {
              setOpen(false);
              form.resetFields();
            }
          }}
          onOk={() => void submit()}
          confirmLoading={submitting}
          okText="确认并切换"
          cancelText="取消"
          closable={!submitting}
          mask={{ closable: !submitting }}
          destroyOnHidden
          width={520}
        >
          <Form form={form} layout="vertical" preserve={false}>
            {hotspot ? (
              <Alert
                type="info"
                showIcon
                title={`连接 ${hotspot.ssid} 后访问 http://192.168.4.1:8000`}
              />
            ) : (
              <>
                <Form.Item
                  label="Wi-Fi 名称"
                  name="ssid"
                  rules={[
                    { required: true, message: '请输入 Wi-Fi 名称' },
                    {
                      validator: (_, value) =>
                        !value || new TextEncoder().encode(value).length <= 32
                          ? Promise.resolve()
                          : Promise.reject(new Error('名称不能超过 32 字节')),
                    },
                  ]}
                >
                  <Input autoComplete="off" maxLength={32} />
                </Form.Item>
                <Form.Item
                  label="安全类型"
                  name="security"
                  rules={[{ required: true }]}
                >
                  <Select
                    options={Object.entries(securityName)
                      .filter(([key]) => key !== 'unsupported')
                      .map(([value, label]) => ({ value, label }))}
                  />
                </Form.Item>
                {security !== 'open' && (
                  <Form.Item
                    label="Wi-Fi 密码"
                    name="password"
                    rules={[
                      { required: true, message: '请输入目标 Wi-Fi 的密码' },
                    ]}
                  >
                    <Input.Password
                      autoComplete="new-password"
                      maxLength={64}
                    />
                  </Form.Item>
                )}
                <Form.Item name="hidden" valuePropName="checked">
                  <Checkbox>这是隐藏网络</Checkbox>
                </Form.Item>
              </>
            )}
            <Alert
              type="warning"
              showIcon
              title="切换将暂时中断当前网页连接"
              description="请先记下名称入口或准备从路由器查询新 IP。切换后连接同一 Wi-Fi，重新登录并在切换开始后约 5 分钟内确认，否则恢复原网络。"
            />
            {status?.local_url && !hotspot && (
              <Typography.Paragraph copyable className={styles.address}>
                {status.local_url}
              </Typography.Paragraph>
            )}
            <Form.Item
              name="acknowledged"
              valuePropName="checked"
              rules={[
                {
                  validator: (_, value) =>
                    value
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error(
                            '请先确认机器人已停止，并已了解重新连接步骤',
                          ),
                        ),
                },
              ]}
              style={{ marginTop: 16 }}
            >
              <Checkbox>机器人已停止，我已了解重新连接和超时恢复步骤</Checkbox>
            </Form.Item>
          </Form>
        </Modal>
      </div>
    </PageContainer>
  );
}

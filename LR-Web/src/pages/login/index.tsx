import { LockOutlined, RobotOutlined, UserOutlined, WifiOutlined } from '@ant-design/icons';
import { history, useModel } from '@umijs/max';
import { Alert, Button, Form, Input } from 'antd';
import { useState } from 'react';
import { signIn } from '@/services/auth';
import './index.less';

export default function LoginPage() {
  const { setInitialState } = useModel('@@initialState');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();

  async function login(values: { username: string; password: string }) {
    setLoading(true);
    setError(undefined);
    try {
      const currentUser = await signIn(values.username.trim(), values.password);
      await setInitialState((state) => ({ ...state!, currentUser }));
      const redirect = new URLSearchParams(window.location.search).get('redirect');
      const destination = redirect?.startsWith('/') && !redirect.startsWith('//') && !redirect.startsWith('/login')
        ? redirect : '/overview/dashboard';
      history.replace(destination);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '暂时无法登录，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="robot-login">
      <div className="robot-login-shell">
        <section className="robot-login-intro" aria-label="图书馆机器人">
          <div className="robot-login-brand"><span className="robot-login-mark"><RobotOutlined /></span><span>智巡 · 图书馆机器人</span></div>
          <div className="robot-login-story">
            <span className="robot-login-eyebrow">LIBRARY ROBOT</span>
            <h1>让每一本书，<br />抵达它的位置。</h1>
            <p>连接身边的机器人，让取还书、地图导航与日常管理更从容。</p>
            <div className="robot-login-illustration" aria-hidden="true">
              <div className="robot-login-orbit" />
              <div className="robot-login-shelf"><i /><i /><i /><i /><i /></div>
              <div className="robot-login-robot"><RobotOutlined /><span /><b /><b /></div>
              <div className="robot-login-dot" />
            </div>
          </div>
          <div className="robot-login-connection"><WifiOutlined /> 连接机器人所在网络，即可在本地使用</div>
        </section>
        <section className="robot-login-panel">
          <div className="robot-login-form">
            <div className="robot-login-welcome">欢迎使用</div>
            <h2>登录机器人控制台</h2>
            <p className="robot-login-description">使用您的账号，开始今天的图书馆作业。</p>
            {error && <Alert className="robot-login-error" title={error} type="error" showIcon role="alert" />}
            <Form layout="vertical" requiredMark={false} onFinish={login} size="large">
              <Form.Item name="username" label="账号" rules={[{ required: true, whitespace: true, message: '请输入账号' }]}>
                <Input prefix={<UserOutlined />} placeholder="请输入登录账号" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
                <Input.Password prefix={<LockOutlined />} placeholder="请输入登录密码" autoComplete="current-password" />
              </Form.Item>
              <Button block type="primary" htmlType="submit" loading={loading}>登录控制台</Button>
            </Form>
            <div className="robot-login-features"><span>作业管理</span><span>地图与导航</span><span>系统管理</span></div>
            <p className="robot-login-help">账号由管理员提供。支持手机与电脑访问。</p>
          </div>
          <footer>智巡 · 让图书馆服务触手可及</footer>
        </section>
      </div>
    </main>
  );
}

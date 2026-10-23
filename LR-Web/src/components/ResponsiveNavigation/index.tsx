import { MenuOutlined, RobotOutlined } from '@ant-design/icons';
import type { MenuDataItem } from '@ant-design/pro-components';
import { Link, useLocation } from '@umijs/max';
import type { MenuProps } from 'antd';
import { Button, Drawer, Grid, Menu } from 'antd';
import type { ReactNode } from 'react';
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';

type Props = {
  menuData?: MenuDataItem[];
  actions: ReactNode;
  canDebug: boolean;
};

// Consume the framework's route menu so navigation and route permissions stay aligned.
function visibleMenu(items: MenuDataItem[], canDebug: boolean): MenuDataItem[] {
  return items.flatMap((item) => {
    if (
      !item.name ||
      item.hideInMenu ||
      item.unaccessible ||
      (!canDebug && item.key === 'debug')
    )
      return [];
    const children = item.children
      ? visibleMenu(item.children, canDebug)
      : undefined;
    if (item.children && !children?.length) return [];
    return [{ ...item, children }];
  });
}

function menuItems(
  items: MenuDataItem[],
  onNavigate: () => void,
): MenuProps['items'] {
  return items.map((item) => ({
    key: item.children?.length
      ? (item.key ?? item.path ?? item.name ?? '')
      : (item.path ?? item.key ?? item.name ?? ''),
    icon: item.icon,
    disabled: item.disabled,
    label:
      item.children?.length || !item.path ? (
        item.name
      ) : (
        <Link to={item.path} onClick={onNavigate}>
          {item.name}
        </Link>
      ),
    children: item.children?.length
      ? menuItems(item.children, onNavigate)
      : undefined,
  }));
}

export default function ResponsiveNavigation({
  menuData = [],
  actions,
  canDebug,
}: Props) {
  const { pathname } = useLocation();
  const screens = Grid.useBreakpoint();
  const [open, setOpen] = useState(false);
  const [openKeys, setOpenKeys] = useState<string[]>([]);
  const items = useMemo(
    () => visibleMenu(menuData, canDebug),
    [menuData, canDebug],
  );
  const close = () => setOpen(false);

  useEffect(() => {
    setOpen(false);
    const currentGroup = items.find((item) =>
      item.children?.some((child) => child.path === pathname),
    );
    if (currentGroup) {
      const key =
        currentGroup.key ?? currentGroup.path ?? currentGroup.name ?? '';
      setOpenKeys((keys) => (keys.includes(key) ? keys : [...keys, key]));
    }
  }, [pathname, items]);

  useEffect(() => {
    if (screens.lg) setOpen(false);
  }, [screens.lg]);

  const navigation = (mobile: boolean) => (
    <nav aria-label={mobile ? '移动端页面导航' : '页面导航'}>
      <Menu
        mode="inline"
        selectedKeys={[pathname]}
        openKeys={openKeys}
        onOpenChange={setOpenKeys}
        items={menuItems(items, close)}
        inlineIndent={16}
      />
    </nav>
  );

  return (
    <>
      <div className="robot-app-header">
        <Button
          className="robot-nav-toggle"
          type="text"
          icon={<MenuOutlined />}
          aria-label="打开导航菜单"
          aria-expanded={open}
          aria-controls="robot-mobile-navigation"
          onClick={() => setOpen(true)}
        />
        <Link
          className="robot-app-brand"
          to="/overview/dashboard"
          aria-label="图书馆机器人首页"
        >
          <span className="robot-app-mark">
            <RobotOutlined />
          </span>
          <span className="robot-app-brand-text">
            图书馆机器人<small>智巡 · 控制台</small>
          </span>
        </Link>
        <div className="robot-app-actions">{actions}</div>
      </div>
      {screens.lg && typeof document !== 'undefined'
        ? createPortal(
            <aside className="robot-desktop-navigation">
              <div className="robot-navigation-caption">
                工作空间<span>WORKSPACE</span>
              </div>
              <div className="robot-navigation-scroll">{navigation(false)}</div>
              <div className="robot-navigation-footer">
                <RobotOutlined /> 智巡 · 图书馆机器人
              </div>
            </aside>,
            document.body,
          )
        : null}
      <Drawer
        rootClassName="robot-navigation-drawer"
        title={
          <div className="robot-navigation-title">
            <span className="robot-app-mark">
              <RobotOutlined />
            </span>
            <div>
              图书馆机器人<small>选择页面，开始操作</small>
            </div>
          </div>
        }
        placement="left"
        size="min(336px, calc(100vw - 32px))"
        open={open && !screens.lg}
        onClose={close}
        closable={{ placement: 'end', 'aria-label': '关闭导航菜单' }}
        closeIcon={<span aria-hidden="true">×</span>}
        destroyOnHidden
        footer={
          <div className="robot-navigation-footer">
            智巡 · 图书馆机器人控制台
          </div>
        }
      >
        <div id="robot-mobile-navigation">{navigation(true)}</div>
      </Drawer>
    </>
  );
}

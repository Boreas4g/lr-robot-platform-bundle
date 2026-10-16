"""A restrained Tkinter desktop control console for YZ-AIM drives."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, TypeVar

from ..lift_platform import LiftPlatform
from ..models import DriveStatus
from .session import ConnectionSettings, DriveSession


T = TypeVar("T")


PALETTE = {
    "navy": "#142033",
    "navy_active": "#20324b",
    "canvas": "#f3f6fa",
    "surface": "#ffffff",
    "text": "#152235",
    "muted": "#66758a",
    "border": "#dfe6ee",
    "primary": "#2864dc",
    "primary_dark": "#174ebd",
    "danger": "#c73546",
    "danger_dark": "#a62535",
    "success": "#14845f",
    "warning": "#a66b00",
    "input": "#f9fbfd",
}

# Noto Sans CJK is installed by default on the supported Linux images and
# renders Chinese and Latin UI text consistently.
FONT_FAMILY = "Noto Sans CJK SC"
MONOSPACE_FONT_FAMILY = "Noto Sans Mono CJK SC"


def _parse_int(value: str, label: str) -> int:
    try:
        return int(value.strip(), 0)
    except ValueError as error:
        raise ValueError(f"{label}必须是整数，可使用 0x 前缀输入十六进制") from error


def _parse_float(value: str, label: str) -> float:
    try:
        return float(value.strip())
    except ValueError as error:
        raise ValueError(f"{label}必须是数字") from error


def list_serial_ports() -> list[str]:
    """Return available serial port names without requiring a live drive."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [port.device for port in list_ports.comports()]


class ScrollablePage(ttk.Frame):
    """A mouse-wheel scrollable page that keeps controls visible on small screens."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="Canvas.TFrame")
        self.canvas = tk.Canvas(self, background=PALETTE["canvas"], highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, style="Canvas.TFrame", padding=(28, 26, 28, 28))
        self.window_id = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.body.bind("<Configure>", self._update_region)
        self.canvas.bind("<Configure>", self._fit_width)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    def _update_region(self, _: object) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_width(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_wheel(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class StatusCard(tk.Frame):
    """Compact live-value surface used on the connection and control pages."""

    def __init__(self, parent: tk.Misc, label: str, value: str = "--", unit: str = "") -> None:
        super().__init__(parent, background=PALETTE["surface"], highlightbackground=PALETTE["border"], highlightthickness=1)
        self.columnconfigure(0, weight=1)
        tk.Label(
            self,
            text=label,
            background=PALETTE["surface"],
            foreground=PALETTE["muted"],
            font=(FONT_FAMILY, 9),
            anchor="w",
        ).grid(row=0, column=0, padx=16, pady=(13, 3), sticky="ew")
        self.value = tk.Label(
            self,
            text=value,
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            font=(FONT_FAMILY, 16, "bold"),
            anchor="w",
        )
        self.value.grid(row=1, column=0, padx=16, pady=(0, 2), sticky="ew")
        self.unit = tk.Label(
            self,
            text=unit,
            background=PALETTE["surface"],
            foreground=PALETTE["muted"],
            font=(FONT_FAMILY, 9),
            anchor="w",
        )
        self.unit.grid(row=2, column=0, padx=16, pady=(0, 13), sticky="ew")

    def set(self, value: str, unit: str | None = None, *, color: str | None = None) -> None:
        self.value.configure(text=value)
        if unit is not None:
            self.unit.configure(text=unit)
        if color is not None:
            self.value.configure(foreground=color)


class MotorControlApp(tk.Tk):
    """Main AIM desktop control console."""

    def __init__(self, session: DriveSession | None = None) -> None:
        super().__init__()
        self.session = session or DriveSession()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aim-serial")
        self._busy = False
        self._current_page = "connection"
        self._poll_job: str | None = None
        self.title("AIM 伺服控制台")
        self.geometry("1180x780")
        self.minsize(1020, 680)
        self.configure(background=PALETTE["canvas"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_style()
        self._build_shell()
        self._show_page("connection")
        self.after(160, self.refresh_ports)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", (FONT_FAMILY, 10))
        style.configure("App.TFrame", background=PALETTE["canvas"])
        style.configure("Canvas.TFrame", background=PALETTE["canvas"])
        style.configure("Panel.TLabelframe", background=PALETTE["surface"], bordercolor=PALETTE["border"], relief="solid")
        style.configure("Panel.TLabelframe.Label", background=PALETTE["surface"], foreground=PALETTE["text"], font=(FONT_FAMILY, 10, "bold"))
        style.configure("Panel.TFrame", background=PALETTE["surface"])
        style.configure("TLabel", background=PALETTE["canvas"], foreground=PALETTE["text"], font=(FONT_FAMILY, 9))
        style.configure("Muted.TLabel", background=PALETTE["canvas"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 9))
        style.configure("Panel.TLabel", background=PALETTE["surface"], foreground=PALETTE["text"], font=(FONT_FAMILY, 9))
        style.configure("PanelMuted.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 9))
        style.configure("Title.TLabel", background=PALETTE["canvas"], foreground=PALETTE["text"], font=(FONT_FAMILY, 20, "bold"))
        style.configure("Subtitle.TLabel", background=PALETTE["canvas"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 10))
        style.configure("TEntry", fieldbackground=PALETTE["input"], bordercolor=PALETTE["border"], padding=7, font=(FONT_FAMILY, 10))
        style.configure("TCombobox", fieldbackground=PALETTE["input"], background=PALETTE["input"], padding=6, font=(FONT_FAMILY, 10))
        style.configure("TSpinbox", fieldbackground=PALETTE["input"], bordercolor=PALETTE["border"], padding=6, font=(FONT_FAMILY, 10))
        style.configure("TCheckbutton", background=PALETTE["surface"], foreground=PALETTE["text"], font=(FONT_FAMILY, 9))
        style.configure("TRadiobutton", background=PALETTE["surface"], foreground=PALETTE["text"], font=(FONT_FAMILY, 9))
        style.configure("Primary.TButton", background=PALETTE["primary"], foreground="#ffffff", padding=(13, 8), font=(FONT_FAMILY, 9, "bold"), borderwidth=0)
        style.map("Primary.TButton", background=[("active", PALETTE["primary_dark"]), ("disabled", "#9ab5ea")])
        style.configure("Secondary.TButton", background=PALETTE["surface"], foreground=PALETTE["text"], padding=(12, 8), font=(FONT_FAMILY, 9), bordercolor=PALETTE["border"])
        style.map("Secondary.TButton", background=[("active", "#edf2f8")])
        style.configure("Danger.TButton", background=PALETTE["danger"], foreground="#ffffff", padding=(13, 8), font=(FONT_FAMILY, 9, "bold"), borderwidth=0)
        style.map("Danger.TButton", background=[("active", PALETTE["danger_dark"]), ("disabled", "#e3a5ad")])

    def _build_shell(self) -> None:
        shell = ttk.Frame(self, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, width=218, background=PALETTE["navy"])
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="AIM", background=PALETTE["navy"], foreground="#ffffff", font=(FONT_FAMILY, 22, "bold")).pack(anchor="w", padx=24, pady=(28, 0))
        tk.Label(sidebar, text="SERVO CONTROL CONSOLE", background=PALETTE["navy"], foreground="#b7c5d7", font=(FONT_FAMILY, 8)).pack(anchor="w", padx=25, pady=(0, 30))
        self.nav_buttons: dict[str, tk.Button] = {}
        self._nav_button(sidebar, "connection", "连接与使能", "配置串口并管理伺服输出")
        self._nav_button(sidebar, "modbus", "Modbus RTU 控制", "定位、监控与寄存器调试")
        self._nav_button(sidebar, "lift", "升降台调试", "按厘米高度进行绝对定位")
        tk.Frame(sidebar, height=1, background="#31435a").pack(fill="x", padx=20, pady=(28, 18))
        tk.Label(sidebar, text="安全提醒", background=PALETTE["navy"], foreground="#d7e3f1", font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", padx=24)
        tk.Label(
            sidebar,
            text="串口连接不代表电机已使能。\n先确认机械安全，再启用输出。",
            background=PALETTE["navy"], foreground="#afbdcf", font=(FONT_FAMILY, 9), justify="left", wraplength=166,
        ).pack(anchor="w", padx=24, pady=(8, 0))
        main = ttk.Frame(shell, style="App.TFrame")
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, background=PALETTE["surface"], height=72, highlightbackground=PALETTE["border"], highlightthickness=1)
        header.pack(fill="x")
        header.pack_propagate(False)
        self.header_title = tk.Label(header, text="连接与使能", background=PALETTE["surface"], foreground=PALETTE["text"], font=(FONT_FAMILY, 16, "bold"))
        self.header_title.pack(side="left", padx=28, pady=20)
        self.connection_badge = tk.Label(header, text="未连接", background="#eef2f6", foreground=PALETTE["muted"], font=(FONT_FAMILY, 9, "bold"), padx=12, pady=6)
        self.connection_badge.pack(side="right", padx=26, pady=18)
        self.page_container = ttk.Frame(main, style="App.TFrame")
        self.page_container.pack(fill="both", expand=True)
        self.pages = {
            "connection": ConnectionPage(self.page_container, self),
            "modbus": ModbusControlPage(self.page_container, self),
            "lift": LiftPlatformPage(self.page_container, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self.page_container.rowconfigure(0, weight=1)
        self.page_container.columnconfigure(0, weight=1)

    def _nav_button(self, parent: tk.Misc, page: str, title: str, subtitle: str) -> None:
        button = tk.Button(
            parent, text=f"{title}\n{subtitle}", compound="left", anchor="w", justify="left", relief="flat", borderwidth=0,
            background=PALETTE["navy"], activebackground=PALETTE["navy_active"], foreground="#eef4fb", activeforeground="#ffffff",
            font=(FONT_FAMILY, 10, "bold"), padx=24, pady=13, command=lambda: self._show_page(page),
        )
        button.pack(fill="x", padx=12, pady=3)
        self.nav_buttons[page] = button

    def _show_page(self, page: str) -> None:
        self._current_page = page
        self.pages[page].tkraise()
        titles = {
            "connection": "连接与使能",
            "modbus": "RS485 Modbus RTU 通讯控制",
            "lift": "升降台厘米定位调试",
        }
        self.header_title.configure(text=titles[page])
        for key, button in self.nav_buttons.items():
            button.configure(background=PALETTE["navy_active"] if key == page else PALETTE["navy"])
        if page in ("modbus", "lift") and self.session.connected:
            self.refresh_status()

    def run_action(
        self,
        label: str,
        operation: Callable[[], T],
        on_success: Callable[[T], None] | None = None,
        *,
        quiet: bool = False,
    ) -> None:
        """Run serial work off the Tk thread and marshal result handling back."""
        if self._busy:
            if not quiet:
                self._set_message("正在执行上一条通讯操作，请稍候。", error=True)
            return
        self._busy = True
        self._set_message(f"正在{label}…")
        future = self.executor.submit(operation)
        future.add_done_callback(lambda done: self.after(0, self._finish_action, label, done, on_success, quiet))

    def _finish_action(
        self,
        label: str,
        future: Future[T],
        on_success: Callable[[T], None] | None,
        quiet: bool,
    ) -> None:
        self._busy = False
        try:
            result = future.result()
        except Exception as error:
            self._set_message(f"{label}失败：{error}", error=True)
            if not quiet:
                messagebox.showerror("通讯操作失败", f"{label}失败\n\n{error}")
            return
        self._set_message(f"{label}完成", error=False)
        if on_success is not None:
            on_success(result)

    def _set_message(self, message: str, *, error: bool = False) -> None:
        color = PALETTE["danger"] if error else PALETTE["muted"]
        for page in self.pages.values():
            page.message.configure(text=message, foreground=color)

    def refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.pages["connection"].set_ports(ports)
        self._set_message("已刷新串口列表" if ports else "未检测到串口，可手动输入串口名称")

    def set_connection_state(self, connected: bool, detail: str = "") -> None:
        if connected:
            settings = self.session.settings
            text = f"已连接 · {settings.port} · 地址 {settings.address}" if settings else "已连接"
            self.connection_badge.configure(text=text, background="#e4f4ed", foreground=PALETTE["success"])
        else:
            self.connection_badge.configure(text="未连接", background="#eef2f6", foreground=PALETTE["muted"])
        self.pages["connection"].set_connection_state(connected, detail)
        self.pages["modbus"].set_connection_state(connected)
        self.pages["lift"].set_connection_state(connected)

    def refresh_status(self, *, quiet: bool = False) -> None:
        if not self.session.connected:
            return
        self.run_action("读取状态", lambda: self.session.call(lambda drive: drive.read_status()), self._apply_status, quiet=quiet)

    def _apply_status(self, status: DriveStatus) -> None:
        self.pages["connection"].apply_status(status)
        self.pages["modbus"].apply_status(status)
        self.pages["lift"].apply_status(status)

    def start_polling(self) -> None:
        if self._poll_job is None:
            self._poll_tick()

    def stop_polling(self) -> None:
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None

    def _poll_tick(self) -> None:
        control = self.pages["modbus"]
        if self.session.connected and control.auto_refresh.get() and not self._busy:
            self.refresh_status(quiet=True)
        interval_ms = max(200, int(control.poll_interval.get() * 1000))
        self._poll_job = self.after(interval_ms, self._poll_tick)

    def _on_close(self) -> None:
        self.stop_polling()
        def finish() -> None:
            try:
                self.session.disconnect(disable_output=True)
            except Exception:
                pass
        future = self.executor.submit(finish)
        try:
            future.result(timeout=1.0)
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


class ConnectionPage(ScrollablePage):
    """Serial connection and explicit Modbus/output enable operations."""

    def __init__(self, parent: tk.Misc, app: MotorControlApp) -> None:
        super().__init__(parent)
        self.app = app
        self.port = tk.StringVar(value="/dev/lift_port")
        self.baudrate = tk.StringVar(value="19200")
        self.address = tk.StringVar(value="1")
        self.timeout = tk.StringVar(value="0.20")
        self.retries = tk.StringVar(value="1")
        self.output_state = tk.StringVar(value="输出未使能")
        self.modbus_state = tk.StringVar(value="通讯控制未使能")
        self._build()

    def _build(self) -> None:
        body = self.body
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        ttk.Label(body, text="建立安全、可追溯的串口连接", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="连接成功后仍需单独启用 Modbus 控制和伺服输出。", style="Subtitle.TLabel").grid(row=1, column=0, columnspan=2, pady=(4, 22), sticky="w")
        connect = ttk.LabelFrame(body, text="串口连接", style="Panel.TLabelframe", padding=18)
        connect.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        connect.columnconfigure(1, weight=1)
        self._field(connect, 0, "串口", ttk.Combobox(connect, textvariable=self.port, state="normal", width=19))
        self.port_box = connect.grid_slaves(row=0, column=1)[0]
        refresh = ttk.Button(connect, text="刷新串口", style="Secondary.TButton", command=self.app.refresh_ports)
        refresh.grid(row=0, column=2, padx=(8, 0), pady=7)
        self._field(connect, 1, "波特率", ttk.Combobox(connect, textvariable=self.baudrate, values=("9600", "19200", "38400", "115200"), state="readonly", width=19))
        self._field(connect, 2, "设备地址", ttk.Entry(connect, textvariable=self.address, width=22))
        self._field(connect, 3, "超时（秒）", ttk.Entry(connect, textvariable=self.timeout, width=22))
        self._field(connect, 4, "失败重试次数", ttk.Entry(connect, textvariable=self.retries, width=22))
        actions = ttk.Frame(connect, style="Panel.TFrame")
        actions.grid(row=5, column=0, columnspan=3, sticky="w", pady=(14, 0))
        ttk.Button(actions, text="连接串口", style="Primary.TButton", command=self.connect).pack(side="left")
        ttk.Button(actions, text="断开并失能", style="Danger.TButton", command=self.disconnect).pack(side="left", padx=(8, 0))
        output = ttk.LabelFrame(body, text="使能与失能", style="Panel.TLabelframe", padding=18)
        output.grid(row=2, column=1, sticky="nsew")
        ttk.Label(output, text="建议顺序", style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Label(output, text="连接串口 → 启用通讯控制 → 启用伺服输出", style="Panel.TLabel", wraplength=280).pack(anchor="w", pady=(3, 15))
        self.modbus_label = tk.Label(output, textvariable=self.modbus_state, background=PALETTE["surface"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 10, "bold"), anchor="w")
        self.modbus_label.pack(fill="x", pady=(0, 7))
        ttk.Button(output, text="启用 Modbus 控制", style="Secondary.TButton", command=self.enable_modbus).pack(fill="x")
        ttk.Button(output, text="退出 Modbus 控制", style="Secondary.TButton", command=self.disable_modbus).pack(fill="x", pady=(7, 15))
        self.output_label = tk.Label(output, textvariable=self.output_state, background=PALETTE["surface"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 10, "bold"), anchor="w")
        self.output_label.pack(fill="x", pady=(0, 7))
        ttk.Button(output, text="使能伺服输出", style="Primary.TButton", command=self.enable_output).pack(fill="x")
        ttk.Button(output, text="失能伺服输出", style="Danger.TButton", command=self.disable_output).pack(fill="x", pady=(7, 0))
        state = ttk.LabelFrame(body, text="设备状态", style="Panel.TLabelframe", padding=18)
        state.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        for index in range(4):
            state.columnconfigure(index, weight=1)
        self.connection_card = StatusCard(state, "连接状态", "未连接", "等待串口连接")
        self.connection_card.grid(row=0, column=0, padx=(0, 10), sticky="ew")
        self.alarm_card = StatusCard(state, "报警代码", "--", "请读取设备状态")
        self.alarm_card.grid(row=0, column=1, padx=5, sticky="ew")
        self.speed_card = StatusCard(state, "当前转速", "--", "RPM")
        self.speed_card.grid(row=0, column=2, padx=5, sticky="ew")
        self.position_card = StatusCard(state, "当前位置", "--", "脉冲")
        self.position_card.grid(row=0, column=3, padx=(10, 0), sticky="ew")
        footer = ttk.Frame(body, style="Canvas.TFrame")
        footer.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Button(footer, text="读取设备状态", style="Secondary.TButton", command=self.app.refresh_status).pack(side="left")
        self.message = tk.Label(footer, text="准备就绪", background=PALETTE["canvas"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 9), anchor="e")
        self.message.pack(side="right")

    def _field(self, parent: ttk.LabelFrame, row: int, label: str, widget: ttk.Widget) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, pady=7, sticky="w")
        widget.grid(row=row, column=1, pady=7, padx=(16, 0), sticky="ew")

    def set_ports(self, ports: list[str]) -> None:
        self.port_box.configure(values=ports)
        if ports and not self.port.get().strip():
            self.port.set(ports[0])

    def _settings(self) -> ConnectionSettings:
        return ConnectionSettings(
            port=self.port.get(),
            address=_parse_int(self.address.get(), "设备地址"),
            baudrate=_parse_int(self.baudrate.get(), "波特率"),
            timeout_s=_parse_float(self.timeout.get(), "超时"),
            retries=_parse_int(self.retries.get(), "重试次数"),
        )

    def connect(self) -> None:
        try:
            settings = self._settings()
            settings.validate()
        except ValueError as error:
            messagebox.showwarning("连接参数无效", str(error))
            return
        self.app.run_action("连接串口", lambda: self.app.session.connect(settings), self._connected)

    def _connected(self, _: object) -> None:
        self.app.set_connection_state(True, "串口已连接，尚未使能输出")
        self.connection_card.set("已连接", "可开始读取状态", color=PALETTE["success"])
        self.app.refresh_status(quiet=True)

    def disconnect(self) -> None:
        if not self.app.session.connected:
            return
        self.app.run_action("断开串口", lambda: self.app.session.disconnect(disable_output=True), self._disconnected)

    def _disconnected(self, _: object) -> None:
        self.app.set_connection_state(False)
        self.connection_card.set("未连接", "等待串口连接", color=PALETTE["text"])
        self.modbus_state.set("通讯控制未使能")
        self.output_state.set("输出未使能")
        self.modbus_label.configure(foreground=PALETTE["muted"])
        self.output_label.configure(foreground=PALETTE["muted"])

    def enable_modbus(self) -> None:
        self.app.run_action("启用 Modbus 控制", lambda: self.app.session.call(lambda drive: drive.enable_modbus()), lambda _: self.app.refresh_status())

    def disable_modbus(self) -> None:
        if not messagebox.askyesno("确认退出通讯控制", "退出 Modbus 控制后，通讯定位命令将不可用。是否继续？"):
            return
        self.app.run_action("退出 Modbus 控制", lambda: self.app.session.call(lambda drive: drive.disable_modbus()), lambda _: self.app.refresh_status())

    def enable_output(self) -> None:
        if not messagebox.askyesno("确认使能伺服", "请确认机构安全、可自由运动，并已准备好独立物理急停。是否使能输出？"):
            return
        self.app.run_action("使能伺服输出", lambda: self.app.session.call(lambda drive: drive.enable_output()), lambda _: self.app.refresh_status())

    def disable_output(self) -> None:
        self.app.run_action("失能伺服输出", lambda: self.app.session.call(lambda drive: drive.disable_output()), lambda _: self.app.refresh_status())

    def set_connection_state(self, connected: bool, detail: str) -> None:
        if not connected:
            self.connection_card.set("未连接", "等待串口连接", color=PALETTE["text"])
        elif detail:
            self.connection_card.set("已连接", detail, color=PALETTE["success"])

    def apply_status(self, status: DriveStatus) -> None:
        self.modbus_state.set("通讯控制已使能" if status.modbus_enabled else "通讯控制未使能")
        self.output_state.set("伺服输出已使能" if status.output_enabled else "输出未使能")
        self.modbus_label.configure(foreground=PALETTE["success"] if status.modbus_enabled else PALETTE["muted"])
        self.output_label.configure(foreground=PALETTE["success"] if status.output_enabled else PALETTE["muted"])
        alarm_text = f"0x{int(status.alarm):02X}" if isinstance(status.alarm, int) else str(status.alarm)
        alarm_color = PALETTE["success"] if int(status.alarm) == 0 else PALETTE["danger"]
        self.alarm_card.set(alarm_text, "正常" if int(status.alarm) == 0 else "请检查驱动器", color=alarm_color)
        self.speed_card.set(f"{status.speed_rpm:.1f}", "RPM")
        self.position_card.set(f"{status.absolute_position:,}", "脉冲")


class ModbusControlPage(ScrollablePage):
    """Position, feedback and low-level Modbus RTU controls."""

    def __init__(self, parent: tk.Misc, app: MotorControlApp) -> None:
        super().__init__(parent)
        self.app = app
        self.connected = False
        self.speed = tk.StringVar(value="500")
        self.acceleration = tk.StringVar(value="3000")
        self.absolute_target = tk.StringVar(value="32768")
        self.relative_target = tk.StringVar(value="100")
        self.wait_for_position = tk.BooleanVar(value=True)
        self.clear_ack = tk.BooleanVar(value=False)
        self.auto_refresh = tk.BooleanVar(value=True)
        self.poll_interval = tk.DoubleVar(value=0.5)
        self.raw_mode = tk.StringVar(value="read")
        self.raw_register = tk.StringVar(value="0x16")
        self.raw_count = tk.StringVar(value="2")
        self.raw_value = tk.StringVar(value="0")
        self.raw_function = tk.StringVar(value="0x03")
        self.raw_data = tk.StringVar(value="00 16 00 02")
        self.allow_raw_write = tk.BooleanVar(value=False)
        self._build()

    def _build(self) -> None:
        body = self.body
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="位置控制与实时反馈", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="所有位置均使用编码器脉冲；单圈为 32768 脉冲。", style="Subtitle.TLabel").grid(row=1, column=0, pady=(4, 18), sticky="w")
        feedback = ttk.LabelFrame(body, text="实时反馈", style="Panel.TLabelframe", padding=18)
        feedback.grid(row=2, column=0, sticky="ew")
        for index in range(6):
            feedback.columnconfigure(index, weight=1)
        self.feedback_cards = {
            "position": StatusCard(feedback, "绝对位置", "--", "脉冲"),
            "turns": StatusCard(feedback, "圈数", "--", "转"),
            "speed": StatusCard(feedback, "当前转速", "--", "RPM"),
            "current": StatusCard(feedback, "系统电流", "--", "A"),
            "voltage": StatusCard(feedback, "系统电压", "--", "V"),
            "temperature": StatusCard(feedback, "系统温度", "--", "°C"),
        }
        for index, card in enumerate(self.feedback_cards.values()):
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 0 if index == 5 else 5))
        controls = ttk.Frame(feedback, style="Panel.TFrame")
        controls.grid(row=1, column=0, columnspan=6, sticky="w", pady=(15, 0))
        ttk.Button(controls, text="立即刷新", style="Secondary.TButton", command=self.app.refresh_status).pack(side="left")
        ttk.Checkbutton(controls, text="自动刷新", variable=self.auto_refresh, command=self._toggle_poll).pack(side="left", padx=(14, 8))
        ttk.Label(controls, text="间隔（秒）", style="Panel.TLabel").pack(side="left")
        ttk.Spinbox(controls, from_=0.2, to=10.0, increment=0.1, textvariable=self.poll_interval, width=6).pack(side="left", padx=(6, 0))
        motion_area = ttk.Frame(body, style="Canvas.TFrame")
        motion_area.grid(row=3, column=0, sticky="nsew", pady=(18, 0))
        motion_area.columnconfigure(0, weight=1)
        motion_area.columnconfigure(1, weight=1)
        config = ttk.LabelFrame(motion_area, text="1. 运动参数", style="Panel.TLabelframe", padding=18)
        config.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        config.columnconfigure(1, weight=1)
        self._field(config, 0, "目标速度（RPM）", ttk.Entry(config, textvariable=self.speed))
        self._field(config, 1, "加速度（RPM/s）", ttk.Entry(config, textvariable=self.acceleration))
        ttk.Label(config, text="发送定位时会先自动应用这里的参数。", style="Panel.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(config, text="仅发送运动参数", style="Secondary.TButton", command=self.apply_motion).grid(row=3, column=0, columnspan=2, sticky="w", pady=(9, 0))
        position = ttk.LabelFrame(motion_area, text="2. 定位控制", style="Panel.TLabelframe", padding=18)
        position.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        position.columnconfigure(1, weight=1)
        self._field(position, 0, "绝对目标（脉冲）", ttk.Entry(position, textvariable=self.absolute_target))
        self._field(position, 1, "相对位移（脉冲）", ttk.Entry(position, textvariable=self.relative_target))
        ttk.Checkbutton(position, text="等待到位（±10 脉冲）", variable=self.wait_for_position).grid(row=2, column=0, columnspan=2, sticky="w", pady=(2, 7))
        buttons = ttk.Frame(position, style="Panel.TFrame")
        buttons.grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Button(buttons, text="按参数发送绝对位置", style="Primary.TButton", command=self.move_absolute).pack(side="left")
        ttk.Button(buttons, text="按参数发送相对位置", style="Secondary.TButton", command=self.move_relative).pack(side="left", padx=(8, 0))
        safety = ttk.LabelFrame(body, text="回零与安全操作", style="Panel.TLabelframe", padding=18)
        safety.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        safety.columnconfigure(4, weight=1)
        ttk.Button(safety, text="原点开关回零", style="Secondary.TButton", command=lambda: self._special("home_switch")).grid(row=0, column=0, padx=(0, 8), pady=(0, 8), sticky="w")
        ttk.Button(safety, text="机械回零 + 36°", style="Secondary.TButton", command=lambda: self._special("home_mechanical")).grid(row=0, column=1, padx=8, pady=(0, 8), sticky="w")
        ttk.Button(safety, text="回编码器零点", style="Secondary.TButton", command=lambda: self._special("home_encoder")).grid(row=0, column=2, padx=8, pady=(0, 8), sticky="w")
        ttk.Button(safety, text="软件急停", style="Danger.TButton", command=self.emergency_stop).grid(row=0, column=3, padx=(8, 0), pady=(0, 8), sticky="w")
        ttk.Checkbutton(safety, text="我确认要将当前位置清零", variable=self.clear_ack).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(safety, text="清除绝对位置", style="Secondary.TButton", command=self.clear_position).grid(row=1, column=2, padx=8, sticky="w", pady=(4, 0))
        ttk.Button(safety, text="保存当前参数", style="Secondary.TButton", command=lambda: self._run_drive("保存参数", lambda drive: drive.save_parameters())).grid(row=1, column=3, padx=(8, 0), sticky="w", pady=(4, 0))
        raw = ttk.LabelFrame(body, text="Modbus 寄存器与协议调试", style="Panel.TLabelframe", padding=18)
        raw.grid(row=5, column=0, sticky="ew", pady=(18, 0))
        raw.columnconfigure(3, weight=1)
        ttk.Radiobutton(raw, text="读取寄存器", variable=self.raw_mode, value="read", command=self._update_raw_form).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(raw, text="写入单个寄存器", variable=self.raw_mode, value="write", command=self._update_raw_form).grid(row=0, column=1, sticky="w", padx=(18, 0))
        self._field(raw, 1, "起始地址", ttk.Entry(raw, textvariable=self.raw_register, width=14), column=0)
        self.raw_count_label = ttk.Label(raw, text="读取数量", style="Panel.TLabel")
        self.raw_count_box = ttk.Entry(raw, textvariable=self.raw_count, width=14)
        self.raw_count_label.grid(row=1, column=2, padx=(18, 6), sticky="w")
        self.raw_count_box.grid(row=1, column=3, sticky="w")
        self.raw_value_label = ttk.Label(raw, text="写入值", style="Panel.TLabel")
        self.raw_value_box = ttk.Entry(raw, textvariable=self.raw_value, width=14)
        ttk.Button(raw, text="执行寄存器操作", style="Secondary.TButton", command=self.register_operation).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Separator(raw, orient="horizontal").grid(row=3, column=0, columnspan=4, sticky="ew", pady=18)
        ttk.Label(raw, text="高级原始请求（SDK 自动附加 CRC）", style="Panel.TLabel").grid(row=4, column=0, columnspan=4, sticky="w")
        self._field(raw, 5, "功能码", ttk.Entry(raw, textvariable=self.raw_function, width=14), column=0)
        ttk.Label(raw, text="数据字节（十六进制）", style="Panel.TLabel").grid(row=5, column=2, padx=(18, 6), sticky="w")
        ttk.Entry(raw, textvariable=self.raw_data, width=32).grid(row=5, column=3, sticky="ew")
        ttk.Checkbutton(raw, text="我确认原始写命令可能改变驱动器状态", variable=self.allow_raw_write).grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Button(raw, text="发送原始请求", style="Secondary.TButton", command=self.raw_request).grid(row=6, column=3, sticky="e", pady=(12, 0))
        self.raw_result = tk.Text(raw, height=5, background=PALETTE["input"], foreground=PALETTE["text"], relief="solid", borderwidth=1, highlightthickness=0, font=(MONOSPACE_FONT_FAMILY, 10), state="disabled")
        self.raw_result.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        footer = ttk.Frame(body, style="Canvas.TFrame")
        footer.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        self.message = tk.Label(footer, text="请先连接串口", background=PALETTE["canvas"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 9), anchor="w")
        self.message.pack(side="left")
        self._update_raw_form()

    def _field(self, parent: ttk.LabelFrame, row: int, label: str, widget: ttk.Widget, *, column: int = 0) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=column, sticky="w", pady=7)
        widget.grid(row=row, column=column + 1, sticky="ew" if column == 0 else "w", padx=(12 if column == 0 else 6, 0), pady=7)

    def _toggle_poll(self) -> None:
        if self.auto_refresh.get():
            self.app.start_polling()
        else:
            self.app.stop_polling()

    def set_connection_state(self, connected: bool) -> None:
        self.connected = connected
        if connected:
            self.app.start_polling()
        else:
            self.app.stop_polling()
            for card in self.feedback_cards.values():
                card.set("--")

    def apply_status(self, status: DriveStatus) -> None:
        self.feedback_cards["position"].set(f"{status.absolute_position:,}", "脉冲")
        self.feedback_cards["turns"].set(f"{status.absolute_position / 32768:.4f}", "转")
        self.feedback_cards["speed"].set(f"{status.speed_rpm:.1f}", "RPM")
        self.feedback_cards["current"].set(f"{status.current_a:.3f}", "A")
        self.feedback_cards["voltage"].set(f"{status.voltage_v:.2f}", "V")
        color = PALETTE["danger"] if status.temperature_c >= 80 else PALETTE["text"]
        self.feedback_cards["temperature"].set(str(status.temperature_c), "°C", color=color)

    def _run_drive(self, label: str, operation: Callable[[object], T], on_success: Callable[[T], None] | None = None) -> None:
        if not self.app.session.connected:
            messagebox.showwarning("尚未连接", "请先在“连接与使能”页面连接串口。")
            return
        self.app.run_action(label, lambda: self.app.session.call(operation), on_success)

    def apply_motion(self) -> None:
        try:
            speed, acceleration = self._motion_parameters()
        except ValueError as error:
            messagebox.showwarning("运动参数无效", str(error))
            return
        self._run_drive("发送运动参数", lambda drive: drive.configure_motion(max_speed_rpm=speed, acceleration_rpm_s=acceleration))

    def _motion_parameters(self) -> tuple[int, int]:
        """Read the parameters that must be applied before a position command."""
        return (
            _parse_int(self.speed.get(), "目标速度"),
            _parse_int(self.acceleration.get(), "加速度"),
        )

    def move_absolute(self) -> None:
        try:
            target = _parse_int(self.absolute_target.get(), "绝对目标")
            speed, acceleration = self._motion_parameters()
        except ValueError as error:
            messagebox.showwarning("定位参数无效", str(error))
            return
        if target == 0:
            messagebox.showwarning("绝对位置为零", "通信模式下写入绝对位置 0 可能执行清零。请使用“清除绝对位置”操作。")
            return
        wait = self.wait_for_position.get()
        self._run_drive(
            "设置运动参数并发送绝对位置",
            lambda drive: self._configure_then_move_absolute(drive, speed, acceleration, target, wait),
            lambda _: self.app.refresh_status(quiet=True),
        )

    def move_relative(self) -> None:
        try:
            pulses = _parse_int(self.relative_target.get(), "相对位移")
            speed, acceleration = self._motion_parameters()
        except ValueError as error:
            messagebox.showwarning("定位参数无效", str(error))
            return
        self._run_drive(
            "设置运动参数并发送相对位置",
            lambda drive: self._configure_then_move_relative(drive, speed, acceleration, pulses),
            lambda _: self.app.refresh_status(quiet=True),
        )

    @staticmethod
    def _configure_then_move_absolute(drive: object, speed: int, acceleration: int, target: int, wait: bool) -> None:
        drive.configure_motion(max_speed_rpm=speed, acceleration_rpm_s=acceleration)
        drive.move_absolute(target, wait=wait)

    @staticmethod
    def _configure_then_move_relative(drive: object, speed: int, acceleration: int, pulses: int) -> None:
        drive.configure_motion(max_speed_rpm=speed, acceleration_rpm_s=acceleration)
        drive.move_relative(pulses)

    def _special(self, action: str) -> None:
        prompts = {
            "home_switch": ("原点开关回零", "请确认原点开关已接入 EN 输入且机构行程安全。是否开始？", lambda drive: drive.home_switch()),
            "home_mechanical": ("机械回零", "此操作会让电机反向运行至堵转，再前进 36°。是否确认机构可安全堵转？", lambda drive: drive.home_mechanical()),
            "home_encoder": ("编码器零点回零", "此操作会让电机反向运行至堵转，再运行至编码器零点。是否继续？", lambda drive: drive.home_mechanical(to_encoder_zero=True)),
        }
        title, prompt, operation = prompts[action]
        if messagebox.askyesno(title, prompt):
            self._run_drive(title, operation)

    def emergency_stop(self) -> None:
        if messagebox.askyesno("确认软件急停", "将执行手册中的通讯急停流程。它不能替代独立物理急停。是否继续？"):
            self._run_drive("执行软件急停", lambda drive: drive.emergency_stop(), lambda _: self.app.refresh_status(quiet=True))

    def clear_position(self) -> None:
        if not self.clear_ack.get():
            messagebox.showwarning("需要确认", "请勾选“我确认要将当前位置清零”。")
            return
        self._run_drive("清除绝对位置", lambda drive: drive.clear_absolute_position(acknowledge=True), self._clear_done)

    def _clear_done(self, _: object) -> None:
        self.clear_ack.set(False)
        self.app.refresh_status(quiet=True)

    def _update_raw_form(self) -> None:
        read_mode = self.raw_mode.get() == "read"
        if read_mode:
            self.raw_count_label.grid()
            self.raw_count_box.grid()
            self.raw_value_label.grid_remove()
            self.raw_value_box.grid_remove()
        else:
            self.raw_count_label.grid_remove()
            self.raw_count_box.grid_remove()
            self.raw_value_label.grid(row=1, column=2, padx=(18, 6), sticky="w")
            self.raw_value_box.grid(row=1, column=3, sticky="w")

    def register_operation(self) -> None:
        try:
            register = _parse_int(self.raw_register.get(), "寄存器地址")
            if self.raw_mode.get() == "read":
                count = _parse_int(self.raw_count.get(), "读取数量")
                if count < 1:
                    raise ValueError("读取数量必须大于零")
                self._run_drive("读取寄存器", lambda drive: drive.read_registers(register, count), self._show_register_values)
            else:
                value = _parse_int(self.raw_value.get(), "写入值")
                if not messagebox.askyesno("确认写寄存器", f"将向寄存器 0x{register:04X} 写入 0x{value:04X}。是否继续？"):
                    return
                self._run_drive("写入寄存器", lambda drive: drive.write_register(register, value), lambda _: self._show_raw_result("写入完成"))
        except ValueError as error:
            messagebox.showwarning("寄存器参数无效", str(error))

    def _show_register_values(self, values: list[int]) -> None:
        start = _parse_int(self.raw_register.get(), "寄存器地址")
        lines = [f"0x{start + offset:04X}: 0x{value:04X}  ({value})" for offset, value in enumerate(values)]
        self._show_raw_result("\n".join(lines))

    def raw_request(self) -> None:
        try:
            function = _parse_int(self.raw_function.get(), "功能码")
            if not 0 <= function <= 0xFF:
                raise ValueError("功能码必须在 0x00 到 0xFF 之间")
            hex_text = self.raw_data.get().replace(" ", "").replace("0x", "")
            if len(hex_text) % 2:
                raise ValueError("十六进制数据必须由完整字节组成")
            data = bytes.fromhex(hex_text)
        except ValueError as error:
            messagebox.showwarning("原始请求无效", str(error))
            return
        if function in (0x06, 0x10, 0x78, 0x7A) and not self.allow_raw_write.get():
            messagebox.showwarning("需要确认", "发送可能写入驱动器的原始功能码前，请先勾选确认框。")
            return
        if not messagebox.askyesno("确认原始 Modbus 请求", f"发送功能码 0x{function:02X}，数据：{data.hex(' ').upper()}？"):
            return
        self._run_drive("发送原始请求", lambda drive: drive.client.request(drive.address, function, data), self._show_raw_response)

    def _show_raw_response(self, response: bytes) -> None:
        self._show_raw_result("响应数据：" + (response.hex(" ").upper() if response else "<空>"))

    def _show_raw_result(self, text: str) -> None:
        self.raw_result.configure(state="normal")
        self.raw_result.delete("1.0", "end")
        self.raw_result.insert("1.0", text)
        self.raw_result.configure(state="disabled")


class LiftPlatformPage(ScrollablePage):
    """Centimetre-based control and feedback panel for the calibrated lift."""

    def __init__(self, parent: tk.Misc, app: MotorControlApp) -> None:
        super().__init__(parent)
        self.app = app
        self.target_height = tk.StringVar(value="54")
        self.speed_level = tk.StringVar(value="1")
        self.wait_for_position = tk.BooleanVar(value=True)
        self.target_pulses = tk.StringVar(value="--")
        self.profile_summary = tk.StringVar(value="--")
        self.target_height.trace_add("write", self._update_preview)
        self.speed_level.trace_add("write", self._update_preview)
        self._build()
        self._update_preview()

    def _build(self) -> None:
        body = self.body
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="升降台厘米定位", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            body,
            text="标定：54 cm = 绝对脉冲 1；每 2.2 cm = 100000 脉冲。执行会先设置速度和加速度，再发送绝对位置。",
            style="Subtitle.TLabel",
            wraplength=850,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 18))

        control = ttk.LabelFrame(body, text="目标高度与速度", style="Panel.TLabelframe", padding=18)
        control.grid(row=2, column=0, sticky="nsew", padx=(0, 9))
        control.columnconfigure(1, weight=1)
        self._field(control, 0, "目标高度（cm）", ttk.Entry(control, textvariable=self.target_height))
        ttk.Label(control, text="允许范围：54 到 120 cm", style="PanelMuted.TLabel").grid(row=1, column=1, sticky="w", pady=(0, 7))
        self._field(
            control,
            2,
            "速度档位",
            ttk.Combobox(control, textvariable=self.speed_level, values=("1", "2", "3"), state="readonly"),
        )
        ttk.Label(control, textvariable=self.profile_summary, style="PanelMuted.TLabel").grid(row=3, column=1, sticky="w", pady=(0, 7))
        ttk.Checkbutton(control, text="等待到位（±10 脉冲，最长 45 秒）", variable=self.wait_for_position).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(control, text="按厘米定位", style="Primary.TButton", command=self.move_to_height).grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))

        preview = ttk.LabelFrame(body, text="指令预览", style="Panel.TLabelframe", padding=18)
        preview.grid(row=2, column=1, sticky="nsew", padx=(9, 0))
        preview.columnconfigure(1, weight=1)
        self._field(preview, 0, "目标绝对脉冲", ttk.Label(preview, textvariable=self.target_pulses, style="Panel.TLabel"))
        ttk.Label(
            preview,
            text="取最近整数脉冲；本页不修改零位或标定值。",
            style="PanelMuted.TLabel",
            wraplength=330,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        feedback = ttk.LabelFrame(body, text="当前升降台反馈", style="Panel.TLabelframe", padding=18)
        feedback.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        feedback.columnconfigure(0, weight=1)
        feedback.columnconfigure(1, weight=1)
        self.height_card = StatusCard(feedback, "当前高度", "--", "cm")
        self.height_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.position_card = StatusCard(feedback, "当前绝对位置", "--", "脉冲")
        self.position_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Button(feedback, text="读取当前高度", style="Secondary.TButton", command=self.read_height).grid(row=1, column=0, columnspan=2, sticky="w", pady=(15, 0))

        safety = ttk.LabelFrame(body, text="操作前确认", style="Panel.TLabelframe", padding=18)
        safety.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Label(
            safety,
            text="请先在“连接与使能”页连接串口、启用 Modbus 控制和伺服输出，并确认行程安全。",
            style="Panel.TLabel",
            wraplength=850,
        ).pack(anchor="w")

        footer = ttk.Frame(body, style="Canvas.TFrame")
        footer.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.message = tk.Label(footer, text="请先连接串口并确认升降台安全", background=PALETTE["canvas"], foreground=PALETTE["muted"], font=(FONT_FAMILY, 9), anchor="w")
        self.message.pack(side="left")

    @staticmethod
    def _field(parent: ttk.LabelFrame, row: int, label: str, widget: ttk.Widget) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=7)
        widget.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=7)

    def _update_preview(self, *_: object) -> None:
        try:
            target = LiftPlatform.height_to_absolute_position(self.target_height.get())
            profile = LiftPlatform.speed_profile(_parse_int(self.speed_level.get(), "速度档位"))
        except ValueError as error:
            self.target_pulses.set(f"无效：{error}")
            self.profile_summary.set("请选择速度档位 1、2 或 3")
            return
        self.target_pulses.set(f"{target:,}")
        self.profile_summary.set(f"目标速度 {profile.target_speed_rpm} RPM；加速度 {profile.acceleration_rpm_s} RPM/s")

    def move_to_height(self) -> None:
        try:
            height = self.target_height.get()
            target = LiftPlatform.height_to_absolute_position(height)
            speed = _parse_int(self.speed_level.get(), "速度档位")
            LiftPlatform.speed_profile(speed)
        except ValueError as error:
            messagebox.showwarning("升降台参数无效", str(error))
            return
        if not messagebox.askyesno(
            "确认升降台定位",
            f"将升降台移动到 {height} cm（绝对脉冲 {target}），速度档位 {speed}。\n\n请确认行程内无人和障碍物。是否继续？",
        ):
            return
        wait = self.wait_for_position.get()
        self._run_drive(
            "设置升降台参数并定位",
            lambda drive: LiftPlatform(drive).move_to_height(height, speed, wait=wait),
            lambda _: self.app.refresh_status(quiet=True),
        )

    def read_height(self) -> None:
        self._run_drive("读取升降台高度", lambda drive: LiftPlatform(drive).read_height_cm(), self._show_height)

    def _run_drive(self, label: str, operation: Callable[[object], T], on_success: Callable[[T], None] | None = None) -> None:
        if not self.app.session.connected:
            messagebox.showwarning("尚未连接", "请先在“连接与使能”页面连接串口。")
            return
        self.app.run_action(label, lambda: self.app.session.call(operation), on_success)

    def _show_height(self, height: object) -> None:
        self.height_card.set(f"{height:.4f}", "cm")

    def set_connection_state(self, connected: bool) -> None:
        if not connected:
            self.height_card.set("--")
            self.position_card.set("--")

    def apply_status(self, status: DriveStatus) -> None:
        self.position_card.set(f"{status.absolute_position:,}", "脉冲")
        height = LiftPlatform.absolute_position_to_height(status.absolute_position)
        self.height_card.set(f"{height:.4f}", "cm")


def main() -> None:
    """Start the desktop GUI."""
    app = MotorControlApp()
    app.mainloop()


if __name__ == "__main__":
    main()

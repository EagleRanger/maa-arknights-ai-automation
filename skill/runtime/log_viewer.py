"""日志悬浮窗 - 实时显示脚本运行状态"""
import tkinter as tk
import ctypes
import os

try:
    from phantom_log_localization import localize_phantom_log_line
except ImportError:
    localize_phantom_log_line = None

ctypes.windll.shcore.SetProcessDpiAwareness(1)

BASE = os.environ.get("ARKNIGHTS_AUTO_BASE", os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.environ.get("ARKNIGHTS_LOG_FILE", os.path.join(BASE, "outputs", "auto_run.log"))
_STATUS_FILE_OVERRIDE = os.environ.get("ARKNIGHTS_STATUS_FILE")
_STATUS_TEXT_OVERRIDE = os.environ.get("ARKNIGHTS_STATUS_TEXT")
# A long-term supervisor supplies its own status text.  In that mode the daily
# status.txt belongs to a different workflow and must not overwrite the viewer
# header with stale mainline text such as H12-4.
STATUS_FILE = _STATUS_FILE_OVERRIDE or (
    None if _STATUS_TEXT_OVERRIDE else os.path.join(BASE, "outputs", "status.txt")
)
WINDOW_TITLE = os.environ.get("ARKNIGHTS_LOG_TITLE", "明日方舟自动化运行日志")
LOCALIZE_PHANTOM = "傀影肉鸽" in WINDOW_TITLE and localize_phantom_log_line is not None
DEFAULT_STATUS = os.environ.get("ARKNIGHTS_STATUS_TEXT", "启动中...")
MAX_TEXT_LINES = max(500, int(os.environ.get("ARKNIGHTS_LOG_VIEWER_MAX_LINES", "3000")))
STOP_FILE = os.path.join(BASE, "outputs", "log_viewer.stop")
PID_FILE = os.path.join(BASE, "outputs", "log_viewer.pid")


def acquire_viewer_mutex():
    """日志窗单实例，避免每次运行重复弹窗。"""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ArknightsAutoLogViewer")
    if not handle or kernel32.GetLastError() == 183:
        if handle:
            kernel32.CloseHandle(handle)
        return None
    return handle

class LogViewer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry("800x500+50+50")
        # MuMu/MAA会频繁切换前台窗口。始终置顶会在每次切换时重新抢到
        # Z-order，看起来像旧日志窗反复闪现。日志窗应保持为普通窗口，
        # 需要查看时由用户手动切回，不得干扰游戏画面。
        self.root.attributes("-topmost", False)
        self.last_pos = 0  # 文件读取位置

        # 状态栏
        self.status_label = tk.Label(self.root, text=DEFAULT_STATUS, font=("Microsoft YaHei UI", 12, "bold"),
                                      bg="#1e1e1e", fg="#00ff00", anchor="w", padx=10, pady=4)
        self.status_label.pack(fill=tk.X)

        # 日志文本框 + 滚动条
        frame = tk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text = tk.Text(frame, font=("Microsoft YaHei UI", 10), bg="#1e1e1e", fg="#cccccc",
                           wrap=tk.WORD, yscrollcommand=scrollbar.set)
        self.text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text.yview)

        # 颜色标签
        self.text.tag_config("error", foreground="#ff4444")
        self.text.tag_config("warn", foreground="#ffaa00")
        self.text.tag_config("success", foreground="#00ff00")
        self.text.tag_config("info", foreground="#cccccc")

        self.root.after(1000, self.update_log)
        self.root.mainloop()

    def at_bottom(self):
        """检查用户是否在底部"""
        return self.text.yview()[1] >= 0.98

    def update_log(self):
        try:
            if os.path.exists(STOP_FILE):
                self.root.destroy()
                return
            # 读状态
            if STATUS_FILE and os.path.exists(STATUS_FILE):
                with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                    self.status_label.config(text=f.read().strip())

            # 增量读取日志(只读新增部分)
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, 'r', encoding='utf-8') as f:
                    f.seek(self.last_pos)
                    new_content = f.read()
                    self.last_pos = f.tell()

                if new_content:
                    should_scroll = self.at_bottom()
                    for line in new_content.splitlines():
                        if LOCALIZE_PHANTOM:
                            line = localize_phantom_log_line(line)
                        if "[ERROR]" in line or "❌" in line:
                            self.text.insert(tk.END, line + "\n", "error")
                        elif "[WARN]" in line or "⚠️" in line:
                            self.text.insert(tk.END, line + "\n", "warn")
                        elif "通关" in line or "✅" in line:
                            self.text.insert(tk.END, line + "\n", "success")
                        else:
                            self.text.insert(tk.END, line + "\n", "info")

                    # Tk Text 会把所有历史文本永久留在进程内。长跑只保留最近
                    # 3000 行；完整日志仍在磁盘，窗口内存不再随运行时间增长。
                    line_count = int(self.text.index("end-1c").split(".")[0])
                    excess = line_count - MAX_TEXT_LINES
                    if excess > 0:
                        self.text.delete("1.0", f"{excess + 1}.0")

                    if should_scroll:
                        self.text.see(tk.END)

        except Exception:
            pass

        self.root.after(2000, self.update_log)

if __name__ == "__main__":
    _mutex = acquire_viewer_mutex()
    if _mutex:
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
        try:
            LogViewer()
        finally:
            try:
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
            except OSError:
                pass

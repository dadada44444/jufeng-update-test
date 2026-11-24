#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷电模拟器验证码自动识别 - 手动窗口指定版
不依赖窗口枚举，手动指定 HWND 或坐标区域
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from PIL import Image, ImageTk
import cv2
import numpy as np
import pyautogui
import threading
import time
import ctypes
from ctypes import wintypes
import os
import json

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [wintypes.HWND]
SetForegroundWindow.restype = wintypes.BOOL

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
ShowWindow.restype = wintypes.BOOL

IsIconic = user32.IsIconic
IsIconic.argtypes = [wintypes.HWND]
IsIconic.restype = wintypes.BOOL

PostMessageW = user32.PostMessageW
PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
PostMessageW.restype = wintypes.BOOL

class DigitRecognizer:
    def __init__(self):
        self.templates = {}
        self._build_templates()
    
    def _build_templates(self):
        fonts = [
            (cv2.FONT_HERSHEY_SIMPLEX, 2.0, 3),
            (cv2.FONT_HERSHEY_SIMPLEX, 2.5, 4),
            (cv2.FONT_HERSHEY_TRIPLEX, 2.0, 3),
            (cv2.FONT_HERSHEY_DUPLEX, 2.0, 3),
        ]
        sizes = [(60, 40), (80, 50), (100, 60)]
        for font, scale, thick in fonts:
            for h, w in sizes:
                for d in range(10):
                    img = np.ones((h, w), dtype=np.uint8) * 255
                    cv2.putText(img, str(d), (5, int(h*0.8)), font, scale, 0, thick, cv2.LINE_AA)
                    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
                    norm = cv2.resize(img, (50, 80))
                    if d not in self.templates:
                        self.templates[d] = []
                    self.templates[d].append(norm)
    
    def load_custom_templates(self, template_dir):
        if not template_dir or not os.path.exists(template_dir):
            return False
        loaded = 0
        for digit in range(10):
            for ext in ['.png', '.jpg', '.bmp']:
                path = os.path.join(template_dir, f"{digit}{ext}")
                if os.path.exists(path):
                    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                    if img is not None:
                        _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
                        norm = cv2.resize(img, (50, 80))
                        if digit not in self.templates:
                            self.templates[digit] = []
                        self.templates[digit].append(norm)
                        loaded += 1
                        break
        return loaded > 0
    
    def preprocess(self, image):
        if isinstance(image, Image.Image):
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        else:
            img = image
        results = []
        for scale in [1.5, 2.0, 2.5]:
            h, w = img.shape[:2]
            resized = cv2.resize(img, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            gray = clahe.apply(gray)
            blurred = cv2.GaussianBlur(gray, (3,3), 0)
            thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4)
            results.append(thresh)
        return results
    
    def segment(self, binary_img):
        contours, _ = cv2.findContours(binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = binary_img.shape
        regions = []
        for cnt in contours:
            x, y, rw, rh = cv2.boundingRect(cnt)
            if rw < 8 or rh < 15:
                continue
            regions.append((x, y, rw, rh))
        regions.sort(key=lambda r: r[0])
        return regions
    
    def recognize_digit(self, roi):
        if roi.shape[0] < 12 or roi.shape[1] < 8:
            return None, 0
        input_n = cv2.resize(roi, (50, 80))
        _, input_n = cv2.threshold(input_n, 127, 255, cv2.THRESH_BINARY_INV)
        best_d, best_s = None, -1
        for d, templs in self.templates.items():
            for t in templs:
                r = cv2.matchTemplate(input_n, t, cv2.TM_CCOEFF_NORMED)
                _, mv, _, _ = cv2.minMaxLoc(r)
                if mv > best_s:
                    best_s = mv
                    best_d = d
        if best_d is not None and best_s > 0.30:
            return str(best_d), best_s
        return None, best_s
    
    def recognize(self, image):
        pipelines = self.preprocess(image)
        best_text, best_info, best_score = None, "", -1
        for binary in pipelines:
            regions = self.segment(binary)
            if not regions:
                continue
            regions.sort(key=lambda r: r[2]*r[3], reverse=True)
            regions = regions[:8]
            regions.sort(key=lambda r: r[0])
            digits = []
            confs = []
            for x, y, w, h in regions:
                pad = 4
                y1, y2 = max(0,y-pad), min(binary.shape[0], y+h+pad)
                x1, x2 = max(0,x-pad), min(binary.shape[1], x+w+pad)
                roi = binary[y1:y2, x1:x2]
                if roi.shape[0] < 12 or roi.shape[1] < 8:
                    continue
                d, c = self.recognize_digit(roi)
                if d:
                    digits.append(d)
                    confs.append(c)
            if len(digits) >= 3:
                text = ''.join(digits)
                avg = sum(confs)/len(confs)
                score = len(digits) * avg
                if score > best_score:
                    best_score = score
                    best_text = text
                    best_info = f"识别: {text} (置信度: {avg:.2f})"
        if best_text:
            return best_text, best_info
        return None, "识别失败"


class CaptchaWindow:
    """表示一个要处理的模拟器窗口，手动指定 HWND 或坐标"""
    def __init__(self, name, hwnd=None, left=0, top=0, width=0, height=0):
        self.name = name
        self.hwnd = hwnd
        self.left = left
        self.top = top
        self.width = width
        self.height = height


class CaptchaRecognizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("雷电验证码自动识别 - 手动窗口指定版")
        self.root.geometry("1200x800")
        self.root.resizable(True, True)

        self.recognizer = DigitRecognizer()

        # 状态
        self.is_running = False
        self.auto_mode = tk.BooleanVar(value=False)
        self.interval = tk.DoubleVar(value=3.0)
        self.last_results = {}  # window_name -> text
        self.windows = []  # list of CaptchaWindow
        self.window_vars = {}  # index -> BooleanVar
        self.result_vars = {}  # index -> StringVar
        self.status_vars = {}  # index -> StringVar
        self.input_positions = {}  # index -> (x, y)

        self.config_file = 'captcha_config.json'
        self.load_config()

        self.build_ui()

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.input_positions = {int(k): v for k, v in cfg.get('input_positions', {}).items()}
        except Exception:
            pass

    def save_config(self):
        try:
            cfg = {
                'input_positions': {str(k): v for k, v in self.input_positions.items()},
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

    def build_ui(self):
        main = ttk.Frame(self.root, padding="8")
        main.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)

        ttk.Label(main, text="雷电模拟器验证码自动识别 - 手动窗口指定版",
                 font=('Microsoft YaHei', 15, 'bold')).grid(row=0, column=0, pady=(5, 8))

        # === 手动添加窗口区域 ===
        add_frame = ttk.LabelFrame(main, text="手动添加模拟器窗口", padding="8")
        add_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        add_frame.columnconfigure(5, weight=1)

        ttk.Label(add_frame, text="窗口名称:").grid(row=0, column=0, sticky=tk.W)
        self.name_var = tk.StringVar(value="模拟器1")
        ttk.Entry(add_frame, textvariable=self.name_var, width=15).grid(row=0, column=1, padx=3)

        ttk.Label(add_frame, text="窗口句柄 HWND:").grid(row=0, column=2, sticky=tk.W)
        self.hwnd_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.hwnd_var, width=12).grid(row=0, column=3, padx=3)

        ttk.Label(add_frame, text="左:").grid(row=0, column=4, sticky=tk.W)
        self.left_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.left_var, width=8).grid(row=0, column=5, padx=3)

        ttk.Label(add_frame, text="顶:").grid(row=1, column=0, sticky=tk.W)
        self.top_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.top_var, width=8).grid(row=1, column=1, padx=3)

        ttk.Label(add_frame, text="宽:").grid(row=1, column=2, sticky=tk.W)
        self.width_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.width_var, width=8).grid(row=1, column=3, padx=3)

        ttk.Label(add_frame, text="高:").grid(row=1, column=4, sticky=tk.W)
        self.height_var = tk.StringVar()
        ttk.Entry(add_frame, textvariable=self.height_var, width=8).grid(row=1, column=5, padx=3)

        ttk.Button(add_frame, text="添加窗口", command=self.add_window).grid(row=0, column=6, padx=5)
        ttk.Button(add_frame, text="删除选中", command=self.remove_selected).grid(row=1, column=6, padx=5)

        # === 批量操作按钮 ===
        row2 = ttk.Frame(main)
        row2.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        for i in range(8):
            row2.columnconfigure(i, weight=1)

        ttk.Button(row2, text="全选", command=self.select_all).grid(row=0, column=0, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="取消全选", command=self.deselect_all).grid(row=0, column=1, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="识别选中", command=self.recognize_selected).grid(row=0, column=2, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="自动填充选中", command=self.auto_fill_selected).grid(row=0, column=3, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="定位输入框", command=self.locate_input_positions).grid(row=0, column=4, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="激活窗口", command=self.activate_selected).grid(row=0, column=5, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="加载模板", command=self.load_templates).grid(row=0, column=6, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="保存配置", command=self.save_config_manual).grid(row=0, column=7, padx=2, sticky=(tk.W, tk.E))

        # === 窗口列表 ===
        list_frame = ttk.LabelFrame(main, text="模拟器窗口列表（双击选中/取消）", padding="8")
        list_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        columns = ('select', 'name', 'hwnd', 'pos', 'size', 'result', 'status', 'input_pos')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=14)

        self.tree.heading('select', text='选择')
        self.tree.heading('name', text='窗口名称')
        self.tree.heading('hwnd', text='窗口句柄 HWND')
        self.tree.heading('pos', text='位置')
        self.tree.heading('size', text='大小')
        self.tree.heading('result', text='识别结果')
        self.tree.heading('status', text='状态')
        self.tree.heading('input_pos', text='输入框位置')

        self.tree.column('select', width=55, anchor='center')
        self.tree.column('name', width=120)
        self.tree.column('hwnd', width=110, anchor='center')
        self.tree.column('pos', width=130)
        self.tree.column('size', width=110)
        self.tree.column('result', width=220)
        self.tree.column('status', width=160)
        self.tree.column('input_pos', width=120, anchor='center')

        vsb = ttk.Scrollbar(list_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        vsb.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.tree.bind('<Double-1>', self.on_tree_double_click)

        # === 自动模式 ===
        auto_frame = ttk.LabelFrame(main, text="自动模式", padding="8")
        auto_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        auto_frame.columnconfigure(6, weight=1)

        self.auto_chk = ttk.Checkbutton(auto_frame, text="启动自动识别/填充",
                                       variable=self.auto_mode, command=self.toggle_auto_mode)
        self.auto_chk.grid(row=0, column=0, sticky=tk.W, padx=(0, 15))

        ttk.Label(auto_frame, text="间隔(秒):").grid(row=0, column=1, sticky=tk.E)
        self.interval_spin = ttk.Spinbox(auto_frame, from_=1, to=300, increment=0.5,
                                        textvariable=self.interval, width=8)
        self.interval_spin.grid(row=0, column=2, sticky=tk.W, padx=(5, 20))

        self.auto_status = ttk.Label(auto_frame, text="就绪", foreground="green", font=('Microsoft YaHei', 10, 'bold'))
        self.auto_status.grid(row=0, column=3, sticky=tk.W)

        ttk.Button(auto_frame, text="测试单张图片", command=self.test_single_image).grid(row=0, column=4, padx=8)

        # === 日志 ===
        log_frame = ttk.LabelFrame(main, text="运行日志", padding="8")
        log_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=150, font=('Consolas', 10))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # === 手动输入 ===
        manual_frame = ttk.LabelFrame(main, text="手动输入验证码", padding="8")
        manual_frame.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        manual_frame.columnconfigure(1, weight=1)
        ttk.Label(manual_frame, text="验证码:").grid(row=0, column=0, sticky=tk.W)
        self.manual_var = tk.StringVar()
        ttk.Entry(manual_frame, textvariable=self.manual_var, font=('Consolas', 14), width=20).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 8), pady=3)
        ttk.Button(manual_frame, text="输入到选中第一个窗口", command=self.manual_input_selected).grid(row=0, column=2, padx=5)

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    # === 窗口管理 ===
    def add_window(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入窗口名称")
            return
        try:
            hwnd = int(self.hwnd_var.get()) if self.hwnd_var.get().strip() else 0
            left = int(self.left_var.get()) if self.left_var.get().strip() else 0
            top = int(self.top_var.get()) if self.top_var.get().strip() else 0
            width = int(self.width_var.get()) if self.width_var.get().strip() else 0
            height = int(self.height_var.get()) if self.height_var.get().strip() else 0
        except ValueError:
            messagebox.showerror("错误", "HWND 和坐标必须是数字")
            return

        win = CaptchaWindow(name, hwnd, left, top, width, height)
        self.windows.append(win)
        idx = len(self.windows) - 1
        self.window_vars[idx] = tk.BooleanVar(value=True)
        self.result_vars[idx] = tk.StringVar(value="")
        self.status_vars[idx] = tk.StringVar(value="待处理")
        self.update_tree()
        self.log(f"已添加窗口: {name} (HWND:{hwnd})")

    def remove_selected(self):
        selected = self.get_selected_indices()
        if not selected:
            messagebox.showwarning("提示", "请先勾选要删除的窗口")
            return
        for idx in sorted(selected, reverse=True):
            del self.windows[idx]
            # 重建索引映射
        self.rebuild_indices()
        self.log(f"已删除 {len(selected)} 个窗口")

    def rebuild_indices(self):
        """重建所有索引映射"""
        new_window_vars = {}
        new_result_vars = {}
        new_status_vars = {}
        new_input_positions = {}
        for new_idx, old_idx in enumerate(range(len(self.windows))):
            # 其实 self.windows 已经重新排列了，直接按新索引设置
            pass
        # 简单重建：按当前 self.windows 顺序
        self.window_vars = {i: tk.BooleanVar(value=True) for i in range(len(self.windows))}
        self.result_vars = {i: tk.StringVar(value="") for i in range(len(self.windows))}
        self.status_vars = {i: tk.StringVar(value="待处理") for i in range(len(self.windows))}
        self.input_positions = {i: self.input_positions.get(i) for i in range(len(self.windows))}
        self.update_tree()

    def get_selected_indices(self):
        return [i for i, v in self.window_vars.items() if v.get()]

    def select_all(self):
        for v in self.window_vars.values():
            v.set(True)
        self.update_tree()

    def deselect_all(self):
        for v in self.window_vars.values():
            v.set(False)
        self.update_tree()

    def update_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, win in enumerate(self.windows):
            chk = '☑' if self.window_vars.get(i, tk.BooleanVar(value=False)).get() else '☐'
            pos = f"({win.left}, {win.top})" if win.width > 0 else "未设置"
            size = f"{win.width}x{win.height}" if win.width > 0 else "未设置"
            ip = self.input_positions.get(i, "未设置")
            self.tree.insert('', tk.END, iid=str(i), values=(
                chk, win.name, win.hwnd, pos, size,
                self.result_vars.get(i, tk.StringVar()).get(),
                self.status_vars.get(i, tk.StringVar(value="待处理")).get(),
                ip
            ))

    def on_tree_double_click(self, event):
        item = self.tree.selection()
        if item:
            idx = int(item[0])
            self.window_vars[idx].set(not self.window_vars[idx].get())
            self.update_tree()

    # === 识别核心 ===
    def capture_window(self, idx):
        win = self.windows[idx]
        if win.hwnd and win.hwnd != 0:
            # 尝试通过 HWND 获取窗口矩形
            try:
                rect = ctypes.wintypes.RECT()
                if ctypes.windll.user32.GetWindowRect(win.hwnd, ctypes.byref(rect)):
                    left, top = rect.left, rect.top
                    width, height = rect.right - rect.left, rect.bottom - rect.top
                else:
                    left, top, width, height = win.left, win.top, win.width, win.height
            except Exception:
                left, top, width, height = win.left, win.top, win.width, win.height
        else:
            left, top, width, height = win.left, win.top, win.width, win.height

        if width <= 0 or height <= 0:
            return None, "窗口大小未设置"

        screen_w, screen_h = pyautogui.size()
        if left + width > screen_w:
            width = screen_w - left
        if top + height > screen_h:
            height = screen_h - top
        if width <= 0 or height <= 0:
            return None, "区域超出屏幕"

        try:
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            return screenshot, None
        except Exception as e:
            return None, str(e)

    def capture_and_recognize(self, idx):
        try:
            screenshot, err = self.capture_window(idx)
            if err:
                self.root.after(0, lambda: self.status_vars[idx].set(f"截图失败: {err}"))
                self.root.after(0, self.update_tree)
                return
            wdt, hgt = screenshot.size
            region = screenshot.crop((0, int(hgt*0.08), wdt, int(hgt*0.45)))
            text, info = self.recognizer.recognize(region)
            if text:
                self.last_results[idx] = text
                self.root.after(0, lambda: self.result_vars[idx].set(text))
                self.root.after(0, lambda: self.status_vars[idx].set("识别成功"))
                self.root.after(0, lambda: self.log(f"窗口{self.windows[idx].name} 识别成功: {text}"))
            else:
                self.root.after(0, lambda: self.status_vars[idx].set(f"识别失败: {info}"))
                self.root.after(0, lambda: self.log(f"窗口{self.windows[idx].name} 识别失败: {info}"))
            self.root.after(0, self.update_tree)
        except Exception as e:
            self.root.after(0, lambda: self.log(f"窗口{self.windows[idx].name} 异常: {e}"))
            self.root.after(0, lambda: self.status_vars[idx].set(f"异常: {e}"))
            self.root.after(0, self.update_tree)

    def recognize_selected(self):
        idxs = self.get_selected_indices()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        self.log(f"开始识别 {len(idxs)} 个选中窗口")
        for idx in idxs:
            self.root.after(0, lambda i=idx: self.status_vars[i].set("识别中..."))
            threading.Thread(target=self.capture_and_recognize, args=(idx,), daemon=True).start()

    # === 输入框位置定位 ===
    def locate_input_positions(self):
        idxs = self.get_selected_indices()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选要定位的窗口")
            return
        idx = idxs[0]
        win = self.windows[idx]
        screenshot, err = self.capture_window(idx)
        if err:
            messagebox.showerror("错误", f"截图失败: {err}")
            return
        self._open_picker(idx, win, screenshot)

    def _open_picker(self, idx, win, screenshot):
        picker = tk.Toplevel(self.root)
        picker.title(f"点击窗口 {win.name} 的验证码输入框位置")
        picker.attributes('-fullscreen', True)
        picker.attributes('-topmost', True)
        picker.configure(cursor='crosshair')
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        iw, ih = screenshot.size
        scale = min(sw/iw, sh/ih) * 0.9
        dw, dh = int(iw*scale), int(ih*scale)
        disp = screenshot.resize((dw, dh), Image.LANCZOS)
        photo = ImageTk.PhotoImage(disp)
        canvas = tk.Canvas(picker, width=dw, height=dh, cursor='crosshair')
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas.photo = photo
        result = {'pos': None}
        def on_click(ev):
            x = int(ev.x/scale)
            y = int(ev.y/scale)
            result['pos'] = (win.left + x, win.top + y)
            picker.destroy()
        canvas.bind('<Button-1>', on_click)
        picker.bind('<Escape>', lambda e: picker.destroy())
        self.root.wait_window(picker)
        if result['pos']:
            self.input_positions[idx] = list(result['pos'])
            self.log(f"窗口 {win.name} 输入框位置已记录: {result['pos']}")
            self.update_tree()
            self.save_config()

    # === 自动填充 ===
    def activate_selected(self):
        idxs = self.get_selected_indices()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        idx = idxs[0]
        win = self.windows[idx]
        if win.hwnd and win.hwnd != 0:
            try:
                if ctypes.windll.user32.IsIconic(win.hwnd):
                    ctypes.windll.user32.ShowWindow(win.hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(win.hwnd)
                self.log(f"已激活窗口 {win.name} (HWND:{win.hwnd})")
            except Exception as e:
                self.log(f"激活失败: {e}")
        else:
            messagebox.showwarning("提示", "该窗口未设置 HWND，无法激活")

    def auto_fill_selected(self):
        idxs = self.get_selected_indices()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        no_result = [i for i in idxs if i not in self.last_results or not self.last_results[i]]
        if no_result:
            names = "\n".join(f"窗口{self.windows[i].name}" for i in no_result[:6])
            messagebox.showwarning("提示", f"以下窗口无识别结果，请先识别：\n{names}")
            return
        ok = 0
        for idx in idxs:
            text = self.last_results[idx]
            win = self.windows[idx]
            pos = self.input_positions.get(idx)
            if pos:
                cx, cy = pos
            else:
                cx = win.left + win.width // 2
                cy = win.top + int(win.height * 0.72)
            try:
                switch_to_english_input()
                if win.hwnd and win.hwnd != 0:
                    activate_window(win.hwnd)
                pyautogui.click(cx, cy)
                time.sleep(0.15)
                pyautogui.write(text, interval=0.02)
                time.sleep(0.15)
                self.log(f"窗口 {win.name} 已填充: {text} 位置:({cx},{cy})")
                ok += 1
            except Exception as e:
                self.log(f"窗口 {win.name} 填充失败: {e}")
        messagebox.showinfo("完成", f"成功填充 {ok}/{len(idxs)} 个窗口")

    # === 自动模式 ===
    def toggle_auto_mode(self):
        if self.auto_mode.get():
            self.is_running = True
            threading.Thread(target=self.auto_loop, daemon=True).start()
            self.auto_status.config(text="运行中", foreground="green")
            self.log("自动模式已启动")
        else:
            self.is_running = False
            self.auto_status.config(text="就绪", foreground="green")
            self.log("自动模式已停止")

    def auto_loop(self):
        while self.is_running:
            try:
                idxs = self.get_selected_indices()
                if not idxs:
                    time.sleep(0.5)
                    continue
                self.log(f"自动循环处理 {len(idxs)} 个窗口")
                for idx in idxs:
                    if not self.is_running:
                        break
                    self.capture_and_recognize(idx)
                    time.sleep(0.4)
                    if idx in self.last_results and self.last_results[idx]:
                        text = self.last_results[idx]
                        pos = self.input_positions.get(idx)
                        win = self.windows[idx]
                        cx, cy = (pos if pos else (
                            win.left + win.width // 2,
                            win.top + int(win.height * 0.72)
                        ))
                        try:
                            switch_to_english_input()
                            if win.hwnd and win.hwnd != 0:
                                activate_window(win.hwnd)
                            pyautogui.click(cx, cy)
                            time.sleep(0.15)
                            pyautogui.write(text, interval=0.02)
                            self.log(f"自动填充窗口 {win.name}: {text}")
                        except Exception as e:
                            self.log(f"自动填充窗口 {win.name} 失败: {e}")
                time.sleep(max(1.0, self.interval.get()))
            except Exception as e:
                self.log(f"自动循环异常: {e}")
                time.sleep(2.0)

    # === 其他 ===
    def manual_input_selected(self):
        text = self.manual_var.get().strip()
        if not text:
            messagebox.showwarning("提示", "请输入验证码")
            return
        idxs = self.get_selected_indices()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选窗口")
            return
        idx = idxs[0]
        win = self.windows[idx]
        pos = self.input_positions.get(idx)
        cx, cy = (pos if pos else (
            win.left + win.width // 2,
            win.top + int(win.height * 0.72)
        ))
        try:
            switch_to_english_input()
            if win.hwnd and win.hwnd != 0:
                activate_window(win.hwnd)
            pyautogui.click(cx, cy)
            time.sleep(0.15)
            pyautogui.write(text)
            self.log(f"手动输入窗口 {win.name}: {text}")
        except Exception as e:
            self.log(f"手动输入失败: {e}")
            messagebox.showerror("错误", str(e))

    def clear_results(self):
        self.last_results.clear()
        for v in self.result_vars.values():
            v.set("")
        for v in self.status_vars.values():
            v.set("待处理")
        self.update_tree()
        self.log("结果已清空")

    def load_templates(self):
        d = filedialog.askdirectory(title="选择模板图片目录（需包含 0.png~9.png）")
        if d:
            ok = self.recognizer.load_custom_templates(d)
            self.log(f"模板加载: {'成功' if ok else '失败或目录无效'} {d}")

    def save_config_manual(self):
        self.save_config()
        messagebox.showinfo("提示", "配置已保存到 captcha_config.json")

    def test_single_image(self):
        f = filedialog.askopenfilename(title="选择验证码图片",
                                      filetypes=[("图片", "*.png *.jpg *.bmp *.jpeg")])
        if not f:
            return
        try:
            img = Image.open(f)
            text, info = self.recognizer.recognize(img)
            messagebox.showinfo("测试结果", f"{info}\n\n文件: {f}")
            self.log(f"测试图片 {f}: {info}")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.is_running = False
        self.auto_mode.set(False)
        self.save_config()
        self.root.destroy()


def switch_to_english_input():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ctypes.windll.user32.PostMessageW(hwnd, 0x0050, 0, 0x00000409)
    except Exception:
        pass


def activate_window(hwnd):
    try:
        if ctypes.windll.user32.IsIconic(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
    except Exception:
        pass


def main():
    root = tk.Tk()
    app = CaptchaRecognizerApp(root)
    app.run()


if __name__ == "__main__":
    main()

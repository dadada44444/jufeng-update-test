#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷电模拟器验证码自动识别 - 纯 Windows API 版 (支持子窗口枚举)
不依赖 pygetwindow，支持枚举父窗口下的子模拟器窗口
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

# ---------- Windows API ----------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

EnumWindows = user32.EnumWindows
EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
EnumWindows.restype = wintypes.BOOL

EnumChildWindows = user32.EnumChildWindows
EnumChildWindows.argtypes = [wintypes.HWND, ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
EnumChildWindows.restype = wintypes.BOOL

GetWindowRect = user32.GetWindowRect
GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
GetWindowRect.restype = wintypes.BOOL

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.argtypes = [wintypes.HWND]
IsWindowVisible.restype = wintypes.BOOL

IsIconic = user32.IsIconic
IsIconic.argtypes = [wintypes.HWND]
IsIconic.restype = wintypes.BOOL

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [wintypes.HWND]
SetForegroundWindow.restype = wintypes.BOOL

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
ShowWindow.restype = wintypes.BOOL

GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextLengthW.argtypes = [wintypes.HWND]
GetWindowTextLengthW.restype = wintypes.INT

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]
GetWindowTextW.restype = wintypes.INT

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

PostMessageW = user32.PostMessageW
PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
PostMessageW.restype = wintypes.BOOL

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
QueryFullProcessImageNameW.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

def switch_to_english_input():
    try:
        hwnd = user32.GetForegroundWindow()
        PostMessageW(hwnd, 0x0050, 0, 0x00000409)
    except Exception:
        pass

def activate_window(hwnd):
    try:
        if IsIconic(hwnd):
            ShowWindow(hwnd, 9)
        SetForegroundWindow(hwnd)
        time.sleep(0.1)
    except Exception:
        pass

def get_rect(hwnd):
    try:
        rect = RECT()
        if GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass
    return None

def get_title(hwnd):
    try:
        length = GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""

class WindowInfo:
    def __init__(self, hwnd, title, left, top, width, height, parent_hwnd=0):
        self.hwnd = hwnd
        self.title = title
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.parent_hwnd = parent_hwnd

class WindowEnumerator:
    def __init__(self):
        self.windows = []
        self.keywords = ['thunder', 'leidian', '雷电', 'ldplayer', 'android',
                         'emulator', 'adb', 'memu', 'nox', 'bluestacks', 'instagram']
        self.custom_titles = []
        self.ldplayer_path = ""
    
    def _check_window(self, hwnd, parent_hwnd=0):
        """检查单个窗口是否匹配"""
        try:
            if not IsWindowVisible(hwnd):
                return False
            if IsIconic(hwnd):
                return False
            title = get_title(hwnd)
            if not title:
                return False
            rect = get_rect(hwnd)
            if rect is None:
                return False
            left, top, width, height = rect
            if width <= 0 or height <= 0:
                return False
            title_lower = title.lower()
            matched = any(kw in title_lower for kw in self.keywords)
            if not matched and title in self.custom_titles:
                matched = True
            if self.ldplayer_path and not matched:
                pid = wintypes.DWORD()
                GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                hproc = OpenProcess(0x1000, False, pid.value)
                if hproc:
                    buf = ctypes.create_unicode_buffer(260)
                    size = wintypes.DWORD(260)
                    if QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                        exe_path = buf.value
                        if exe_path.lower().startswith(self.ldplayer_path.lower().rstrip('\\')):
                            matched = True
                    CloseHandle(hproc)
            if matched:
                self.windows.append(WindowInfo(hwnd, title, left, top, width, height, parent_hwnd))
            return True
        except Exception:
            return True
    
    def _enum_child_callback(self, hwnd, lParam):
        self._check_window(hwnd, lParam)
        return True
    
    def _enum_top_callback(self, hwnd, lParam):
        # 先检查顶级窗口本身
        self._check_window(hwnd, 0)
        # 然后枚举该顶级窗口的子窗口
        try:
            child_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(self._enum_child_callback)
            EnumChildWindows(hwnd, child_callback, hwnd)
        except Exception:
            pass
        return True
    
    def refresh(self):
        self.windows = []
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(self._enum_top_callback)
        EnumWindows(callback, 0)
        self.windows.sort(key=lambda w: w.hwnd)
        return self.windows


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


class CaptchaRecognizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("雷电验证码自动识别 - 支持子窗口枚举版")
        self.root.geometry("1300x850")
        self.root.resizable(True, True)
        
        self.enumerator = WindowEnumerator()
        self.recognizer = DigitRecognizer()
        
        self.is_running = False
        self.auto_mode = tk.BooleanVar(value=False)
        self.interval = tk.DoubleVar(value=3.0)
        self.last_results = {}
        self.window_vars = {}
        self.result_vars = {}
        self.status_vars = {}
        self.hwnd_order = []
        self.input_positions = {}
        
        self.config_file = 'captcha_config.json'
        self.load_config()
        
        self.build_ui()
        self.refresh()
    
    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.enumerator.keywords = cfg.get('keywords', self.enumerator.keywords)
                self.enumerator.custom_titles = cfg.get('custom_titles', [])
                self.enumerator.ldplayer_path = cfg.get('ldplayer_path', "")
                raw_pos = cfg.get('input_positions', {})
                self.input_positions = {int(k): v for k, v in raw_pos.items()}
        except Exception:
            pass
    
    def save_config(self):
        try:
            cfg = {
                'keywords': self.enumerator.keywords,
                'custom_titles': self.enumerator.custom_titles,
                'ldplayer_path': self.enumerator.ldplayer_path,
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
        main.rowconfigure(3, weight=1)
        
        ttk.Label(main, text="雷电模拟器验证码自动识别 - 支持子窗口枚举版",
                 font=('Microsoft YaHei', 15, 'bold')).grid(row=0, column=0, pady=(5, 8))
        
        row_ld = ttk.LabelFrame(main, text="雷电安装路径设置", padding="6")
        row_ld.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        row_ld.columnconfigure(1, weight=1)
        ttk.Label(row_ld, text="雷电路径:").grid(row=0, column=0, sticky=tk.W)
        self.ldpath_var = tk.StringVar(value=self.enumerator.ldplayer_path)
        ttk.Entry(row_ld, textvariable=self.ldpath_var, width=60).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 5))
        ttk.Button(row_ld, text="浏览", command=self.browse_ldpath).grid(row=0, column=2, padx=3)
        ttk.Button(row_ld, text="应用路径", command=self.apply_ldpath).grid(row=0, column=3, padx=3)
        
        row1 = ttk.Frame(main)
        row1.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        row1.columnconfigure(1, weight=1)
        ttk.Label(row1, text="窗口关键词:").grid(row=0, column=0, sticky=tk.W)
        self.keyword_var = tk.StringVar(value=",".join(self.enumerator.keywords))
        ttk.Entry(row1, textvariable=self.keyword_var, width=50).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 5))
        ttk.Button(row1, text="应用关键词", command=self.apply_keywords).grid(row=0, column=2, padx=3)
        ttk.Button(row1, text="刷新窗口", command=self.refresh).grid(row=0, column=3, padx=3)
        
        row2 = ttk.Frame(main)
        row2.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        for i in range(9):
            row2.columnconfigure(i, weight=1)
        ttk.Button(row2, text="全选", command=self.select_all).grid(row=0, column=0, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="取消全选", command=self.deselect_all).grid(row=0, column=1, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="识别选中", command=self.recognize_selected).grid(row=0, column=2, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="自动填充选中", command=self.auto_fill_selected).grid(row=0, column=3, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="定位输入框", command=self.locate_input_positions).grid(row=0, column=4, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="激活窗口", command=self.activate_selected).grid(row=0, column=5, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="加载模板", command=self.load_templates).grid(row=0, column=6, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="保存配置", command=self.save_config_manual).grid(row=0, column=7, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="清空结果", command=self.clear_results).grid(row=0, column=8, padx=2, sticky=(tk.W, tk.E))
        
        list_frame = ttk.LabelFrame(main, text="模拟器窗口列表（HWND 唯一标识，双击选中/取消）", padding="8")
        list_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        main.rowconfigure(4, weight=1)
        
        columns = ('select', 'hwnd', 'title', 'pos', 'size', 'result', 'status', 'input_pos')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=14)
        self.tree.heading('select', text='选择')
        self.tree.heading('hwnd', text='窗口句柄 HWND')
        self.tree.heading('title', text='窗口标题')
        self.tree.heading('pos', text='位置')
        self.tree.heading('size', text='大小')
        self.tree.heading('result', text='识别结果')
        self.tree.heading('status', text='状态')
        self.tree.heading('input_pos', text='输入框位置')
        self.tree.column('select', width=55, anchor='center')
        self.tree.column('hwnd', width=110, anchor='center')
        self.tree.column('title', width=260)
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
        
        auto_frame = ttk.LabelFrame(main, text="自动模式", padding="8")
        auto_frame.grid(row=5, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        auto_frame.columnconfigure(7, weight=1)
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
        
        log_frame = ttk.LabelFrame(main, text="运行日志", padding="8")
        log_frame.grid(row=6, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main.rowconfigure(6, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=170, font=('Consolas', 10))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        manual_frame = ttk.LabelFrame(main, text="手动输入验证码", padding="8")
        manual_frame.grid(row=7, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
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
    
    def browse_ldpath(self):
        d = filedialog.askdirectory(title="选择雷电安装目录")
        if d:
            self.ldpath_var.set(d)
    
    def apply_ldpath(self):
        path = self.ldpath_var.get().strip()
        self.enumerator.ldplayer_path = path
        self.log(f"雷电路径已设置: {path if path else '(未设置)'}")
        self.refresh()
        self.save_config()
    
    def apply_keywords(self):
        self.enumerator.keywords = [k.strip().lower() for k in self.keyword_var.get().split(',') if k.strip()]
        self.log(f"关键词已更新: {self.keyword_var.get()}")
        self.refresh()
    
    def refresh(self):
        wins = self.enumerator.refresh()
        prev_selected = {hwnd for hwnd, v in self.window_vars.items() if v.get()}
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.window_vars = {}
        self.result_vars = {}
        self.status_vars = {}
        self.hwnd_order = []
        for w in wins:
            hwnd = w.hwnd
            var = tk.BooleanVar(value=(hwnd in prev_selected))
            self.window_vars[hwnd] = var
            self.result_vars[hwnd] = tk.StringVar(value="")
            self.status_vars[hwnd] = tk.StringVar(value="待处理")
            self.hwnd_order.append(hwnd)
            pos = f"({w.left}, {w.top})"
            size = f"{w.width}x{w.height}"
            ip = self.input_positions.get(hwnd, "未设置")
            self.tree.insert('', tk.END, iid=str(hwnd), values=(
                '☑' if var.get() else '☐', hwnd, w.title, pos, size, '', '待处理', ip
            ))
        self.log(f"检测到 {len(wins)} 个模拟器窗口（含子窗口）")
        if not wins:
            messagebox.showinfo("提示", "未检测到任何模拟器窗口。\n请确保模拟器已启动且窗口可见。")
    
    def select_all(self):
        for v in self.window_vars.values():
            v.set(True)
        self.update_tree()
    
    def deselect_all(self):
        for v in self.window_vars.values():
            v.set(False)
        self.update_tree()
    
    def get_selected_hwnds(self):
        return [hwnd for hwnd, v in self.window_vars.items() if v.get()]
    
    def update_tree(self):
        for hwnd in self.hwnd_order:
            if not self.tree.exists(str(hwnd)):
                continue
            chk = '☑' if self.window_vars[hwnd].get() else '☐'
            w = None
            for win in self.enumerator.windows:
                if win.hwnd == hwnd:
                    w = win
                    break
            if w is None:
                continue
            ip = self.input_positions.get(hwnd, "未设置")
            self.tree.item(str(hwnd), values=(
                chk, hwnd, w.title,
                f"({w.left}, {w.top})", f"{w.width}x{w.height}",
                self.result_vars[hwnd].get(), self.status_vars[hwnd].get(), ip
            ))
    
    def on_tree_double_click(self, event):
        item = self.tree.selection()
        if item:
            hwnd = int(item[0])
            self.window_vars[hwnd].set(not self.window_vars[hwnd].get())
            self.update_tree()
    
    def capture_window(self, hwnd):
        for w in self.enumerator.windows:
            if w.hwnd == hwnd:
                left, top, width, height = w.left, w.top, w.width, w.height
                screen_w, screen_h = pyautogui.size()
                if left + width > screen_w:
                    width = screen_w - left
                if top + height > screen_h:
                    height = screen_h - top
                if width <= 0 or height <= 0:
                    return None, "窗口超出屏幕范围"
                screenshot = pyautogui.screenshot(region=(left, top, width, height))
                return screenshot, None
        return None, "句柄不在窗口列表中"
    
    def capture_and_recognize(self, hwnd):
        try:
            screenshot, err = self.capture_window(hwnd)
            if err:
                self.root.after(0, lambda: self.status_vars[hwnd].set(f"截图失败: {err}"))
                self.root.after(0, self.update_tree)
                return
            wdt, hgt = screenshot.size
            region = screenshot.crop((0, int(hgt*0.08), wdt, int(hgt*0.45)))
            text, info = self.recognizer.recognize(region)
            if text:
                self.last_results[hwnd] = text
                self.root.after(0, lambda: self.result_vars[hwnd].set(text))
                self.root.after(0, lambda: self.status_vars[hwnd].set("识别成功"))
                self.root.after(0, lambda: self.log(f"窗口HWND:{hwnd} 识别成功: {text}"))
            else:
                self.root.after(0, lambda: self.status_vars[hwnd].set(f"识别失败: {info}"))
                self.root.after(0, lambda: self.log(f"窗口HWND:{hwnd} 识别失败: {info}"))
            self.root.after(0, self.update_tree)
        except Exception as e:
            self.root.after(0, lambda: self.log(f"窗口HWND:{hwnd} 异常: {e}"))
            self.root.after(0, lambda: self.status_vars[hwnd].set(f"异常: {e}"))
            self.root.after(0, self.update_tree)
    
    def recognize_selected(self):
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        self.log(f"开始识别 {len(hwnds)} 个选中窗口")
        for hwnd in hwnds:
            self.root.after(0, lambda h=hwnd: self.status_vars[h].set("识别中..."))
            threading.Thread(target=self.capture_and_recognize, args=(hwnd,), daemon=True).start()
    
    def locate_input_positions(self):
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选要定位的窗口")
            return
        hwnd = hwnds[0]
        screenshot, err = self.capture_window(hwnd)
        if err:
            messagebox.showerror("错误", f"截图失败: {err}")
            return
        self._open_picker(hwnd, screenshot)
    
    def _open_picker(self, hwnd, screenshot):
        picker = tk.Toplevel(self.root)
        picker.title(f"点击窗口 HWND:{hwnd} 的验证码输入框位置")
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
            for w in self.enumerator.windows:
                if w.hwnd == hwnd:
                    result['pos'] = (w.left + x, w.top + y)
                    break
            picker.destroy()
        canvas.bind('<Button-1>', on_click)
        picker.bind('<Escape>', lambda e: picker.destroy())
        self.root.wait_window(picker)
        if result['pos']:
            self.input_positions[hwnd] = list(result['pos'])
            self.log(f"窗口 HWND:{hwnd} 输入框位置已记录: {result['pos']}")
            self.update_tree()
            self.save_config()
    
    def activate_selected(self):
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        hwnd = hwnds[0]
        try:
            if ctypes.windll.user32.IsIconic(hwnd):
                ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            self.log(f"已激活窗口 HWND:{hwnd}")
        except Exception as e:
            self.log(f"激活失败: {e}")
    
    def auto_fill_selected(self):
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        no_result = [h for h in hwnds if h not in self.last_results or not self.last_results[h]]
        if no_result:
            names = "\n".join(f"HWND:{h}" for h in no_result[:6])
            messagebox.showwarning("提示", f"以下窗口无识别结果，请先识别：\n{names}")
            return
        ok = 0
        for hwnd in hwnds:
            text = self.last_results[hwnd]
            pos = self.input_positions.get(hwnd)
            w = None
            for win in self.enumerator.windows:
                if win.hwnd == hwnd:
                    w = win
                    break
            if w is None:
                continue
            if pos:
                cx, cy = pos
            else:
                cx = w.left + w.width // 2
                cy = w.top + int(w.height * 0.72)
            try:
                switch_to_english_input()
                activate_window(w.hwnd)
                pyautogui.click(cx, cy)
                time.sleep(0.15)
                pyautogui.write(text, interval=0.02)
                time.sleep(0.15)
                self.log(f"窗口 HWND:{hwnd} 已填充: {text} 位置:({cx},{cy})")
                ok += 1
            except Exception as e:
                self.log(f"窗口 HWND:{hwnd} 填充失败: {e}")
        messagebox.showinfo("完成", f"成功填充 {ok}/{len(hwnds)} 个窗口")
    
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
                hwnds = self.get_selected_hwnds()
                if not hwnds:
                    time.sleep(0.5)
                    continue
                self.log(f"自动循环处理 {len(hwnds)} 个窗口")
                for hwnd in hwnds:
                    if not self.is_running:
                        break
                    self.capture_and_recognize(hwnd)
                    time.sleep(0.4)
                    if hwnd in self.last_results and self.last_results[hwnd]:
                        text = self.last_results[hwnd]
                        pos = self.input_positions.get(hwnd)
                        w = None
                        for win in self.enumerator.windows:
                            if win.hwnd == hwnd:
                                w = win
                                break
                        if w is None:
                            continue
                        cx, cy = (pos if pos else (w.left + w.width // 2, w.top + int(w.height * 0.72)))
                        try:
                            switch_to_english_input()
                            activate_window(w.hwnd)
                            pyautogui.click(cx, cy)
                            time.sleep(0.15)
                            pyautogui.write(text, interval=0.02)
                            self.log(f"自动填充窗口 HWND:{hwnd}: {text}")
                        except Exception as e:
                            self.log(f"自动填充窗口 HWND:{hwnd} 失败: {e}")
                time.sleep(max(1.0, self.interval.get()))
            except Exception as e:
                self.log(f"自动循环异常: {e}")
                time.sleep(2.0)
    
    def manual_input_selected(self):
        text = self.manual_var.get().strip()
        if not text:
            messagebox.showwarning("提示", "请输入验证码")
            return
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选窗口")
            return
        hwnd = hwnds[0]
        w = None
        for win in self.enumerator.windows:
            if win.hwnd == hwnd:
                w = win
                break
        if w is None:
            return
        pos = self.input_positions.get(hwnd)
        cx, cy = (pos if pos else (w.left + w.width // 2, w.top + int(w.height * 0.72)))
        try:
            switch_to_english_input()
            activate_window(w.hwnd)
            pyautogui.click(cx, cy)
            time.sleep(0.15)
            pyautogui.write(text)
            self.log(f"手动输入窗口 HWND:{hwnd}: {text}")
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


def main():
    root = tk.Tk()
    app = CaptchaRecognizerApp(root)
    app.run()


if __name__ == "__main__":
    main()

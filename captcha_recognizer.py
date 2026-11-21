#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷电模拟器验证码自动识别桌面软件 - 窗口句柄(HWND)增强最终版
Auto CAPTCHA Recognizer for Thunder (Leidian) Emulator - HWND Final

核心改进：
1. 每个窗口显示唯一 HWND 句柄 ID，不再仅依赖窗口标题
2. 使用 Windows API GetWindowRect 根据句柄获取精确窗口位置
3. 输入框位置按 HWND 记录，窗口顺序变化也不会搞错
4. 填充前可自动激活目标窗口（SetForegroundWindow）
5. 多种预处理管道 + 多字体模板 + 多尺度匹配（无需 Tesseract）
"""

import sys
import os
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from PIL import Image, ImageTk
import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
import ctypes
from ctypes import wintypes

# ---------- Windows API ---------- 
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

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

class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG)]

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


def switch_to_english_input():
    """尝试切换到英文输入法"""
    try:
        if os.name == 'nt':
            hwnd = user32.GetForegroundWindow()
            user32.PostMessageW(hwnd, 0x0050, 0, 0x00000409)
    except Exception:
        pass


def activate_window(hwnd):
    """激活并显示指定句柄的窗口"""
    try:
        if IsIconic(hwnd):
            ShowWindow(hwnd, 9)  # SW_SHOW
        SetForegroundWindow(hwnd)
        time.sleep(0.1)
    except Exception:
        pass


def get_rect_by_hwnd(hwnd):
    """根据窗口句柄获取精确矩形"""
    try:
        rect = RECT()
        if GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass
    return None


class DigitRecognizer:
    """
    改进的数字识别器（无需 Tesseract）
    - 多种字体模板（粗体、细体、不同大小）
    - 多种预处理管道（自动尝试最佳组合）
    - 改进字符分割（轮廓 + 投影法结合）
    - 多尺度模板匹配
    """

    def __init__(self):
        self.templates = {}
        self.debug = False
        self._build_multi_font_templates()

    def _build_multi_font_templates(self):
        """构建多种字体和大小的数字模板"""
        fonts = [
            (cv2.FONT_HERSHEY_SIMPLEX, 2.0, 3),
            (cv2.FONT_HERSHEY_SIMPLEX, 2.5, 4),
            (cv2.FONT_HERSHEY_TRIPLEX, 2.0, 3),
            (cv2.FONT_HERSHEY_DUPLEX, 2.0, 3),
            (cv2.FONT_HERSHEY_COMPLEX, 2.0, 3),
        ]
        sizes = [(60, 40), (80, 50), (100, 60)]

        for font, font_scale, thickness in fonts:
            for h, w in sizes:
                for digit in range(10):
                    img = np.ones((h, w), dtype=np.uint8) * 255
                    text = str(digit)
                    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
                    x = max(0, (w - tw) // 2)
                    y = min(h - 5, int(h * 0.8))
                    cv2.putText(img, text, (x, y), font, font_scale, 0, thickness, cv2.LINE_AA)
                    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
                    norm = cv2.resize(img, (50, 80))
                    if digit not in self.templates:
                        self.templates[digit] = []
                    self.templates[digit].append(norm)

    def load_custom_templates(self, template_dir):
        """从目录加载用户自定义模板（0.png~9.png）"""
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

    def preprocess_pipeline(self, image):
        """多种预处理管道，返回多组结果供后续选择最佳"""
        if isinstance(image, Image.Image):
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        else:
            img = image

        results = []

        # 管道1：放大 + CLAHE + 高斯 + 自适应高斯阈值
        for scale in [1.5, 2.0, 2.5]:
            h, w = img.shape[:2]
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, 15, 4
            )
            results.append(('adaptive_gauss', scale, thresh))

        # 管道2：放大 + OTSU阈值
        for scale in [1.5, 2.0, 2.5]:
            h, w = img.shape[:2]
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            results.append(('otsu', scale, thresh))

        # 管道3：中值滤波 + 自适应均值阈值
        for scale in [2.0]:
            h, w = img.shape[:2]
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            median = cv2.medianBlur(gray, 3)
            thresh = cv2.adaptiveThreshold(
                median, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY_INV, 11, 2
            )
            results.append(('adaptive_mean', scale, thresh))

        return results

    def segment_digits_contours(self, binary_img, min_width=8, min_height=15, max_width_ratio=0.5):
        """基于轮廓的字符分割"""
        contours, _ = cv2.findContours(
            binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        h, w = binary_img.shape
        regions = []
        for cnt in contours:
            x, y, rw, rh = cv2.boundingRect(cnt)
            if rw < min_width or rh < min_height:
                continue
            if rw > w * max_width_ratio:
                num_chars = max(1, round(rw / (w * 0.15)))
                char_w = rw // num_chars
                for i in range(num_chars):
                    cx = x + i * char_w
                    cw = char_w if i < num_chars - 1 else rw - i * char_w
                    regions.append((cx, y, cw, rh))
            else:
                regions.append((x, y, rw, rh))
        regions.sort(key=lambda r: r[0])
        return regions

    def segment_digits_projection(self, binary_img):
        """基于垂直投影的字符分割（处理连在一起的数字）"""
        h, w = binary_img.shape
        col_sum = np.sum(binary_img > 0, axis=0)
        in_char = col_sum > 0
        regions = []
        start = None
        for i, val in enumerate(in_char):
            if val and start is None:
                start = i
            elif not val and start is not None:
                end = i
                if end - start >= 5:
                    regions.append((start, 0, end - start, h))
                start = None
        if start is not None:
            regions.append((start, 0, w - start, h))
        return [(x, 0, wd, h) for x, y, wd, h in regions]

    def recognize_digit_multi(self, digit_roi):
        """对单个数字使用多模板、多尺度匹配"""
        if digit_roi.shape[0] < 15 or digit_roi.shape[1] < 8:
            return None, 0.0

        best_digit = None
        best_score = -1.0

        input_norm = cv2.resize(digit_roi, (50, 80))
        _, input_norm = cv2.threshold(input_norm, 127, 255, cv2.THRESH_BINARY_INV)

        for digit, template_list in self.templates.items():
            for template in template_list:
                result = cv2.matchTemplate(input_norm, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)

                input_inv = 255 - input_norm
                result2 = cv2.matchTemplate(input_inv, template, cv2.TM_CCOEFF_NORMED)
                _, max_val2, _, _ = cv2.minMaxLoc(result2)

                score = max(max_val, max_val2)
                if score > best_score:
                    best_score = score
                    best_digit = digit

        if best_digit is not None and best_score > 0.30:
            return str(best_digit), best_score
        return None, best_score

    def recognize(self, image):
        """
        主识别入口：尝试多种预处理 + 分割方法，返回最佳结果
        """
        pipelines = self.preprocess_pipeline(image)

        best_text = None
        best_info = ""
        best_score = -1.0

        for method_name, scale, binary in pipelines:
            regions = self.segment_digits_contours(binary)

            if len(regions) < 2:
                proj_regions = self.segment_digits_projection(binary)
                if len(proj_regions) > len(regions):
                    regions = proj_regions

            if not regions:
                continue

            regions.sort(key=lambda r: r[2] * r[3], reverse=True)
            regions = regions[:8]
            regions.sort(key=lambda r: r[0])

            result_digits = []
            total_conf = 0.0
            valid_count = 0

            for x, y, w, h in regions:
                pad = 4
                y1 = max(0, y - pad)
                y2 = min(binary.shape[0], y + h + pad)
                x1 = max(0, x - pad)
                x2 = min(binary.shape[1], x + w + pad)
                roi = binary[y1:y2, x1:x2]

                if roi.shape[0] < 12 or roi.shape[1] < 8:
                    continue

                digit, conf = self.recognize_digit_multi(roi)
                if digit:
                    result_digits.append(digit)
                    total_conf += conf
                    valid_count += 1

            if valid_count >= 3:
                text = ''.join(result_digits)
                avg_conf = total_conf / valid_count if valid_count else 0
                score = valid_count * avg_conf
                if score > best_score:
                    best_score = score
                    best_text = text
                    best_info = f"[{method_name}] 识别: {text} (字符: {valid_count}, 置信度: {avg_conf:.2f})"

        if best_text:
            return best_text, best_info
        return None, "所有预处理方案均未识别出有效验证码"


class ThunderWindowManager:
    """
    基于窗口句柄(HWND)的窗口管理器
    - 按 HWND 字典存储窗口，每个窗口唯一
    - 使用 Windows API 获取精确窗口位置
    """

    def __init__(self):
        self.windows = {}  # hwnd -> window_info
        self.default_keywords = [
            'thunder', 'leidian', '雷电', 'ldplayer', 'android',
            'emulator', 'adb', 'memu', 'nox', 'bluestacks', 'instagram'
        ]
        self.custom_titles = []

    def set_keywords(self, keywords_str):
        self.default_keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]

    def add_custom_title(self, title):
        if title and title not in self.custom_titles:
            self.custom_titles.append(title)

    def remove_custom_title(self, title):
        if title in self.custom_titles:
            self.custom_titles.remove(title)

    def refresh_windows(self):
        """刷新窗口列表，按 HWND 存储"""
        self.windows = {}
        seen_titles = set()

        try:
            all_windows = gw.getAllWindows()
            for w in all_windows:
                title = w.title
                if not title or title.strip() == '':
                    continue

                title_lower = title.lower()
                matched = any(kw in title_lower for kw in self.default_keywords)
                if not matched and title in self.custom_titles:
                    matched = True

                if matched and title not in seen_titles:
                    hwnd = w._hWnd if hasattr(w, '_hWnd') else None
                    if hwnd is None:
                        continue

                    # 使用 Windows API 获取精确位置
                    rect = get_rect_by_hwnd(hwnd)
                    if rect is None:
                        continue
                    left, top, width, height = rect

                    # 过滤最小化/隐藏窗口
                    if width <= 0 or height <= 0:
                        continue
                    if not IsWindowVisible(hwnd):
                        continue

                    self.windows[hwnd] = {
                        'hwnd': hwnd,
                        'title': title,
                        'left': left,
                        'top': top,
                        'width': width,
                        'height': height,
                    }
                    seen_titles.add(title)
        except Exception as e:
            print(f"刷新窗口失败: {e}")

        return self.windows

    def get_window_list(self):
        """返回按 HWND 排序的窗口列表"""
        return sorted(self.windows.values(), key=lambda x: x['hwnd'])

    def capture_window_by_hwnd(self, hwnd):
        """根据句柄捕获窗口截图"""
        if hwnd not in self.windows:
            return None, "句柄不在窗口列表中"

        win = self.windows[hwnd]
        left = max(0, win['left'])
        top = max(0, win['top'])
        width = max(1, win['width'])
        height = max(1, win['height'])

        # 限制在屏幕范围内
        screen_w, screen_h = pyautogui.size()
        if left + width > screen_w:
            width = screen_w - left
        if top + height > screen_h:
            height = screen_h - top

        if width <= 0 or height <= 0:
            return None, "窗口超出屏幕范围"

        try:
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            return screenshot, None
        except Exception as e:
            return None, str(e)

    def get_window_info(self, hwnd):
        if hwnd not in self.windows:
            return "无效窗口"
        win = self.windows[hwnd]
        return (f"HWND:{win['hwnd']} | {win['title']} | "
                f"({win['left']}, {win['top']}) {win['width']}x{win['height']}")


class CaptchaRecognizerApp:
    """
    主应用程序
    - 按 HWND 管理窗口，更准确
    - 输入框位置按 HWND 记录
    - 填充前可激活目标窗口
    """

    def __init__(self, root):
        self.root = root
        self.root.title("雷电模拟器验证码自动识别 - HWND 句柄增强版")
        self.root.geometry("1500x950")
        self.root.resizable(True, True)

        self.window_mgr = ThunderWindowManager()
        self.recognizer = DigitRecognizer()

        # 状态
        self.is_running = False
        self.auto_mode = tk.BooleanVar(value=False)
        self.interval = tk.DoubleVar(value=3.0)
        self.last_results = {}  # hwnd -> text
        self.hwnd_order = []    # 保持 UI 显示顺序
        self.window_vars = {}   # hwnd -> BooleanVar
        self.result_vars = {}   # hwnd -> StringVar
        self.status_vars = {}   # hwnd -> StringVar

        # 输入框位置按 HWND 记录
        self.input_positions = {}  # hwnd -> [x, y]

        # 配置文件
        self.config_file = 'captcha_config.json'
        self.load_config()

        self.setup_ui()
        self.refresh_windows()

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.window_mgr.default_keywords = cfg.get(
                    'keywords', self.window_mgr.default_keywords
                )
                self.window_mgr.custom_titles = cfg.get('custom_titles', [])
                raw_pos = cfg.get('input_positions', {})
                # 键是字符串，转为 int
                self.input_positions = {int(k): v for k, v in raw_pos.items()}
        except Exception:
            pass

    def save_config(self):
        try:
            cfg = {
                'keywords': self.window_mgr.default_keywords,
                'custom_titles': self.window_mgr.custom_titles,
                'input_positions': {str(k): v for k, v in self.input_positions.items()},
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

    def setup_ui(self):
        main = ttk.Frame(self.root, padding="8")
        main.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        ttk.Label(main, text="雷电模拟器验证码自动识别 - HWND 句柄增强版",
                 font=('Microsoft YaHei', 15, 'bold')).grid(row=0, column=0, pady=(5, 8))

        # === 第一行：关键词和刷新 ===
        row1 = ttk.Frame(main)
        row1.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        row1.columnconfigure(1, weight=1)

        ttk.Label(row1, text="窗口关键词:").grid(row=0, column=0, sticky=tk.W)
        self.keyword_var = tk.StringVar(value=",".join(self.window_mgr.default_keywords))
        ttk.Entry(row1, textvariable=self.keyword_var, width=50).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 5))
        ttk.Button(row1, text="应用关键词", command=self.apply_keywords).grid(
            row=0, column=2, padx=3)
        ttk.Button(row1, text="刷新窗口", command=self.refresh_windows).grid(
            row=0, column=3, padx=3)

        # === 第二行：批量操作 ===
        row2 = ttk.Frame(main)
        row2.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        for i in range(9):
            row2.columnconfigure(i, weight=1)

        ttk.Button(row2, text="全选", command=self.select_all).grid(row=0, column=0, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="取消全选", command=self.deselect_all).grid(row=0, column=1, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="识别选中", command=self.recognize_selected).grid(row=0, column=2, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="自动填充选中", command=self.auto_fill_selected).grid(row=0, column=3, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="定位输入框", command=self.locate_input_positions).grid(row=0, column=4, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="激活窗口", command=self.activate_selected).grid(row=0, column=5, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="加载模板", command=self.load_templates_dialog).grid(row=0, column=6, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="保存配置", command=self.save_config_manual).grid(row=0, column=7, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="清空结果", command=self.clear_results).grid(row=0, column=8, padx=2, sticky=(tk.W, tk.E))

        # === 第三行：窗口列表（带 HWND）===
        list_frame = ttk.LabelFrame(main, text="模拟器窗口列表（HWND 唯一标识，双击选中/取消）", padding="8")
        list_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

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

        # === 第四行：自动模式 ===
        auto_frame = ttk.LabelFrame(main, text="自动模式", padding="8")
        auto_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        auto_frame.columnconfigure(7, weight=1)

        self.auto_chk = ttk.Checkbutton(auto_frame, text="启动自动识别/填充",
                                       variable=self.auto_mode, command=self.toggle_auto_mode)
        self.auto_chk.grid(row=0, column=0, sticky=tk.W, padx=(0, 15))

        ttk.Label(auto_frame, text="间隔(秒):").grid(row=0, column=1, sticky=tk.E)
        self.interval_spin = ttk.Spinbox(auto_frame, from_=1, to=300, increment=0.5,
                                        textvariable=self.interval, width=8)
        self.interval_spin.grid(row=0, column=2, sticky=tk.W, padx=(5, 20))

        self.auto_status = ttk.Label(auto_frame, text="就绪",
                                    foreground="green", font=('Microsoft YaHei', 10, 'bold'))
        self.auto_status.grid(row=0, column=3, sticky=tk.W)

        ttk.Button(auto_frame, text="测试单张图片", command=self.test_single_image).grid(
            row=0, column=4, padx=8)

        # === 第五行：日志 ===
        log_frame = ttk.LabelFrame(main, text="运行日志", padding="8")
        log_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=170,
                                                 font=('Consolas', 10))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # === 第六行：手动输入 ===
        manual_frame = ttk.LabelFrame(main, text="手动输入验证码", padding="8")
        manual_frame.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        manual_frame.columnconfigure(1, weight=1)

        ttk.Label(manual_frame, text="验证码:").grid(row=0, column=0, sticky=tk.W)
        self.manual_var = tk.StringVar()
        ttk.Entry(manual_frame, textvariable=self.manual_var, font=('Consolas', 14), width=20).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 8), pady=3)
        ttk.Button(manual_frame, text="输入到选中第一个窗口",
                  command=self.manual_input_selected).grid(row=0, column=2, padx=5)

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    # ---------------- 窗口管理 ----------------
    def apply_keywords(self):
        self.window_mgr.set_keywords(self.keyword_var.get())
        self.log(f"关键词已更新: {self.keyword_var.get()}")
        self.refresh_windows()

    def refresh_windows(self):
        wins = self.window_mgr.refresh_windows()
        win_list = self.window_mgr.get_window_list()

        # 保留已选中的 hwnd 集合
        prev_selected = {hwnd for hwnd, v in self.window_vars.items() if v.get()}

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        self.window_vars = {}
        self.result_vars = {}
        self.status_vars = {}
        self.hwnd_order = []

        for w in win_list:
            hwnd = w['hwnd']
            var = tk.BooleanVar(value=(hwnd in prev_selected))
            self.window_vars[hwnd] = var
            self.result_vars[hwnd] = tk.StringVar(value="")
            self.status_vars[hwnd] = tk.StringVar(value="待处理")
            self.hwnd_order.append(hwnd)

            pos = f"({w['left']}, {w['top']})"
            size = f"{w['width']}x{w['height']}"
            ip = self.input_positions.get(hwnd, "未设置")

            self.tree.insert('', tk.END, iid=str(hwnd), values=(
                '☑' if var.get() else '☐',
                hwnd,
                w['title'],
                pos,
                size,
                '',
                '待处理',
                ip
            ))

        self.log(f"检测到 {len(win_list)} 个模拟器窗口 (按 HWND 管理)")
        if not win_list:
            messagebox.showinfo("提示",
                "未检测到任何模拟器窗口。\n"
                "请确认：\n"
                "1. 模拟器已启动且窗口可见（未最小化）\n"
                "2. 在上方关键词框中添加窗口标题包含的词（如：雷电, LDPlayer, instagram）\n"
                "3. 可点击“定位输入框”手动记录位置")

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
            w = self.window_mgr.windows[hwnd]
            ip = self.input_positions.get(hwnd, "未设置")
            self.tree.item(str(hwnd), values=(
                chk, hwnd, w['title'],
                f"({w['left']}, {w['top']})",
                f"{w['width']}x{w['height']}",
                self.result_vars[hwnd].get(),
                self.status_vars[hwnd].get(),
                ip
            ))

    def on_tree_double_click(self, event):
        item = self.tree.selection()
        if item:
            hwnd = int(item[0])
            self.window_vars[hwnd].set(not self.window_vars[hwnd].get())
            self.update_tree()

    # ---------------- 识别核心 ----------------
    def capture_and_recognize(self, hwnd):
        """单窗口捕获识别（按 HWND，线程安全）"""
        try:
            screenshot, err = self.window_mgr.capture_window_by_hwnd(hwnd)
            if err:
                self.root.after(0, lambda: self.status_vars[hwnd].set(f"截图失败: {err}"))
                self.root.after(0, self.update_tree)
                return

            w, h = screenshot.size
            region = screenshot.crop((0, int(h * 0.08), w, int(h * 0.45)))

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

    # ---------------- 输入框位置定位 ----------------
    def locate_input_positions(self):
        """可视化定位：选中窗口截图，用户点击输入框位置，按 HWND 记录"""
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选要定位的窗口")
            return

        # 只处理第一个选中的
        hwnd = hwnds[0]
        screenshot, err = self.window_mgr.capture_window_by_hwnd(hwnd)
        if err:
            messagebox.showerror("错误", f"截图失败: {err}")
            return

        self._open_position_picker(hwnd, screenshot)

    def _open_position_picker(self, hwnd, screenshot):
        """弹出全屏选择器，用户点击输入框位置"""
        picker = tk.Toplevel(self.root)
        picker.title(f"点击窗口 HWND:{hwnd} 的验证码输入框位置")
        picker.attributes('-fullscreen', True)
        picker.attributes('-topmost', True)
        picker.configure(cursor='crosshair')

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        img_w, img_h = screenshot.size
        scale = min(sw / img_w, sh / img_h) * 0.9
        disp_w, disp_h = int(img_w * scale), int(img_h * scale)
        disp = screenshot.resize((disp_w, disp_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(disp)

        canvas = tk.Canvas(picker, width=disp_w, height=disp_h, cursor='crosshair')
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas.photo = photo

        result = {'pos': None}

        def on_click(event):
            x = int(event.x / scale)
            y = int(event.y / scale)
            win = self.window_mgr.windows[hwnd]
            abs_x = win['left'] + x
            abs_y = win['top'] + y
            result['pos'] = (abs_x, abs_y)
            picker.destroy()

        canvas.bind('<Button-1>', on_click)
        picker.bind('<Escape>', lambda e: picker.destroy())

        self.root.wait_window(picker)

        if result['pos']:
            x, y = result['pos']
            self.input_positions[hwnd] = [x, y]
            self.log(f"窗口 HWND:{hwnd} 输入框位置已记录: ({x}, {y})")
            self.update_tree()
            self.save_config()

    # ---------------- 自动填充 ----------------
    def activate_selected(self):
        """激活选中的第一个窗口"""
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        hwnd = hwnds[0]
        activate_window(hwnd)
        self.log(f"已激活窗口 HWND:{hwnd}")

    def auto_fill_selected(self):
        hwnds = self.get_selected_hwnds()
        if not hwnds:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return

        no_result = [h for h in hwnds if h not in self.last_results or not self.last_results[h]]
        if no_result:
            names = "\n".join(f"HWND:{h}: {self.window_mgr.windows[h]['title']}" for h in no_result[:6])
            messagebox.showwarning("提示", f"以下窗口无识别结果，请先识别：\n{names}")
            return

        ok = 0
        for hwnd in hwnds:
            text = self.last_results[hwnd]
            pos = self.input_positions.get(hwnd)
            win = self.window_mgr.windows[hwnd]

            if pos:
                cx, cy = pos
            else:
                cx = win['left'] + win['width'] // 2
                cy = win['top'] + int(win['height'] * 0.72)

            try:
                switch_to_english_input()
                activate_window(win['hwnd'])  # 先激活目标窗口
                pyautogui.click(cx, cy)
                time.sleep(0.15)
                pyautogui.write(text, interval=0.02)
                time.sleep(0.15)
                self.log(f"窗口 HWND:{hwnd} 已填充: {text} 位置:({cx},{cy})")
                ok += 1
            except Exception as e:
                self.log(f"窗口 HWND:{hwnd} 填充失败: {e}")

        messagebox.showinfo("完成", f"成功填充 {ok}/{len(hwnds)} 个窗口")

    # ---------------- 自动模式 ----------------
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
                        win = self.window_mgr.windows[hwnd]
                        cx, cy = (pos if pos else (
                            win['left'] + win['width'] // 2,
                            win['top'] + int(win['height'] * 0.72)
                        ))
                        try:
                            switch_to_english_input()
                            activate_window(win['hwnd'])
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

    # ---------------- 其他 ----------------
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
        win = self.window_mgr.windows[hwnd]
        pos = self.input_positions.get(hwnd)
        cx, cy = (pos if pos else (
            win['left'] + win['width'] // 2,
            win['top'] + int(win['height'] * 0.72)
        ))
        try:
            switch_to_english_input()
            activate_window(win['hwnd'])
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

    def load_templates_dialog(self):
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

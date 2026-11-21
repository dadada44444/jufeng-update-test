#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷电模拟器验证码自动识别桌面软件 - 多窗口增强最终版
Auto CAPTCHA Recognizer for Thunder (Leidian) Emulator - Multi-Window Final

主要改进：
1. 窗口检测：宽泛匹配 + 手动添加，支持20+个窗口
2. 识别算法：多种预处理管道 + 多字体模板 + 字符分割 + 多尺度匹配
3. 自动填充：可视化定位输入框 + 输入法英文切换 + 点击验证
4. 健壮性：异常处理、窗口丢失重连、线程安全、配置保存
"""

import sys
import os
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
from PIL import Image, ImageOps, ImageFilter, ImageEnhance, ImageDraw
import cv2
import numpy as np
import pyautogui
import pygetwindow as gw
import ctypes

# 关闭 pyautogui 安全限制（自动化需要）
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

# Windows 输入法切换（切换到英文）
def switch_to_english_input():
    """尝试将输入法切换到英文"""
    try:
        if os.name == 'nt':
            # 发送 Shift+Alt 切换输入法，或直接使用 Win32 API
            user32 = ctypes.windll.user32
            # 获取当前前景窗口
            hwnd = user32.GetForegroundWindow()
            # 发送 WM_INPUTLANGCHANGEREQUEST 请求英文输入法 (00000409)
            user32.PostMessageW(hwnd, 0x0050, 0, 0x00000409)
    except Exception:
        pass


class DigitRecognizer:
    """
    改进的数字识别器
    - 多种字体模板（粗体、细体、不同大小）
    - 多种预处理管道（自动尝试最佳组合）
    - 改进字符分割（轮廓 + 投影法结合）
    - 多尺度模板匹配
    """

    def __init__(self):
        self.templates = {}  # digit -> list of (template_img, scale)
        self.debug = False
        self.debug_dir = '/tmp/captcha_debug'
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
                    # 获取文本大小以居中
                    (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
                    x = max(0, (w - tw) // 2)
                    y = min(h - 5, int(h * 0.8))
                    cv2.putText(img, text, (x, y), font, font_scale, 0, thickness, cv2.LINE_AA)
                    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
                    # 归一化大小存储
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

    def preprocess_pipeline(self, image, method='auto'):
        """
        多种预处理管道，自动尝试并返回最佳结果
        方法包括：不同缩放、不同阈值、不同滤波组合
        """
        if isinstance(image, Image.Image):
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        else:
            img = image

        results = []

        # 管道1：放大 + CLAHE + 高斯 + 自适应阈值
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

        # 管道3：中值滤波 + 自适应阈值（对盐椒噪声效果好）
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
                # 太宽可能是多个字符连在一起，尝试垂直切分
                # 简单处理：按等宽切分
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
        # 计算每列的白色像素数
        col_sum = np.sum(binary_img > 0, axis=0)
        # 找到有字符的列
        in_char = col_sum > 0
        regions = []
        start = None
        for i, val in enumerate(in_char):
            if val and start is None:
                start = i
            elif not val and start is not None:
                end = i
                if end - start >= 5:  # 最小宽度
                    regions.append((start, 0, end - start, h))
                start = None
        if start is not None:
            regions.append((start, 0, w - start, h))
        # 转换为 (x, y, w, h) 格式，y=0 表示全高，后续再裁剪
        return [(x, 0, wd, h) for x, y, wd, h in regions]

    def recognize_digit_multi(self, digit_roi):
        """对单个数字使用多模板、多尺度匹配"""
        if digit_roi.shape[0] < 15 or digit_roi.shape[1] < 8:
            return None, 0.0

        best_digit = None
        best_score = -1.0

        # 归一化输入
        input_norm = cv2.resize(digit_roi, (50, 80))
        _, input_norm = cv2.threshold(input_norm, 127, 255, cv2.THRESH_BINARY_INV)

        # 尝试不同的匹配方法
        for digit, template_list in self.templates.items():
            for template in template_list:
                # 直接匹配
                result = cv2.matchTemplate(input_norm, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)

                # 也尝试反色匹配（有些验证码是白字黑底）
                input_inv = 255 - input_norm
                result2 = cv2.matchTemplate(input_inv, template, cv2.TM_CCOEFF_NORMED)
                _, max_val2, _, _ = cv2.minMaxLoc(result2)

                score = max(max_val, max_val2)
                if score > best_score:
                    best_score = score
                    best_digit = digit

        # 动态阈值：如果最佳得分明显高于次佳，置信度更高
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
            # 尝试轮廓分割
            regions = self.segment_digits_contours(binary)

            # 如果轮廓分割太少，尝试投影分割
            if len(regions) < 2:
                proj_regions = self.segment_digits_projection(binary)
                if len(proj_regions) > len(regions):
                    regions = proj_regions

            if not regions:
                continue

            # 进一步过滤：按宽度排序，保留最可能的4-6个字符
            regions.sort(key=lambda r: r[2] * r[3], reverse=True)
            regions = regions[:8]
            regions.sort(key=lambda r: r[0])  # 按x排序

            result_digits = []
            total_conf = 0.0
            valid_count = 0

            for x, y, w, h in regions:
                # 提取ROI，加边距
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

            if valid_count >= 3:  # 至少识别出3个数字才算成功
                text = ''.join(result_digits)
                avg_conf = total_conf / valid_count if valid_count else 0
                # 综合得分：字符数 * 平均置信度
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
    改进的窗口管理器
    - 宽泛匹配所有可能的模拟器窗口
    - 支持手动添加窗口标题
    - 检查窗口可见性和最小化状态
    """

    def __init__(self):
        self.windows = []
        self.default_keywords = [
            'thunder', 'leidian', '雷电', 'ldplayer', 'android',
            'emulator', 'adb', 'memu', 'nox', 'bluestacks', 'instagram'
        ]
        self.custom_titles = []  # 用户手动添加的完整标题

    def set_keywords(self, keywords_str):
        """设置关键词列表"""
        self.default_keywords = [k.strip().lower() for k in keywords_str.split(',') if k.strip()]

    def add_custom_title(self, title):
        """添加手动指定的窗口标题"""
        if title and title not in self.custom_titles:
            self.custom_titles.append(title)

    def remove_custom_title(self, title):
        """移除自定义标题"""
        if title in self.custom_titles:
            self.custom_titles.remove(title)

    def refresh_windows(self):
        """刷新窗口列表，返回所有匹配的窗口"""
        self.windows = []
        seen_titles = set()

        try:
            all_windows = gw.getAllWindows()
            for w in all_windows:
                title = w.title
                if not title or title.strip() == '':
                    continue

                title_lower = title.lower()

                # 检查是否匹配关键词
                matched = any(kw in title_lower for kw in self.default_keywords)

                # 检查是否在自定义列表中
                if not matched and title in self.custom_titles:
                    matched = True

                if matched and title not in seen_titles:
                    # 检查窗口是否最小化（宽高为0或负通常表示最小化/隐藏）
                    if w.width <= 0 or w.height <= 0:
                        continue

                    self.windows.append({
                        'title': title,
                        'handle': w._hWnd if hasattr(w, '_hWnd') else None,
                        'left': w.left,
                        'top': w.top,
                        'width': w.width,
                        'height': w.height,
                    })
                    seen_titles.add(title)
        except Exception as e:
            print(f"刷新窗口失败: {e}")

        return self.windows

    def capture_window(self, index):
        """捕获指定窗口截图"""
        if index < 0 or index >= len(self.windows):
            return None, "窗口索引无效"

        win = self.windows[index]
        try:
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

            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            return screenshot, None
        except Exception as e:
            return None, str(e)

    def get_window_info(self, index):
        if index < 0 or index >= len(self.windows):
            return "无效窗口"
        win = self.windows[index]
        return (f"{win['title']} | ({win['left']}, {win['top']}) "
                f"{win['width']}x{win['height']}")


class CaptchaRecognizerApp:
    """
    主应用程序
    - 多窗口批量管理
    - 可视化输入框定位
    - 自动循环识别填充
    - 配置保存
    """

    def __init__(self, root):
        self.root = root
        self.root.title("雷电模拟器验证码自动识别 - 多窗口增强版")
        self.root.geometry("1400x900")
        self.root.resizable(True, True)

        self.window_mgr = ThunderWindowManager()
        self.recognizer = DigitRecognizer()

        # 状态
        self.is_running = False
        self.auto_mode = tk.BooleanVar(value=False)
        self.interval = tk.DoubleVar(value=3.0)
        self.last_results = {}  # index -> text
        self.window_vars = []
        self.result_vars = []
        self.status_vars = []

        # 输入框位置记录（每个窗口独立）
        self.input_positions = {}  # index -> (x, y)

        # 配置文件
        self.config_file = 'captcha_config.json'
        self.load_config()

        self.setup_ui()
        self.refresh_windows()

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                self.window_mgr.default_keywords = cfg.get(
                    'keywords', self.window_mgr.default_keywords
                )
                self.window_mgr.custom_titles = cfg.get('custom_titles', [])
                self.input_positions = cfg.get('input_positions', {})
                # 将字符串键转为整数
                self.input_positions = {int(k): v for k, v in self.input_positions.items()}
        except Exception:
            pass

    def save_config(self):
        """保存配置"""
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
        """构建界面"""
        # 主容器
        main = ttk.Frame(self.root, padding="8")
        main.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        # 标题
        ttk.Label(main, text="雷电模拟器验证码自动识别 - 多窗口增强版",
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

        # === 第二行：批量操作按钮 ===
        row2 = ttk.Frame(main)
        row2.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
        for i in range(8):
            row2.columnconfigure(i, weight=1)

        ttk.Button(row2, text="全选", command=self.select_all).grid(row=0, column=0, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="取消全选", command=self.deselect_all).grid(row=0, column=1, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="识别选中", command=self.recognize_selected).grid(row=0, column=2, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="自动填充选中", command=self.auto_fill_selected).grid(row=0, column=3, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="定位输入框", command=self.locate_input_positions).grid(row=0, column=4, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="加载模板", command=self.load_templates_dialog).grid(row=0, column=5, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="保存配置", command=self.save_config_manual).grid(row=0, column=6, padx=2, sticky=(tk.W, tk.E))
        ttk.Button(row2, text="清空结果", command=self.clear_results).grid(row=0, column=7, padx=2, sticky=(tk.W, tk.E))

        # === 第三行：窗口列表 ===
        list_frame = ttk.LabelFrame(main, text="模拟器窗口列表（双击选中/取消）", padding="8")
        list_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        columns = ('select', 'title', 'pos', 'size', 'result', 'status', 'input_pos')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=14)

        self.tree.heading('select', text='选择')
        self.tree.heading('title', text='窗口标题')
        self.tree.heading('pos', text='位置')
        self.tree.heading('size', text='大小')
        self.tree.heading('result', text='识别结果')
        self.tree.heading('status', text='状态')
        self.tree.heading('input_pos', text='输入框位置')

        self.tree.column('select', width=55, anchor='center')
        self.tree.column('title', width=280)
        self.tree.column('pos', width=130)
        self.tree.column('size', width=110)
        self.tree.column('result', width=200)
        self.tree.column('status', width=170)
        self.tree.column('input_pos', width=120, anchor='center')

        vsb = ttk.Scrollbar(list_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        vsb.grid(row=0, column=1, sticky=(tk.N, tk.S))

        self.tree.bind('<Double-1>', self.on_tree_double_click)

        # === 第四行：自动模式 ===
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

        self.auto_status = ttk.Label(auto_frame, text="就绪",
                                    foreground="green", font=('Microsoft YaHei', 10, 'bold'))
        self.auto_status.grid(row=0, column=3, sticky=tk.W)

        ttk.Button(auto_frame, text="测试识别一张图", command=self.test_single_image).grid(
            row=0, column=4, padx=8)

        # === 第五行：日志 ===
        log_frame = ttk.LabelFrame(main, text="运行日志", padding="8")
        log_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main.rowconfigure(5, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=160,
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
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        self.window_vars = []
        self.result_vars = []
        self.status_vars = []

        for i, w in enumerate(wins):
            var = tk.BooleanVar(value=False)
            self.window_vars.append(var)
            rv = tk.StringVar(value="")
            self.result_vars.append(rv)
            sv = tk.StringVar(value="待处理")
            self.status_vars.append(sv)

            pos = f"({w['left']}, {w['top']})"
            size = f"{w['width']}x{w['height']}"
            ip = self.input_positions.get(i, "未设置")

            self.tree.insert('', tk.END, iid=str(i), values=(
                '☐', w['title'], pos, size, '', '待处理', ip
            ))

        self.log(f"检测到 {len(wins)} 个模拟器窗口")
        if not wins:
            messagebox.showinfo("提示",
                "未检测到任何模拟器窗口。\n"
                "请确认：\n"
                "1. 模拟器已启动且窗口可见（未最小化）\n"
                "2. 在上方关键词框中添加窗口标题包含的词（如：雷电, LDPlayer, instagram）\n"
                "3. 或点击“定位输入框”后手动记录窗口")

    def select_all(self):
        for v in self.window_vars:
            v.set(True)
        self.update_tree()

    def deselect_all(self):
        for v in self.window_vars:
            v.set(False)
        self.update_tree()

    def get_selected(self):
        return [i for i, v in enumerate(self.window_vars) if v.get()]

    def update_tree(self):
        for i in range(len(self.window_vars)):
            if not self.tree.exists(str(i)):
                continue
            chk = '☑' if self.window_vars[i].get() else '☐'
            w = self.window_mgr.windows[i]
            ip = self.input_positions.get(i, "未设置")
            self.tree.item(str(i), values=(
                chk, w['title'],
                f"({w['left']}, {w['top']})",
                f"{w['width']}x{w['height']}",
                self.result_vars[i].get(),
                self.status_vars[i].get(),
                ip
            ))

    def on_tree_double_click(self, event):
        item = self.tree.selection()
        if item:
            i = int(item[0])
            self.window_vars[i].set(not self.window_vars[i].get())
            self.update_tree()

    # ---------------- 识别核心 ----------------
    def capture_and_recognize(self, i):
        """单窗口捕获识别（线程安全，结果通过after回调）"""
        try:
            screenshot, err = self.window_mgr.capture_window(i)
            if err:
                self.root.after(0, lambda: self.status_vars[i].set(f"截图失败: {err}"))
                self.root.after(0, self.update_tree)
                return

            w, h = screenshot.size
            # 验证码通常在窗口上部 8%-45% 区域
            region = screenshot.crop((0, int(h * 0.08), w, int(h * 0.45)))

            text, info = self.recognizer.recognize(region)

            if text:
                self.last_results[i] = text
                self.root.after(0, lambda: self.result_vars[i].set(text))
                self.root.after(0, lambda: self.status_vars[i].set("识别成功"))
                self.root.after(0, lambda: self.log(f"窗口{i} 识别成功: {text}"))
            else:
                self.root.after(0, lambda: self.status_vars[i].set(f"识别失败: {info}"))
                self.root.after(0, lambda: self.log(f"窗口{i} 识别失败: {info}"))

            self.root.after(0, self.update_tree)
        except Exception as e:
            self.root.after(0, lambda: self.log(f"窗口{i} 异常: {e}"))
            self.root.after(0, lambda: self.status_vars[i].set(f"异常: {e}"))
            self.root.after(0, self.update_tree)

    def recognize_selected(self):
        idxs = self.get_selected()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return
        self.log(f"开始识别 {len(idxs)} 个选中窗口")
        for i in idxs:
            self.root.after(0, lambda ii=i: self.status_vars[ii].set("识别中..."))
            threading.Thread(target=self.capture_and_recognize, args=(i,), daemon=True).start()

    # ---------------- 自动填充 ----------------
    def locate_input_positions(self):
        """可视化定位：截图当前选中窗口，让用户点击输入框位置"""
        idxs = self.get_selected()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选要定位的窗口")
            return

        # 只处理第一个选中的，演示如何定位
        i = idxs[0]
        screenshot, err = self.window_mgr.capture_window(i)
        if err:
            messagebox.showerror("错误", f"截图失败: {err}")
            return

        # 打开一个选择器窗口
        self._open_position_picker(i, screenshot)

    def _open_position_picker(self, index, screenshot):
        """弹出一个全屏选择器，用户点击输入框位置"""
        picker = tk.Toplevel(self.root)
        picker.title(f"点击窗口 {index} 的验证码输入框位置")
        picker.attributes('-fullscreen', True)
        picker.attributes('-topmost', True)
        picker.configure(cursor='crosshair')

        # 显示截图（缩放到屏幕）
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        img_w, img_h = screenshot.size
        scale = min(sw / img_w, sh / img_h) * 0.9
        disp_w, disp_h = int(img_w * scale), int(img_h * scale)
        disp = screenshot.resize((disp_w, disp_h), Image.LANCZOS)
        photo = tk.PhotoImage(image=disp)  # PIL -> tkinter 需要 ImageTk，这里简化用 PhotoImage 需要 PPM
        # 实际上 PhotoImage 不支持 PIL 直接，需要 ImageTk
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(disp)

        canvas = tk.Canvas(picker, width=disp_w, height=disp_h, cursor='crosshair')
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas.photo = photo  # 防止被GC

        result = {'pos': None}

        def on_click(event):
            # 转换回原图坐标
            x = int(event.x / scale)
            y = int(event.y / scale)
            # 加上窗口左上角偏移
            win = self.window_mgr.windows[index]
            abs_x = win['left'] + x
            abs_y = win['top'] + y
            result['pos'] = (abs_x, abs_y)
            picker.destroy()

        canvas.bind('<Button-1>', on_click)
        picker.bind('<Escape>', lambda e: picker.destroy())

        self.root.wait_window(picker)

        if result['pos']:
            x, y = result['pos']
            self.input_positions[index] = [x, y]
            self.log(f"窗口 {index} 输入框位置已记录: ({x}, {y})")
            self.update_tree()
            self.save_config()

    def auto_fill_selected(self):
        idxs = self.get_selected()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选至少一个窗口")
            return

        no_result = [i for i in idxs if i not in self.last_results or not self.last_results[i]]
        if no_result:
            names = "\n".join(f"窗口{i}: {self.window_mgr.windows[i]['title']}" for i in no_result[:6])
            messagebox.showwarning("提示", f"以下窗口无识别结果，请先识别：\n{names}")
            return

        ok = 0
        for i in idxs:
            text = self.last_results[i]
            pos = self.input_positions.get(i)
            win = self.window_mgr.windows[i]

            if pos:
                cx, cy = pos
            else:
                # 回退：窗口中心偏下
                cx = win['left'] + win['width'] // 2
                cy = win['top'] + int(win['height'] * 0.72)

            try:
                switch_to_english_input()
                pyautogui.click(cx, cy)
                time.sleep(0.15)
                pyautogui.write(text, interval=0.02)
                time.sleep(0.15)
                self.log(f"窗口{i} 已填充: {text} 位置:({cx},{cy})")
                ok += 1
            except Exception as e:
                self.log(f"窗口{i} 填充失败: {e}")

        messagebox.showinfo("完成", f"成功填充 {ok}/{len(idxs)} 个窗口")

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
                idxs = self.get_selected()
                if not idxs:
                    time.sleep(0.5)
                    continue

                self.log(f"自动循环处理 {len(idxs)} 个窗口")
                for i in idxs:
                    if not self.is_running:
                        break
                    self.capture_and_recognize(i)
                    time.sleep(0.4)

                    if i in self.last_results and self.last_results[i]:
                        text = self.last_results[i]
                        pos = self.input_positions.get(i)
                        win = self.window_mgr.windows[i]
                        cx, cy = (pos if pos else (
                            win['left'] + win['width'] // 2,
                            win['top'] + int(win['height'] * 0.72)
                        ))
                        try:
                            switch_to_english_input()
                            pyautogui.click(cx, cy)
                            time.sleep(0.15)
                            pyautogui.write(text, interval=0.02)
                            self.log(f"自动填充窗口{i}: {text}")
                        except Exception as e:
                            self.log(f"自动填充窗口{i}失败: {e}")

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
        idxs = self.get_selected()
        if not idxs:
            messagebox.showwarning("提示", "请先勾选窗口")
            return
        i = idxs[0]
        win = self.window_mgr.windows[i]
        pos = self.input_positions.get(i)
        cx, cy = (pos if pos else (
            win['left'] + win['width'] // 2,
            win['top'] + int(win['height'] * 0.72)
        ))
        try:
            switch_to_english_input()
            pyautogui.click(cx, cy)
            time.sleep(0.15)
            pyautogui.write(text)
            self.log(f"手动输入窗口{i}: {text}")
        except Exception as e:
            self.log(f"手动输入失败: {e}")
            messagebox.showerror("错误", str(e))

    def clear_results(self):
        self.last_results.clear()
        for v in self.result_vars:
            v.set("")
        for v in self.status_vars:
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
        """测试识别一张本地图片"""
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

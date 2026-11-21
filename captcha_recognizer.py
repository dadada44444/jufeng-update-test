#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷电模拟器验证码自动识别桌面软件 - 多窗口版本
Auto CAPTCHA Recognizer for Thunder (Leidian) Emulator - Multi-Window Version

支持同时识别多个模拟器窗口中的验证码，无需安装 Tesseract OCR
"""

import sys
import os
import threading
import time
import json
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import cv2
import numpy as np
import pyautogui
import pygetwindow as gw

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


class DigitRecognizer:
    """
    基于 OpenCV 模板匹配的数字识别器，不依赖 Tesseract
    通过将验证码图像分割为单个字符，与 0-9 的模板进行匹配
    """

    def __init__(self):
        self.templates = {}  # 存储 0-9 的模板图像
        self.debug = False
        self._build_default_templates()

    def _build_default_templates(self):
        """构建默认的数字模板（使用简单的字体渲染）"""
        # 使用 OpenCV 的 putText 创建简单的数字模板
        for digit in range(10):
            # 创建白色背景
            img = np.ones((60, 40), dtype=np.uint8) * 255
            # 绘制黑色数字
            cv2.putText(img, str(digit), (5, 50), cv2.FONT_HERSHEY_SIMPLEX,
                       1.8, 0, 3, cv2.LINE_AA)
            # 二值化
            _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
            self.templates[digit] = img

    def load_templates_from_dir(self, template_dir):
        """从目录加载自定义模板图像（文件名应为 0.png 到 9.png）"""
        if not os.path.exists(template_dir):
            return False
        for digit in range(10):
            path = os.path.join(template_dir, f"{digit}.png")
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY_INV)
                    self.templates[digit] = img
        return True

    def preprocess(self, image):
        """预处理验证码图像"""
        if isinstance(image, Image.Image):
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        else:
            img = image

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 高斯模糊去噪
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        # 自适应二值化
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )
        # 形态学闭运算，连接断开的笔画
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        return thresh

    def segment_digits(self, binary_img, min_width=8, min_height=15):
        """将二值化图像分割为单个数字字符区域"""
        contours, _ = cv2.findContours(
            binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        regions = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w >= min_width and h >= min_height:
                regions.append((x, y, w, h))

        # 按 x 坐标排序，从左到右
        regions.sort(key=lambda r: r[0])
        return regions

    def recognize_digit(self, digit_img):
        """对单个数字图像进行模板匹配识别"""
        best_digit = None
        best_score = -1

        # 调整输入图像大小以匹配模板
        input_resized = cv2.resize(digit_img, (40, 60))
        _, input_resized = cv2.threshold(
            input_resized, 127, 255, cv2.THRESH_BINARY_INV
        )

        for digit, template in self.templates.items():
            # 调整模板大小与输入一致
            tmpl_resized = cv2.resize(template, (40, 60))
            # 匹配
            result = cv2.matchTemplate(
                input_resized, tmpl_resized, cv2.TM_CCOEFF_NORMED
            )
            _, max_val, _, _ = cv2.minMaxLoc(result)

            if max_val > best_score:
                best_score = max_val
                best_digit = digit

        # 置信度阈值
        if best_score > 0.4:
            return str(best_digit), best_score
        return None, best_score

    def recognize(self, image):
        """识别验证码图像中的所有数字"""
        processed = self.preprocess(image)
        regions = self.segment_digits(processed)

        if not regions:
            return None, "未检测到数字字符"

        result_digits = []
        total_confidence = 0

        for x, y, w, h in regions:
            # 提取数字区域，添加少量边距
            pad = 3
            y1 = max(0, y - pad)
            y2 = min(processed.shape[0], y + h + pad)
            x1 = max(0, x - pad)
            x2 = min(processed.shape[1], x + w + pad)
            digit_roi = processed[y1:y2, x1:x2]

            digit, conf = self.recognize_digit(digit_roi)
            if digit:
                result_digits.append(digit)
                total_confidence += conf

        if result_digits:
            captcha_text = ''.join(result_digits)
            avg_conf = total_confidence / len(result_digits)
            return captcha_text, f"识别: {captcha_text} (置信度: {avg_conf:.2f})"
        else:
            return None, "无法识别任何数字"


class ThunderWindowManager:
    """管理多个雷电模拟器窗口"""

    def __init__(self):
        self.windows = []
        self.selected_indices = set()

    def refresh_windows(self):
        """刷新窗口列表，返回所有匹配的模拟器窗口"""
        self.windows = []
        try:
            all_windows = gw.getAllWindows()
            for w in all_windows:
                title = w.title.lower()
                # 匹配雷电模拟器、Android 模拟器、Instagram 等相关窗口
                if any(kw in title for kw in [
                    'thunder', 'leidian', '雷电', 'android', 'emulator',
                    'adb', 'memu', 'nox', 'bluestacks', 'instagram'
                ]) or 'instagram' in title:
                    self.windows.append({
                        'title': w.title,
                        'handle': w._hWnd if hasattr(w, '_hWnd') else None,
                        'left': w.left,
                        'top': w.top,
                        'width': w.width,
                        'height': w.height,
                    })
        except Exception as e:
            print(f"刷新窗口失败: {e}")
        return self.windows

    def capture_window(self, index):
        """捕获指定索引窗口的截图"""
        if index < 0 or index >= len(self.windows):
            return None, "窗口索引无效"

        win = self.windows[index]
        try:
            left = win['left']
            top = win['top']
            width = win['width']
            height = win['height']

            if width <= 0 or height <= 0:
                return None, "窗口大小无效"

            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            return screenshot, None
        except Exception as e:
            return None, str(e)

    def get_window_info(self, index):
        """获取窗口信息字符串"""
        if index < 0 or index >= len(self.windows):
            return "无效窗口"
        win = self.windows[index]
        return (f"{win['title']} | ({win['left']}, {win['top']}) "
                f"{win['width']}x{win['height']}")


class CaptchaRecognizerApp:
    """多窗口验证码自动识别桌面应用"""

    def __init__(self, root):
        self.root = root
        self.root.title("雷电模拟器验证码自动识别 - 多窗口版")
        self.root.geometry("1100x750")
        self.root.resizable(True, True)

        self.window_mgr = ThunderWindowManager()
        self.recognizer = DigitRecognizer()

        # 状态变量
        self.is_running = False
        self.auto_mode = tk.BooleanVar(value=False)
        self.interval = tk.DoubleVar(value=3.0)
        self.last_results = {}  # window_index -> last captcha text
        self.window_vars = []  # 每个窗口的复选框变量
        self.result_vars = []  # 每个窗口的结果变量
        self.status_vars = []  # 每个窗口的状态变量

        self.setup_ui()
        self.refresh_windows()

    def setup_ui(self):
        """构建用户界面"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # === 顶部控制区 ===
        top_frame = ttk.Frame(main_frame)
        top_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        top_frame.columnconfigure(1, weight=1)

        ttk.Button(top_frame, text="刷新窗口 / Refresh",
                  command=self.refresh_windows).grid(row=0, column=0, padx=(0, 10))

        ttk.Button(top_frame, text="全选 / Select All",
                  command=self.select_all).grid(row=0, column=1, padx=(0, 10))

        ttk.Button(top_frame, text="取消全选 / Deselect All",
                  command=self.deselect_all).grid(row=0, column=2, padx=(0, 10))

        ttk.Button(top_frame, text="识别选中 / Recognize Selected",
                  command=self.recognize_selected).grid(row=0, column=3, padx=(0, 10))

        ttk.Button(top_frame, text="自动填充选中 / Auto Fill Selected",
                  command=self.auto_fill_selected).grid(row=0, column=4)

        # === 窗口列表区 ===
        list_frame = ttk.LabelFrame(main_frame, text="模拟器窗口列表 / Emulator Windows", padding="10")
        list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # 创建 Treeview 显示窗口列表
        columns = ('select', 'title', 'pos', 'size', 'result', 'status')
        self.tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)

        self.tree.heading('select', text='选择')
        self.tree.heading('title', text='窗口标题')
        self.tree.heading('pos', text='位置')
        self.tree.heading('size', text='大小')
        self.tree.heading('result', text='识别结果')
        self.tree.heading('status', text='状态')

        self.tree.column('select', width=60, anchor='center')
        self.tree.column('title', width=250)
        self.tree.column('pos', width=120)
        self.tree.column('size', width=100)
        self.tree.column('result', width=150)
        self.tree.column('status', width=150)

        # 滚动条
        v_scroll = ttk.Scrollbar(list_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=v_scroll.set)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        v_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 双击选中/取消选中
        self.tree.bind('<Double-1>', self.on_tree_double_click)

        # === 自动模式区 ===
        auto_frame = ttk.LabelFrame(main_frame, text="自动模式 / Auto Mode", padding="10")
        auto_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Checkbutton(auto_frame, text="启动自动识别 / Enable Auto Recognition",
                       variable=self.auto_mode, command=self.toggle_auto_mode).grid(
                           row=0, column=0, sticky=tk.W, padx=(0, 20))

        ttk.Label(auto_frame, text="间隔(秒):").grid(row=0, column=1, sticky=tk.E)
        ttk.Spinbox(auto_frame, from_=1, to=60, increment=0.5,
                   textvariable=self.interval, width=8).grid(row=0, column=2, sticky=tk.W, padx=(5, 20))

        self.auto_status_label = ttk.Label(auto_frame, text="状态: 就绪 / Status: Ready", foreground="green")
        self.auto_status_label.grid(row=0, column=3, sticky=tk.W)

        # === 日志区 ===
        log_frame = ttk.LabelFrame(main_frame, text="日志 / Log", padding="10")
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, width=120)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    def log(self, message):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def refresh_windows(self):
        """刷新窗口列表"""
        windows = self.window_mgr.refresh_windows()

        # 清空现有项目
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.window_vars = []
        self.result_vars = []
        self.status_vars = []

        for i, win in enumerate(windows):
            var = tk.BooleanVar(value=False)
            self.window_vars.append(var)

            result_var = tk.StringVar(value="")
            self.result_vars.append(result_var)

            status_var = tk.StringVar(value="待处理 / Pending")
            self.status_vars.append(status_var)

            pos = f"({win['left']}, {win['top']})"
            size = f"{win['width']}x{win['height']}"

            self.tree.insert('', tk.END, iid=str(i), values=(
                '☐', win['title'], pos, size, '', '待处理 / Pending'
            ))

        self.log(f"找到 {len(windows)} 个模拟器窗口 / Found {len(windows)} emulator windows")

        if not windows:
            messagebox.showinfo("提示", "未找到模拟器窗口，请确保雷电模拟器正在运行")

    def select_all(self):
        """全选所有窗口"""
        for i in range(len(self.window_vars)):
            self.window_vars[i].set(True)
        self.update_tree_display()

    def deselect_all(self):
        """取消全选"""
        for i in range(len(self.window_vars)):
            self.window_vars[i].set(False)
        self.update_tree_display()

    def update_tree_display(self):
        """更新 Treeview 显示选中状态和结果"""
        for i in range(len(self.window_vars)):
            item_id = str(i)
            if not self.tree.exists(item_id):
                continue

            checked = '☑' if self.window_vars[i].get() else '☐'
            result = self.result_vars[i].get()
            status = self.status_vars[i].get()

            self.tree.item(item_id, values=(
                checked,
                self.window_mgr.windows[i]['title'],
                f"({self.window_mgr.windows[i]['left']}, {self.window_mgr.windows[i]['top']})",
                f"{self.window_mgr.windows[i]['width']}x{self.window_mgr.windows[i]['height']}",
                result,
                status
            ))

    def on_tree_double_click(self, event):
        """双击切换选中状态"""
        item = self.tree.selection()
        if item:
            idx = int(item[0])
            self.window_vars[idx].set(not self.window_vars[idx].get())
            self.update_tree_display()

    def get_selected_indices(self):
        """获取所有选中的窗口索引"""
        return [i for i, var in enumerate(self.window_vars) if var.get()]

    def capture_and_recognize(self, index):
        """捕获并识别单个窗口的验证码"""
        screenshot, error = self.window_mgr.capture_window(index)
        if error:
            self.log(f"窗口 {index} 捕获失败: {error}")
            self.root.after(0, lambda i=index: self.status_vars[i].set(f"捕获失败: {error}"))
            return

        # 裁剪验证码区域（窗口上半部分）
        w, h = screenshot.size
        captcha_region = screenshot.crop((0, int(h * 0.1), w, int(h * 0.5)))

        text, info = self.recognizer.recognize(captcha_region)

        if text:
            self.last_results[index] = text
            self.root.after(0, lambda i=index, t=text: self.result_vars[i].set(t))
            self.root.after(0, lambda i=index: self.status_vars[i].set("识别成功 / Recognized"))
            self.root.after(0, lambda t=text: self.log(f"窗口 {index} 识别成功: {t}"))
        else:
            self.root.after(0, lambda i=index: self.status_vars[i].set(f"识别失败: {info}"))
            self.root.after(0, lambda i=info: self.log(f"窗口 {index} 识别失败: {i}"))

        self.root.after(0, self.update_tree_display)

    def recognize_selected(self):
        """识别所有选中窗口的验证码"""
        indices = self.get_selected_indices()
        if not indices:
            messagebox.showwarning("警告", "请先选择至少一个窗口 / Please select at least one window")
            return

        self.log(f"开始识别 {len(indices)} 个选中窗口")

        for idx in indices:
            self.root.after(0, lambda i=idx: self.status_vars[i].set("识别中..."))
            threading.Thread(target=self.capture_and_recognize, args=(idx,), daemon=True).start()

    def auto_fill_selected(self):
        """自动填充所有选中窗口的验证码"""
        indices = self.get_selected_indices()
        if not indices:
            messagebox.showwarning("警告", "请先选择至少一个窗口 / Please select at least one window")
            return

        # 检查是否有识别结果
        no_result = [i for i in indices if i not in self.last_results or not self.last_results[i]]
        if no_result:
            messagebox.showwarning("警告", "以下窗口尚无识别结果，请先识别 / Please recognize first:\n" +
                                  "\n".join(f"窗口 {i}" for i in no_result[:5]))
            return

        for idx in indices:
            text = self.last_results[idx]
            win = self.window_mgr.windows[idx]
            try:
                click_x = win['left'] + win['width'] // 2
                click_y = win['top'] + int(win['height'] * 0.65)

                pyautogui.click(click_x, click_y)
                time.sleep(0.2)
                pyautogui.write(text)
                time.sleep(0.2)

                self.log(f"窗口 {idx} 已填充验证码: {text}")
            except Exception as e:
                self.log(f"窗口 {idx} 自动填充失败: {e}")

        messagebox.showinfo("完成", f"已填充 {len(indices)} 个窗口的验证码")

    def toggle_auto_mode(self):
        """切换自动模式"""
        if self.auto_mode.get():
            self.is_running = True
            threading.Thread(target=self.auto_loop, daemon=True).start()
            self.auto_status_label.config(text="状态: 自动模式运行中 / Status: Auto mode running", foreground="green")
            self.log("自动模式已启动")
        else:
            self.is_running = False
            self.auto_status_label.config(text="状态: 就绪 / Status: Ready", foreground="green")
            self.log("自动模式已停止")

    def auto_loop(self):
        """自动识别循环"""
        while self.is_running:
            try:
                indices = self.get_selected_indices()
                if indices:
                    self.log(f"自动循环: 处理 {len(indices)} 个选中窗口")
                    for idx in indices:
                        if not self.is_running:
                            break
                        self.capture_and_recognize(idx)
                        time.sleep(0.5)  # 每个窗口之间稍微延迟

                        # 自动填充如果有结果
                        if idx in self.last_results and self.last_results[idx]:
                            text = self.last_results[idx]
                            win = self.window_mgr.windows[idx]
                            try:
                                click_x = win['left'] + win['width'] // 2
                                click_y = win['top'] + int(win['height'] * 0.65)
                                pyautogui.click(click_x, click_y)
                                time.sleep(0.2)
                                pyautogui.write(text)
                                self.log(f"自动填充窗口 {idx}: {text}")
                            except Exception as e:
                                self.log(f"自动填充窗口 {idx} 失败: {e}")

                time.sleep(self.interval.get())
            except Exception as e:
                self.log(f"自动循环错误: {e}")
                time.sleep(self.interval.get())

    def run(self):
        """运行应用"""
        self.root.mainloop()


def main():
    root = tk.Tk()
    app = CaptchaRecognizerApp(root)
    app.run()


if __name__ == "__main__":
    main()

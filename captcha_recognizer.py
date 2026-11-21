#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷电模拟器验证码自动识别桌面软件
Auto CAPTCHA Recognizer for Thunder (Leidian) Emulator
"""

import sys
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import cv2
import numpy as np
import pyautogui
import pygetwindow as gw

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1


class CaptchaProcessor:
    """Handles CAPTCHA image processing and digit recognition."""
    
    def __init__(self):
        self.debug = False
        self.use_tesseract = HAS_TESSERACT
    
    def preprocess_image(self, image):
        """Preprocess CAPTCHA image for better OCR results."""
        if isinstance(image, Image.Image):
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        else:
            img = image
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 11, 2
        )
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        result = Image.fromarray(255 - thresh)
        
        if self.debug:
            result.save('/tmp/captcha_preprocessed.png')
        
        return result
    
    def recognize_tesseract(self, image):
        """Recognize CAPTCHA using Tesseract OCR."""
        if not HAS_TESSERACT:
            return None, "Tesseract not available"
        try:
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789'
            text = pytesseract.image_to_string(image, config=custom_config)
            digits = ''.join(c for c in text if c.isdigit())
            return digits if digits else None, text.strip()
        except Exception as e:
            return None, str(e)
    
    def recognize_template(self, image):
        """Template-based digit recognition (fallback)."""
        return None, "Template recognition not implemented"
    
    def recognize(self, image):
        """Main recognition method."""
        processed = self.preprocess_image(image)
        
        if self.use_tesseract and HAS_TESSERACT:
            text, info = self.recognize_tesseract(processed)
            if text and len(text) >= 4:
                return text, f"Tesseract: {text}"
        
        text, info = self.recognize_template(processed)
        if text:
            return text, info
        
        if self.use_tesseract and HAS_TESSERACT:
            text, info = self.recognize_tesseract(processed)
            if text:
                return text, f"Tesseract (partial): {text}"
        
        return None, f"Recognition failed: {info}"


class ThunderWindowManager:
    """Manages Thunder emulator window detection and interaction."""
    
    def __init__(self):
        self.windows = []
        self.selected_window = None
    
    def refresh_windows(self):
        """Refresh list of available Thunder emulator windows."""
        self.windows = []
        try:
            all_windows = gw.getAllWindows()
            for w in all_windows:
                title = w.title.lower()
                if any(keyword in title for keyword in [
                    'thunder', 'leidian', '雷电', 'android', 'emulator',
                    'adb', 'memu', 'nox', 'bluestacks'
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
            print(f"Error refreshing windows: {e}")
        return self.windows
    
    def select_window(self, index):
        """Select a window by index."""
        if 0 <= index < len(self.windows):
            self.selected_window = self.windows[index]
            return self.selected_window
        return None
    
    def capture_window(self, window_info=None):
        """Capture screenshot of the selected window."""
        if window_info is None:
            window_info = self.selected_window
        if window_info is None:
            return None, "No window selected"
        try:
            left = window_info['left']
            top = window_info['top']
            width = window_info['width']
            height = window_info['height']
            screenshot = pyautogui.screenshot(region=(left, top, width, height))
            return screenshot, None
        except Exception as e:
            return None, str(e)
    
    def get_window_center(self, window_info=None):
        """Get center coordinates of window."""
        if window_info is None:
            window_info = self.selected_window
        if window_info is None:
            return None
        center_x = window_info['left'] + window_info['width'] // 2
        center_y = window_info['top'] + window_info['height'] // 2
        return (center_x, center_y)


class CaptchaRecognizerApp:
    """Main desktop application for CAPTCHA recognition."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("雷电模拟器验证码自动识别 - CAPTCHA Auto Recognizer")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        
        self.window_mgr = ThunderWindowManager()
        self.processor = CaptchaProcessor()
        
        self.is_running = False
        self.recognition_thread = None
        self.auto_mode = tk.BooleanVar(value=False)
        self.interval = tk.DoubleVar(value=3.0)
        self.last_captcha = ""
        
        self.setup_ui()
        self.refresh_windows()
    
    def setup_ui(self):
        """Setup the user interface."""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # === Window Selection Section ===
        win_frame = ttk.LabelFrame(main_frame, text="模拟器窗口选择 / Emulator Window Selection", padding="10")
        win_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        win_frame.columnconfigure(1, weight=1)
        
        ttk.Label(win_frame, text="选择窗口:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        
        self.window_combo = ttk.Combobox(win_frame, state="readonly", width=60)
        self.window_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        self.window_combo.bind('<<ComboboxSelected>>', self.on_window_selected)
        
        ttk.Button(win_frame, text="刷新 / Refresh", command=self.refresh_windows).grid(row=0, column=2)
        
        self.window_info_label = ttk.Label(win_frame, text="未选择窗口 / No window selected")
        self.window_info_label.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(5, 0))
        
        # === Capture Section ===
        cap_frame = ttk.LabelFrame(main_frame, text="验证码捕获 / CAPTCHA Capture", padding="10")
        cap_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        cap_frame.columnconfigure(1, weight=1)
        
        ttk.Button(cap_frame, text="捕获当前窗口 / Capture Window",
                  command=self.capture_current).grid(row=0, column=0, padx=(0, 5))
        
        ttk.Button(cap_frame, text="识别验证码 / Recognize CAPTCHA",
                  command=self.recognize_current).grid(row=0, column=1, padx=(0, 5))
        
        ttk.Button(cap_frame, text="自动填充 / Auto Fill",
                  command=self.auto_fill).grid(row=0, column=2)
        
        # === Recognition Result Section ===
        res_frame = ttk.LabelFrame(main_frame, text="识别结果 / Recognition Result", padding="10")
        res_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        res_frame.columnconfigure(1, weight=1)
        
        ttk.Label(res_frame, text="识别出的验证码:").grid(row=0, column=0, sticky=tk.W)
        
        self.result_var = tk.StringVar()
        self.result_entry = ttk.Entry(res_frame, textvariable=self.result_var, font=('Consolas', 14, 'bold'))
        self.result_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0), pady=(0, 5))
        
        ttk.Label(res_frame, text="详细信息:").grid(row=1, column=0, sticky=tk.W)
        self.info_text = scrolledtext.ScrolledText(res_frame, height=4, width=70)
        self.info_text.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(5, 0), pady=(0, 5))
        
        # === Auto Mode Section ===
        auto_frame = ttk.LabelFrame(main_frame, text="自动模式 / Auto Mode", padding="10")
        auto_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        auto_frame.columnconfigure(1, weight=1)
        
        ttk.Checkbutton(auto_frame, text="启动自动识别 / Enable Auto Recognition",
                       variable=self.auto_mode, command=self.toggle_auto_mode).grid(row=0, column=0, sticky=tk.W)
        
        ttk.Label(auto_frame, text="间隔(秒):").grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        ttk.Spinbox(auto_frame, from_=1, to=60, increment=0.5, textvariable=self.interval, width=10).grid(row=1, column=1, sticky=tk.W, padx=(5, 0), pady=(5, 0))
        
        self.status_label = ttk.Label(auto_frame, text="状态: 就绪 / Status: Ready", foreground="green")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))
        
        # === Log Section ===
        log_frame = ttk.LabelFrame(main_frame, text="日志 / Log", padding="10")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=80)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # === Manual Input Section ===
        manual_frame = ttk.LabelFrame(main_frame, text="手动输入 / Manual Input", padding="10")
        manual_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        manual_frame.columnconfigure(1, weight=1)
        
        ttk.Label(manual_frame, text="验证码:").grid(row=0, column=0, sticky=tk.W)
        
        self.manual_var = tk.StringVar()
        ttk.Entry(manual_frame, textvariable=self.manual_var, font=('Consolas', 14)).grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0), pady=(0, 5))
        
        ttk.Button(manual_frame, text="输入到窗口 / Input to Window",
                  command=self.manual_input).grid(row=0, column=2, padx=(5, 0))
    
    def log(self, message):
        """Add message to log."""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def refresh_windows(self):
        """Refresh window list."""
        windows = self.window_mgr.refresh_windows()
        titles = [w['title'] for w in windows]
        self.window_combo['values'] = titles
        
        if titles:
            self.window_combo.current(0)
            self.on_window_selected(None)
        else:
            self.window_combo.set('')
            self.window_info_label.config(text="未找到模拟器窗口 / No emulator windows found")
            self.log("未找到模拟器窗口，请确保雷电模拟器正在运行 / No emulator windows found")
    
    def on_window_selected(self, event):
        """Handle window selection change."""
        index = self.window_combo.current()
        if index >= 0:
            win = self.window_mgr.select_window(index)
            self.window_info_label.config(
                text=f"标题: {win['title']} | 位置: ({win['left']}, {win['top']}) | 大小: {win['width']}x{win['height']}"
            )
            self.log(f"已选择窗口: {win['title']}")
    
    def capture_current(self):
        """Capture screenshot of selected window."""
        screenshot, error = self.window_mgr.capture_window()
        if error:
            messagebox.showerror("错误", f"捕获失败: {error}")
            self.log(f"捕获失败: {error}")
            return None
        
        self.current_screenshot = screenshot
        self.log("已捕获窗口截图")
        return screenshot
    
    def recognize_current(self):
        """Recognize CAPTCHA from current screenshot."""
        if not hasattr(self, 'current_screenshot') or self.current_screenshot is None:
            self.capture_current()
        
        if not hasattr(self, 'current_screenshot') or self.current_screenshot is None:
            messagebox.showwarning("警告", "请先捕获窗口截图 / Please capture window first")
            return
        
        screenshot = self.current_screenshot
        w, h = screenshot.size
        captcha_region = screenshot.crop((0, int(h * 0.1), w, int(h * 0.5)))
        
        text, info = self.processor.recognize(captcha_region)
        
        if text:
            self.result_var.set(text)
            self.last_captcha = text
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, info)
            self.log(f"识别成功: {text}")
            messagebox.showinfo("识别成功", f"验证码: {text}")
        else:
            self.info_text.delete(1.0, tk.END)
            self.info_text.insert(tk.END, info)
            self.log(f"识别失败: {info}")
            messagebox.showwarning("识别失败", f"无法识别验证码: {info}")
    
    def auto_fill(self):
        """Auto fill recognized CAPTCHA into the input field."""
        text = self.result_var.get()
        if not text:
            messagebox.showwarning("警告", "没有可填充的验证码 / No CAPTCHA to fill")
            return
        
        if self.window_mgr.selected_window is None:
            messagebox.showwarning("警告", "请先选择模拟器窗口 / Please select emulator window first")
            return
        
        try:
            win = self.window_mgr.selected_window
            click_x = win['left'] + win['width'] // 2
            click_y = win['top'] + int(win['height'] * 0.65)
            
            pyautogui.click(click_x, click_y)
            time.sleep(0.3)
            pyautogui.write(text)
            time.sleep(0.3)
            
            self.log(f"已自动填充验证码: {text}")
            messagebox.showinfo("成功", f"已填充验证码: {text}")
        except Exception as e:
            self.log(f"自动填充失败: {e}")
            messagebox.showerror("错误", f"自动填充失败: {e}")
    
    def manual_input(self):
        """Manual input of CAPTCHA."""
        text = self.manual_var.get()
        if not text:
            messagebox.showwarning("警告", "请输入验证码 / Please enter CAPTCHA")
            return
        
        if self.window_mgr.selected_window is None:
            messagebox.showwarning("警告", "请先选择模拟器窗口 / Please select emulator window first")
            return
        
        try:
            win = self.window_mgr.selected_window
            click_x = win['left'] + win['width'] // 2
            click_y = win['top'] + int(win['height'] * 0.65)
            
            pyautogui.click(click_x, click_y)
            time.sleep(0.3)
            pyautogui.write(text)
            
            self.log(f"手动输入验证码: {text}")
        except Exception as e:
            self.log(f"手动输入失败: {e}")
            messagebox.showerror("错误", f"手动输入失败: {e}")
    
    def toggle_auto_mode(self):
        """Toggle auto recognition mode."""
        if self.auto_mode.get():
            self.is_running = True
            self.recognition_thread = threading.Thread(target=self.auto_loop, daemon=True)
            self.recognition_thread.start()
            self.status_label.config(text="状态: 自动模式运行中 / Status: Auto mode running", foreground="green")
            self.log("自动模式已启动")
        else:
            self.is_running = False
            self.status_label.config(text="状态: 就绪 / Status: Ready", foreground="green")
            self.log("自动模式已停止")
    
    def auto_loop(self):
        """Auto recognition loop."""
        while self.is_running:
            try:
                screenshot, error = self.window_mgr.capture_window()
                if error:
                    self.log(f"捕获失败: {error}")
                    time.sleep(self.interval.get())
                    continue
                
                self.current_screenshot = screenshot
                w, h = screenshot.size
                captcha_region = screenshot.crop((0, int(h * 0.1), w, int(h * 0.5)))
                
                text, info = self.processor.recognize(captcha_region)
                
                if text and text != self.last_captcha:
                    self.last_captcha = text
                    self.root.after(0, lambda: self.result_var.set(text))
                    self.root.after(0, lambda: self.info_text.delete(1.0, tk.END))
                    self.root.after(0, lambda t=text, i=info: self.info_text.insert(tk.END, i))
                    self.root.after(0, lambda t=text: self.log(f"自动识别: {t}"))
                    self.root.after(0, self.auto_fill)
                
            except Exception as e:
                self.log(f"自动循环错误: {e}")
            
            time.sleep(self.interval.get())
    
    def run(self):
        """Run the application."""
        self.root.mainloop()


def main():
    root = tk.Tk()
    app = CaptchaRecognizerApp(root)
    app.run()


if __name__ == "__main__":
    main()

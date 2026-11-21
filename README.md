# 雷电模拟器验证码自动识别桌面软件
# Auto CAPTCHA Recognizer for Thunder (Leidian) Emulator

## 功能特点 / Features

- 自动捕获雷电模拟器窗口截图
- 图像预处理（灰度化、去噪、二值化、形态学操作）
- 使用 Tesseract OCR 识别验证码数字
- 自动将识别结果填入验证码输入框
- 支持手动输入验证码
- 自动模式：定时循环识别并填充
- 图形用户界面（tkinter）

## 系统要求 / Requirements

- Python 3.7+
- Windows 10/11（推荐）或 Linux（需 X11 显示服务器）
- Tesseract OCR 引擎（用于更好的识别效果）
- 雷电模拟器（Leidian Emulator）或其他 Android 模拟器

## 安装 / Installation

### 1. 克隆仓库
```bash
git clone <repository-url>
cd jufeng-update-test
```

### 2. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 3. 安装 Tesseract OCR（可选但推荐）

**Windows:**
- 下载安装程序：https://github.com/UB-Mannheim/tesseract/wiki
- 安装后将 tesseract.exe 添加到系统 PATH
- 或在代码中指定路径：`pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'`

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim
```

**macOS:**
```bash
brew install tesseract
```

## 使用方法 / Usage

### 启动程序
```bash
python captcha_recognizer.py
```

### 基本操作流程

1. **选择模拟器窗口**：点击"刷新"按钮，从下拉列表中选择运行中的雷电模拟器窗口
2. **捕获截图**：点击"捕获当前窗口"获取模拟器屏幕截图
3. **识别验证码**：点击"识别验证码"自动识别图片中的数字验证码
4. **自动填充**：点击"自动填充"将识别结果输入到验证码输入框
5. **手动输入**：如果自动识别不准确，可在手动输入框中输入验证码，然后点击"输入到窗口"

### 自动模式

勾选"启动自动识别"后，程序将：
- 按设定的间隔时间自动捕获窗口截图
- 自动识别验证码
- 自动填充到输入框
- 适用于连续多个账号验证的场景

## 文件结构 / File Structure

```
jufeng-update-test/
├── captcha_recognizer.py    # 主程序文件
├── requirements.txt         # Python 依赖列表
└── README.md               # 说明文档
```

## 注意事项 / Notes

1. **屏幕分辨率**：确保模拟器窗口可见且不被最小化
2. **验证码位置**：程序默认截取窗口上半部分作为验证码区域，如验证码位置不同需调整代码中的裁剪区域
3. **识别准确率**：受图像质量、验证码干扰线、字体变形等因素影响，建议先手动验证识别结果
4. **自动填充位置**：默认点击窗口中心偏下位置作为输入框，如不准确需调整坐标
5. **法律合规**：仅用于学习和自动化测试目的，请遵守目标平台的服务条款

## 故障排除 / Troubleshooting

| 问题 | 解决方案 |
|------|---------|
| 找不到模拟器窗口 | 确保模拟器正在运行且窗口可见 |
| 识别结果为空 | 安装 Tesseract OCR，或检查验证码图像质量 |
| 自动填充无反应 | 调整点击坐标，确保点击到输入框 |
| 程序启动失败 | 检查 Python 版本和依赖包是否正确安装 |

## 许可证 / License

MIT License

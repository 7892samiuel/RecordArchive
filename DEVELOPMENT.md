# 开发说明

## 已公开的代码

- `share-import/Receiver.cs`：Windows 分享激活、接收文件、通知主程序。
- `share-import/shared_record_backend.py`：解析分享 ZIP、校验路径、匹配附件。
- `share-import/rendered_media.py`、`OcrHelper.cs`：核对已转发记录后补取可见媒体，保存静态图片或动画片段。
- `share-import/ui_feedback.py`、`app_shutdown.py`：自动接收、操作反馈和关闭处理。
- `share-import/support_diagnostics.py`：筛选诊断字段。
- `lifecycle/`：启动器、注册、注销和卸载逻辑。
- `tests/`：使用合成文本与图片的单元测试。

## 运行测试

使用 Python 3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests -p "test_*.py" -v
```

这些测试不读取微信聊天、安装应用或注册系统分享入口。

## 编译接收器与 OCR 辅助程序

在 Windows x64 的 Windows PowerShell 中运行：

```powershell
.\share-import\build_receiver.ps1 -Destination .\build\receiver
```

需要 .NET Framework 4.x C# 编译器及系统 WinMetadata。此操作只生成组件，不安装、不签名，也不注册分享入口。操作系统与微信的分享兼容要求见首页。

## 完整构建的现状

发布版 1.0.0.13 的桌面界面、PDF 导出和部分运行时仍来自历史冻结程序。`build_core.py` 是对该基准的补丁构建脚本，需要外部基准文件；它不是从零构建整个应用的入口。本仓库不包含该二进制基准，也未纳入未经核实的历史源码草稿。

后续需要补齐这些模块、接入当前回调并建立完整构建流程。当前组件测试通过不等于整个桌面应用可独立重建。

安装相关源码保留当前发布版的应用身份和公开证书指纹，用于核对程序完整性。证书指纹不是私钥；仓库不含签名证书文件、私钥或密码。独立发行需要使用自己的应用身份和签名，同时调整启动器与注册校验，不能复用原发布者私钥。

## 提交文件范围

提交代码、文档和合成测试。不要提交真实聊天、导出附件、用户诊断、账号配置、签名材料、机器专用脚本或开发日志。第三方组件遵循各自许可，见 THIRD_PARTY_NOTICES.md。

# 记录归档

把微信合并聊天记录保存为 PDF，图片、GIF 和文件单独归档。

[下载 Windows x64 版](https://github.com/7892samiuel/RecordArchive/releases/download/v1.0.0.13-test/RecordArchive-1.0.0.13-win-x64-test.zip) · [版本记录](https://github.com/7892samiuel/RecordArchive/releases) · [反馈问题](https://github.com/7892samiuel/RecordArchive/issues)

## 使用

1. 完整解压，运行 `WeChatRecordExporter.exe`，按提示初始化分享入口。
2. 微信选择消息 → **合并转发 → 其他应用 → 记录归档**。
3. 收到后自动预览，核对或编辑文字，点击 **导出 PDF**。

首次初始化需管理员确认信任测试证书。本版证书有效至 **2026-11-11**，到期后无法初始化分享入口。

## 导出内容

| 文件 | 内容 |
| --- | --- |
| `聊天记录.pdf` | 便于阅读、打印和分享的聊天记录 |
| `assets/` | 图片、GIF 及文件附件 |
| `微信原始归档.zip` | 微信转发交付的原始包 |

GIF 原件随附件保存，页面补取的动画保存为播放片段。语音文字可手动补充。

## 使用条件

Windows 10/11，Intel/AMD 64 位电脑；微信需要提供可用的“其他应用”转发入口。已实测 Windows 11 25H2、微信 4.1.15.56。

Windows 11 23H2（22631.6060）搭配微信 4.2.0.9 有“其他应用”列表空白的反馈，该组合的兼容问题待修复。

## 数据与卸载

聊天内容在本机处理，导出文件保存在你选择的位置。

运行 `卸载记录归档.cmd` 移除程序与系统分享入口，保留已导出的文件。直接删文件夹会留下分享注册。

反馈时附上 Windows、微信版本和“使用方法 → 复制诊断信息”即可。

## 项目与致谢

当前已公开分享接收、归档解析、媒体处理、界面回调和安装卸载组件的源码，采用 [MIT 许可证](LICENSE)。测试与构建范围见 [开发说明](DEVELOPMENT.md)。完整桌面程序仍依赖历史冻结运行时，尚不能仅凭本仓库重建。第三方许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和下载包内的许可证目录。

Windows 分享接收设计参考 [WeChatBridge](https://github.com/freestylefly/WeChatBridge) 与 [ChatPCBridge](https://github.com/bwjoke/ChatPCBridge)。

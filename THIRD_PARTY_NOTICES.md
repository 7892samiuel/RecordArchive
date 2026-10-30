# Third-party notices

This distribution contains the application runtime only. Historical database,
key, archive recovery and experimental voice-model modules are not included.

## Runtime components

- Python: Python Software Foundation license, supplied in `third-party-licenses/Python-LICENSE.txt`.
- Pillow: MIT-CMU license, supplied in `third-party-licenses/pillow/`.
- ReportLab: BSD license, supplied in `third-party-licenses/reportlab/`.
- charset-normalizer: MIT license, supplied in `third-party-licenses/charset-normalizer/`.
- windows-capture 2.0.1: MIT license, Copyright (c) NiiightmareXD. Native window capture only; its OpenCV/NumPy wrapper is not included. Full license: `third-party-licenses/windows-capture/LICENCE`.
- PyInstaller bootloader: its supplied license and bootloader distribution exception are retained in `third-party-licenses/pyinstaller/`. The build tool itself is not part of the application runtime.

Exact component versions are listed in `third-party-packages.json`.

## Chinese font

Record Archive Sans is a renamed static weight-400 face derived from Noto Sans SC,
Copyright 2014-2021 Adobe, with Reserved Font Name 'Source'. It is distributed
under SIL Open Font License 1.1. Full license, modification notice and source
hashes are supplied in `_internal/assets/fonts/`. No system font installation is
performed. The font may be embedded in generated PDFs under its supplied license.

## Native share design references

Native Windows share activation design was informed by these MIT projects:

- WeChatBridge: Copyright (c) 2026 qzz0518, https://github.com/freestylefly/WeChatBridge
- ChatPCBridge: Copyright (c) 2026 ChatPCBridge contributors, https://github.com/bwjoke/ChatPCBridge

The receiver copies the ZIP explicitly shared by the user into a private local
inbox before completing the Windows share operation, then signals the main app.
The main app parses that copy and may supplement missing images from the matching
open record page. It does not read the WeChat database or media cache.

### MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

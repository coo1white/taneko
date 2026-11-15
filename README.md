# Taneko（たね子）工坊

*Stay with me, even when the connection drops.*

[![GitHub stars](https://img.shields.io/github/stars/coo1white/taneko?style=social)](https://github.com/coo1white/taneko)

> 下载大视频，断了不用重来；做字幕，机器干活，关键处由你把关。
> Resumable video downloads that pick up where they stopped, and subtitles you proofread at the points that matter.

你想下 9 小时比赛里的第 3 局，下到一半断了。别的工具让你重来，这个让你接着下，甚至能把上次留下的半截文件接上。

## 关于 Taneko

Taneko 是这个工坊里一位昭和复古风的“种子娘”：网断了，她把没做完的旧文件当种子好好收着，等你回来接着做。

吉祥物设定还在筹备中，将是原创角色，不借用任何现有作品的人物或美术。

## 致敬 BitTorrent

灵感来自 BitTorrent：把一件大事切成小片，每片独立校验，断了只补缺的。名字 Taneko（たね子，“种子”加上昭和老派女孩名常见的“子”）里的种子，就是 BitTorrent 的 seed——这里指断了之后留下的旧半截文件，它被当作种子，接着往下用。
献给从小陪我们一起长大的 BT 下载，感谢 Bram Cohen 和 BitTorrent 社区。

本项目没有 P2P，不会更快（价值在于不丢进度），不是 BitTorrent 的实现或客户端，也与 BitTorrent, Inc. 无关。

> Inspired by BitTorrent: split a big job into pieces, verify each one, and redo only what is missing. The name Taneko (たね子) means "seed" with the old-fashioned Showa-style "-ko" ending; the seed is the half-finished file an interrupted download leaves behind — it is reused as the seed. Thanks to Bram Cohen and the BitTorrent community. This project has no P2P, is not a BitTorrent implementation or client, and is not affiliated with BitTorrent, Inc.

## 核心功能

- **可续传的截取下载**：把要下的范围切成小片（默认 600 秒），逐片下载并校验起止和关键帧；断了、被限速了、链接过期了，只补缺的片。
- **半截文件当“种子”**：旧的残缺文件通过画面比对找到在时间轴上的位置，接着用，不用从头来。
- **无缝拼接**：按关键帧无损拼接，并检查时间戳是否连续。
- **一条命令跑完，断了重跑接着来**：每个阶段自己判断“做完了吗”；`status` 一眼看到所有项目卡在哪一步。
- **精校字幕，不是一键机翻**：本地 Whisper 转写 → 找出可能听错的专有名词 → 你校对术语表 → 批量修正 → 按术语表统一翻译 → 检查 → 你抽查。人工检查点是流程的一部分。
- **本地优先**：转写在你自己的显卡上跑；API 密钥只放环境变量，不写文件。

## 验证状态（诚实版）

| 已在真实环境验证 | 尚未完整验证 |
|---|---|
| 分片下载、种子对齐、拼接（一局 55 分钟的 1440p60 视频：复用 41 分钟旧文件，对齐画面差异 0.00，无时间断档） | 新框架里的转写、术语校对、翻译这几步（正在用第一局回归） |
| 流程状态判断与人工检查点（5 个自动测试 + 真实项目 `status`）；多片并发下载（`--jobs 2`，在同一场比赛的另外 4 段视频上跑通） | 非 Windows 平台（macOS / Linux 未实测） |

## 技术栈

| 层 | 用到的东西 | 用来做什么 |
|---|---|---|
| 语言 | Python（目标 3.8+，日常在 3.12 上运行），只用标准库：`argparse`、`subprocess`、`concurrent.futures`、`threading`、`json`、`re`、`pathlib`、`unittest` | 整个框架，无第三方 Python 依赖 |
| 下载 | [yt-dlp](https://github.com/yt-dlp/yt-dlp)（Unlicense）+ deno（JS 运行时）+ 浏览器 cookies | 取得视频流；以子进程调用 |
| 媒体处理 | [FFmpeg](https://ffmpeg.org/) / ffprobe（LGPL 2.1+，视构建方式可能为 GPL）：`-copyts`、stream copy、concat demuxer、缩略图比对 | 分片保留绝对时间戳、无损截取与拼接、读取包时间戳；以子进程调用 |
| 语音识别 | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) + CTranslate2，模型 large-v3，CUDA GPU（float16） | 本地转写，不上传视频 |
| 翻译 | [llm-subtrans](https://github.com/machinewrapped/llm-subtrans) + OpenAI 兼容接口（当前 OpenCode） | 按术语表和领域说明翻译字幕，可随时中断续译 |
| 状态与配置 | 每个项目一个 `meta.json`；`config/*.json` | 项目配置、术语表、检查点放行记录 |
| 质量 | `unittest`、Mermaid（架构图）、Git | 测试、文档、版本管理 |

框架本身只“调用”外部工具，不链接、不打包它们的代码；使用时需自行安装 ffmpeg、yt-dlp 等并遵守各自许可证。

## 用法（PowerShell 7）

```powershell
cd D:\Ops_OPC\framework
python taneko.py status                     # 所有项目的进度
python taneko.py status lol-worlds-2026-g1  # 单个项目的每一步
python taneko.py run lol-worlds-2026-g1     # 按计划往下跑，遇到人工检查点停下
python taneko.py approve lol-worlds-2026-g1 terms   # 术语校对完，放行
python taneko.py approve lol-worlds-2026-g1 spot    # 抽查完，放行
```

单个阶段也能单独跑：`fetch / subs / asr / terms / fix / translate / check`。
翻译前想先试风格：`python taneko.py translate <项目> --test`。

## 流程

`fetch → asr(或 subs) → terms → ⏸术语校对 → fix → translate → check → ⏸抽查`

原文是中文时只跑 `fetch → asr`。完整架构、依赖图、Mermaid 图见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 配置

路径默认：项目根 = framework 的上一级，项目在 `<根>\projects`，翻译工具在 `<根>\workflow\vendor`。
可用环境变量覆盖：`TANEKO_ROOT`、`TANEKO_PROJECTS`、`TANEKO_CONFIG`、`TANEKO_VENDOR`。
API 密钥只走环境变量 `OPENCODE_API_KEY`（或运行时输入）。

## 使用提醒

仅用于你有权下载和处理的内容；请遵守平台服务条款和所在地法律，转载他人作品前请确认版权。

- 下载时默认读取本机浏览器的 cookies（`--cookies-from-browser`），只在本地使用，不会写入文件或上传。
- 翻译步骤会给你本地安装的 llm-subtrans 打一个小补丁（让它支持额外请求头和参数），只改你电脑上的副本，不分发它的代码。
- 转写默认读取 `config/asr.json` 里的 `home`（Whisper 目录，示例为 `D:\Tools\whisper`），请改成你自己的路径。

## 许可证与支持

本项目使用 [MIT 许可证](LICENSE)：可以自由使用、修改、分发，保留版权声明即可。

如果它帮你省下了时间，欢迎点一下右上角的 ⭐ **Star**——这是对作者最直接的支持，也能让更多需要的人看到它。
这只是一个请求，不是使用条件。

> If taneko saved you time, a ⭐ on GitHub is the best way to say thanks. It's a request, not a condition of the license.

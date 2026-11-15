# Taneko（たね子）工坊

*Stay with me, even when the connection drops.*

[![GitHub stars](https://img.shields.io/github/stars/coo1white/taneko?style=social)](https://github.com/coo1white/taneko)

> 下载大视频，断了不用重来；做字幕，机器干活，关键处由你把关。
> Resumable video downloads that pick up where they stopped, and subtitles you proofread at the points that matter.

你想下 9 小时比赛里的第 3 局，下到一半断了。别的工具让你重来，这个让你接着下，还能把上次留下的半截文件接上。

## 能做什么

- **断了接着下**：把要下的范围切成小片（默认 600 秒），逐片下载、逐片校验。断网、限速、链接过期，都只补缺的那几片。
- **半截文件不浪费**：上次留下的残缺文件，靠画面比对找到它在时间轴上的位置，直接接着用。
- **无损拼接**：按关键帧拼起来，不重新编码，并检查时间戳有没有断档。
- **一条命令跑完**：每一步自己知道“做完了没有”。断了就重跑同一条命令；`status` 一眼看出每个项目卡在哪。
- **精校字幕，不是一键机翻**：本地 Whisper 转写 → 找出可能听错的专有名词 → 你校对 → 批量修正 → 按术语表翻译 → 检查 → 你抽查。两处人工检查点是流程的一部分，跳不过去。
- **本地优先**：转写在你自己的显卡上跑，视频不上传；API 密钥只放环境变量，不进项目文件。

## 快速开始

### 1. 装好外部工具

Taneko 只用 Python 标准库，但要调用下面这些工具，请自行安装：

| 工具 | 哪一步要用 | 必须吗 |
|---|---|---|
| Python 3.8+ | 全部 | 必须 |
| [FFmpeg](https://ffmpeg.org/)（含 ffprobe），放进 PATH | 下载、拼接、检查 | 必须 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) + [deno](https://deno.com/) | 下载、抓字幕 | 必须 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（单独的 venv，建议 CUDA 显卡） | 转写 `asr` | 没有现成字幕时要 |
| [llm-subtrans](https://github.com/machinewrapped/llm-subtrans) + 一个 OpenAI 兼容接口的密钥 | 翻译 `translate` | 要翻译时要 |

装好后，把 `config/asr.json` 里的 `home` 改成你的 Whisper 目录。

### 2. 建一个项目

每个项目是 `projects/<项目名>/` 下的一个文件夹，里面放一个 `meta.json`。最小的例子：

```json
{
  "source_url": "https://www.youtube.com/watch?v=...",
  "section": { "download": "4:13:00-5:08:00", "name": "game3" },
  "subtitle": { "method": "asr", "source_lang": "en" },
  "translate": { "domain": "英雄联盟电竞", "names": [], "corrections": {} }
}
```

- 不写 `section.download` 就下整条视频。
- 原视频有字幕时，`method` 写 `subs`，直接抓字幕，不用转写。
- 原文是中文时，`source_lang` 写 `zh`，只下载和转写，不翻译。

### 3. 跑起来

```bash
python taneko.py run my-project             # 往下跑，遇到人工检查点停下
python taneko.py status                     # 所有项目的进度
python taneko.py status my-project          # 单个项目的每一步
python taneko.py approve my-project terms   # 术语校对完，放行
python taneko.py approve my-project spot    # 抽查完，放行
```

单个阶段也能单独跑：`fetch / subs / asr / terms / fix / translate / check`。
翻译前想先试风格：`python taneko.py translate my-project --test`。

## 流程

`fetch → asr（或 subs）→ terms → ⏸术语校对 → fix → translate → check → ⏸抽查`

停在 ⏸ 时，屏幕上会告诉你要看哪个文件、改哪里、下一条命令是什么。完整架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

### 退出码

脚本和 agent 靠退出码判断下一步：

| 退出码 | 含义 | 该怎么办 |
|---|---|---|
| `0` | 成功；`run` 表示全部完成 | 没有下一步 |
| `1` | 出错（输出里有“错误：……”） | 看报错，修了再重跑 |
| `2` | 命令行参数不对 | 看 `--help` |
| `10` | `run` 停在人工检查点（不是失败） | 人处理后 `approve`，再重新 `run` |

## 配置

- 默认目录：项目放在代码目录上一级的 `projects/`，翻译工具在上一级的 `workflow/vendor/`。
- 可以用环境变量改：`TANEKO_ROOT`、`TANEKO_PROJECTS`、`TANEKO_CONFIG`、`TANEKO_VENDOR`。
- 转写设置在 `config/asr.json`，翻译设置（接口、模型、分段大小、通用要求）在 `config/translate.json`。

### API 密钥

密钥只走环境变量 `OPENCODE_API_KEY`，从不写进项目文件或仓库。

```bash
python taneko.py key set      # 保存（输入时不显示）
python taneko.py key status   # 只显示有没有、多长、从哪来，不显示内容
python taneko.py key clear    # 删除
```

- Windows：`key set` 存进你的用户环境变量，新开的窗口都能用。它是明文的，你的账户下运行的程序都读得到。
- macOS / Linux：`key set` 不保存，请自己在 shell 配置里 `export OPENCODE_API_KEY=...`（别提交进 git）。
- 不想保存也行：在终端里翻译时会问一次。脚本或 agent 运行时不会问，直接报错退出，不会卡住。

## 验证状态（诚实版）

| 已在真实环境验证 | 还没完整验证 |
|---|---|
| 分片下载、种子对齐、拼接：一局 55 分钟的 1440p60 视频，复用 41 分钟旧文件，对齐画面差异 0.00，没有时间断档 | 新框架里的转写、术语校对、翻译（正在用第一局回归） |
| 多片并发下载（`--jobs 2`）：同一场比赛的另外 4 段视频跑通 | macOS / Linux（只在 Windows 上实测过） |
| 流程判断、人工检查点、退出码、分段翻译：有自动测试 | |

### 已知问题

- 片段短于约 41 分钟时，下载“完成”的标准前后不一致，`run` 可能反复报错：issue [#1](../../issues/1)
- 重做前面的步骤后，旧的人工放行仍然有效：issue [#2](../../issues/2)
- 只下载一段时，`subs` 抓来的字幕可能整体错位（待确认，用 `asr` 不受影响）：issue [#3](../../issues/3)
- 换一台电脑还不好装：issue [#5](../../issues/5)

全部问题见 [Issues](../../issues)，接下来的计划见 [ROADMAP.md](ROADMAP.md)。

## 技术栈

| 层 | 用到的东西 | 用来做什么 |
|---|---|---|
| 语言 | Python（目标 3.8+，日常在 3.12 上运行），只用标准库 | 整个框架，没有第三方 Python 依赖 |
| 下载 | yt-dlp（Unlicense）+ deno + 浏览器 cookies | 取视频流，子进程调用 |
| 媒体处理 | FFmpeg / ffprobe（LGPL 2.1+，视构建方式可能为 GPL）：`-copyts`、stream copy、concat demuxer、缩略图比对 | 分片保留绝对时间戳、无损截取与拼接，子进程调用 |
| 语音识别 | faster-whisper + CTranslate2，模型 large-v3，CUDA（float16），失败时退回 CPU | 本地转写 |
| 翻译 | llm-subtrans + OpenAI 兼容接口（目前只测过 OpenCode） | 按术语表和领域说明翻译；每 200 条一段，译完一段存一段，中断后只补没译完的段 |
| 状态与配置 | 每个项目一个 `meta.json`；`config/*.json` | 项目配置、术语表、检查点放行记录 |
| 质量 | `unittest`、Mermaid、Git | 测试、架构图、版本管理 |

Taneko 只“调用”这些工具，不链接、不打包它们的代码；请自行安装并遵守各自的许可证。

## 关于 Taneko

Taneko 是这个工坊里一位昭和复古风的“种子娘”：网断了，她把没做完的旧文件当种子好好收着，等你回来接着做。

吉祥物设定还在筹备中，将是原创角色，不借用任何现有作品的人物或美术。

## 致敬 BitTorrent

灵感来自 BitTorrent：把一件大事切成小片，每片独立校验，断了只补缺的。名字 Taneko（たね子，“种子”加上昭和老派女孩名常见的“子”）里的种子，就是 BitTorrent 的 seed——这里指断了之后留下的旧半截文件，它被当作种子，接着往下用。
献给从小陪我们一起长大的 BT 下载，感谢 Bram Cohen 和 BitTorrent 社区。

本项目没有 P2P，不会更快（价值在于不丢进度），不是 BitTorrent 的实现或客户端，也与 BitTorrent, Inc. 无关。

> Inspired by BitTorrent: split a big job into pieces, verify each one, and redo only what is missing. The name Taneko (たね子) means "seed" with the old-fashioned Showa-style "-ko" ending; the seed is the half-finished file an interrupted download leaves behind, and it is reused. Thanks to Bram Cohen and the BitTorrent community. This project has no P2P, is not a BitTorrent implementation or client, and is not affiliated with BitTorrent, Inc.

## 使用提醒

只用于你有权下载和处理的内容；请遵守平台服务条款和所在地法律，转载他人作品前请确认版权。

- 下载时默认读取本机 Firefox 的 cookies（`--cookies-from-browser`），只在本地用，不写文件、不上传。可在 `meta.json` 的 `fetch.browser` 换浏览器，写 `none` 不用 cookies。
- 翻译步骤会给你本地装的 llm-subtrans 打一个小补丁（让它支持额外的请求头和参数），只改你电脑上的那份，不分发它的代码。

## 许可证与支持

本项目使用 [MIT 许可证](LICENSE)：可以自由使用、修改、分发，保留版权声明即可。

如果它帮你省下了时间，欢迎点一下右上角的 ⭐ **Star**——这是对作者最直接的支持，也能让更多需要的人看到它。
这只是一个请求，不是使用条件。

> If taneko saved you time, a ⭐ on GitHub is the best way to say thanks. It's a request, not a condition of the license.

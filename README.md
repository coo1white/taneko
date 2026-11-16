# Taneko

[![PyPI](https://img.shields.io/pypi/v/taneko)](https://pypi.org/project/taneko/)
[![test](https://github.com/coo1white/taneko/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/coo1white/taneko/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/coo1white/taneko#快速上手)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/coo1white/taneko/blob/main/LICENSE)

*Stay with me, even when the connection drops.*

> 下载长视频里的一段。断了接着下，不用重来。
> Download part of a long video. If it stops, run it again and it picks up where it stopped.

## 它能做什么

- **只下你要的一段**：写好开始和结束时间，只下这段，速度和下整条一样。
- **断了接着下**：断网、关机、链接过期，再跑一次就行，已下的部分不会丢。
- **旧的半截文件接着用**：以前没下完的文件放进项目文件夹，Taneko 找到它对应的时间，只补缺的部分。
- **画质不变**：不重新编码。下完自动检查画面有没有断档、声音有没有空白。

## 适合你吗？

- **适合**：只要长视频里的一段，比如 9 小时直播里的一局；或者网络不稳，下大文件常常断。
- **不太需要**：只下完整的短视频、网络也稳。直接用 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 就够了，Taneko 本来也是用它取视频。

## 快速上手

下面是最常见的用法：只下视频，不做字幕。共 3 步。

### 1. 安装

先装 FFmpeg、deno 和 pipx，再用 pipx 装 Taneko。yt-dlp 会跟着 Taneko 一起装上。

**Windows**（PowerShell 或 cmd）：

```bash
winget install Python.Python.3.12 Gyan.FFmpeg DenoLand.Deno
```

关掉终端，重新打开一个，再运行：

```bash
py -m pip install --user pipx
py -m pipx ensurepath
```

再关掉终端、重新打开，然后：

```bash
pipx install taneko
```

**macOS**：

```bash
brew install ffmpeg deno pipx
pipx ensurepath
pipx install taneko
```

**Linux**（Ubuntu / Debian）：

```bash
sudo apt install ffmpeg pipx
curl -fsSL https://deno.land/install.sh | sh
pipx ensurepath
pipx install taneko
```

装好后检查一遍：

```bash
taneko doctor
```

缺什么，它会告诉你怎么装。Whisper 和 llm-subtrans 只有做字幕才要，可以不管。

Taneko 默认读取 Firefox 的登录信息（cookies），能下更多视频，比如会员视频。不用 Firefox 也能下。

### 2. 建一个项目

```bash
taneko init game3 "https://www.youtube.com/watch?v=..." --section 4:13:00-5:08:00
```

- `game3`：项目名，也是下好的文件名（`game3.mkv`）。
- 网址：前后加英文引号，免得 `&` 之类的符号被终端误读。
- `--section`：开始-结束时间，可写 `4:13:00`、`13:00` 或 `780`（秒）。多短都行，比如 `4:13:00-4:14:00` 只下 1 分钟。不写就下整条视频。

项目建在用户目录下的 `taneko/projects/game3/`（Windows 是 `C:\Users\你的用户名\taneko\projects\game3\`）。屏幕上会显示完整路径。

### 3. 下载

```bash
taneko run game3
```

屏幕最后会显示检查结果和文件位置，例如：

```text
检查结果：视频时长 64.5 秒；音频从 4.5 秒到 64.5 秒
完成：C:\Users\你的用户名\taneko\projects\game3\game3.mkv
```

视频比你要的长几秒，这是正常的：画面要从开始时间之前最近的关键帧开始，才能不重新编码。声音正好从开始时间开始。检查没通过时，会显示“错误：”和原因，不会覆盖旧文件。

**中途断了？** 再跑一次同样的命令。

**卸载**：`pipx uninstall taneko`。下好的视频在 `taneko/projects/` 里，不会被删。

## 常见问题

**怎么看下到哪了？**
`taneko status` 列出所有项目的进度。

**我有一个以前没下完的文件，能用吗？**
能。把它改名成 `name` 写的名字（例如 `game3.mkv`），放进项目文件夹，再跑 `run`。

**不用 Firefox？**
建项目时加 `--browser chrome`。写 `--browser none` 表示不读浏览器的登录信息。

**下载失败了？**
看屏幕上“错误：”后面的说明，照着做，再跑一次。还不行就[提一个 issue](https://github.com/coo1white/taneko/issues)，附上屏幕上的输出。

## 进阶

<details>
<summary><b>所有命令</b></summary>

```bash
taneko init game3 网址 --section 开始-结束   # 新建项目
taneko run game3            # 跑完所有步骤，已完成的跳过
taneko run .                # 在项目文件夹里运行；也可以给完整路径
taneko status game3         # 一个项目的每一步
taneko status --json        # 进度的 JSON 版，给脚本和 agent 读
taneko fetch game3 --jobs 2 # 只跑下载这一步
taneko doctor               # 检查工具
```

`fetch` 的常用选项：`--force` 重新下载，`--sections` 改用分段下载，`--keep` 保留中间文件。

项目可以分组，最多 3 层：`init lol-worlds/game3 网址` 会建在 `projects/lol-worlds/game3/`，之后用 `run game3` 就行。

`init` 写出的 `meta.json` 也可以手动改：

```json
{
  "source_url": "https://www.youtube.com/watch?v=...",
  "section": { "name": "game3", "download": "4:13:00-5:08:00" },
  "subtitle": { "method": "none" },
  "fetch": { "browser": "chrome" }
}
```

`"method": "none"` 表示只下视频，不做字幕。

</details>

<details>
<summary><b>从源码运行（不用 pipx）</b></summary>

```bash
git clone https://github.com/coo1white/taneko.git
python -m pip install yt-dlp
python taneko/taneko.py doctor
```

下面所有 `taneko` 命令都换成 `python taneko/taneko.py`。从源码运行时，项目放在代码文件夹旁边的 `projects/`。

</details>

<details>
<summary><b>下载是怎么做的</b></summary>

- 下整条视频时，交给 yt-dlp，它自己续传。
- 只下一段时，先读视频文件自带的索引（MP4 的 `sidx`、WebM 的 Cues），只下这段需要的字节；断了从已下的字节接着下。
- 没有索引的格式（例如直播流）改用分段下载：把时间范围切成小片（默认 600 秒），逐片下载、逐片检查，断了只补缺的片。
- 拼接时，视频在关键帧处接，音频在各自的起点处接，不重新编码。

YouTube 偶尔会对新地址返回 403，Taneko 会等几秒再试，再不行就换新地址，最后改用分段下载。

</details>

<details>
<summary><b>字幕（实验性，暂停开发）</b></summary>

字幕能用，但不保证质量。流程：

`fetch → asr（或 subs）→ terms → ⏸术语校对 → fix → translate → check → ⏸抽查`

本地 Whisper 转写，找出可能听错的专有名词，你校对，批量修正，按术语表翻译，检查，你抽查。停在 ⏸ 时，屏幕会告诉你看哪个文件、改哪里、下一条命令是什么。

还要装：

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：单独的 venv，建议用 CUDA 显卡。在 `taneko/config/asr.json` 的 `home` 里写它的目录。
- [llm-subtrans](https://github.com/machinewrapped/llm-subtrans)：翻译用，还要一个 OpenAI 兼容接口的密钥。

`meta.json` 的写法：

```json
{
  "source_url": "https://www.youtube.com/watch?v=...",
  "section": { "download": "4:13:00-5:08:00", "name": "game3" },
  "subtitle": { "method": "asr", "source_lang": "en" },
  "translate": { "domain": "英雄联盟电竞", "names": [], "corrections": {} }
}
```

- `method`：`asr` 是本地转写；`subs` 是抓视频自带的字幕。
- `source_lang` 写 `zh` 时，只转写，不翻译。

检查点命令：

```bash
taneko approve game3 terms   # 术语校对完
taneko approve game3 spot    # 抽查完
taneko translate game3 --test  # 先试翻译风格
```

单个步骤也能单独跑：`fetch / subs / asr / terms / fix / translate / check`。

**API 密钥**只放在环境变量 `OPENCODE_API_KEY`，不写进项目文件：

```bash
taneko key set      # 保存（输入时不显示）
taneko key status   # 只显示有没有、多长、从哪来
taneko key check    # 问一次服务器密钥是否有效（用 1 个 token）
taneko key clear    # 删除
```

- Windows：`key set` 存进用户环境变量。它是明文，你账户下的程序都读得到。
- macOS / Linux：`key set` 不保存，请自己在 shell 配置里 `export OPENCODE_API_KEY=...`。
- 不保存也行：在终端里翻译时会问一次。脚本或 agent 运行时不问，直接报错退出。

翻译步骤会给你本地的 llm-subtrans 打一个小补丁（支持额外的请求头和参数）。只改你电脑上那份，不分发它的代码。

</details>

<details>
<summary><b>退出码（给脚本和 agent）</b></summary>

| 退出码 | 含义 | 下一步 |
|---|---|---|
| `0` | 成功；`run` 表示全部完成 | 无 |
| `1` | 出错（输出里有“错误：”） | 看报错，修好再跑 |
| `2` | 命令参数不对 | 看 `--help` |
| `10` | `run` 停在人工检查点（不是失败） | 处理后 `approve`，再 `run` |

`status --json` 给出每个项目的 `next`（下一步）、`needs_human`（是否在等人）和每一步的 `state`（`done` / `skip` / `next` / `todo`）。

</details>

<details>
<summary><b>配置和目录</b></summary>

- 从源码运行时，项目默认在代码文件夹旁边的 `projects/`。用 pip 安装后，默认在用户目录下的 `taneko/projects/`（Windows 是 `C:\Users\你的用户名\taneko\projects`）。`doctor` 会显示实际位置。
- 翻译工具默认在项目目录旁边的 `workflow/vendor/`。
- 用环境变量改位置：`TANEKO_ROOT`、`TANEKO_PROJECTS`、`TANEKO_CONFIG`、`TANEKO_VENDOR`。
- 转写设置在 `taneko/config/asr.json`；翻译设置（接口、模型、分段大小）在 `taneko/config/translate.json`。

</details>

<details>
<summary><b>测过什么（诚实版）</b></summary>

| 在真实环境测过 | 还没测过 |
|---|---|
| 分段下载、半截文件对齐、拼接：一局 55 分钟的 1440p60 视频，复用 41 分钟的旧文件，对齐误差 0.00，视频无断档。2026-11-16 前拼的文件接缝处有 0.5～3.5 秒没声音，已修复（issue [#1](https://github.com/coo1white/taneko/issues/1)） | 转写、术语校对、翻译（实验性，暂停开发） |
| 按索引下载一段（issue [#8](https://github.com/coo1white/taneko/issues/8)）：YouTube 1440p60，中途强行停掉再跑，从已下的 160 MiB 接着下；画面和整条下载逐字节相同，音画差 5～21 毫秒；约 8 MiB/s（分段下载约 2 倍实时） | B 站、X 等网站的按索引下载 |
| Windows 上按索引下载：用 Firefox 登录信息，格式 308+140 跑了 3 次都成功，每次约 50 秒（分段下载 176 秒）；默认格式（AV1 + Opus）照快速上手走了一遍 | macOS、Linux 上的真实下载（只有自动测试） |
| 多片同时下载（`--jobs 2`）：同一场比赛的另外 4 段 | |
| 流程、人工检查点、退出码、分段翻译：有自动测试 | |

已知问题：

- 在新电脑上安装还不方便：issue [#5](https://github.com/coo1white/taneko/issues/5)。
- 字幕的已知问题随字幕一起暂停，见 [ROADMAP.md](https://github.com/coo1white/taneko/blob/main/ROADMAP.md) 的“暂停”一节。

全部问题见 [Issues](https://github.com/coo1white/taneko/issues)，计划见 [ROADMAP.md](https://github.com/coo1white/taneko/blob/main/ROADMAP.md)，架构见 [ARCHITECTURE.md](https://github.com/coo1white/taneko/blob/main/ARCHITECTURE.md)。

</details>

<details>
<summary><b>技术栈</b></summary>

| 层 | 用到的东西 | 做什么 |
|---|---|---|
| 语言 | Python 3.11+，代码只用标准库 | 整个框架。唯一的依赖是 yt-dlp，pip 安装时一起装上，只作为命令调用 |
| 下载 | yt-dlp（Unlicense）+ deno + 浏览器登录信息 | 取视频地址，子进程调用 |
| 按索引下载 | HTTP Range 请求，读 MP4 `sidx` 和 WebM Cues（标准库自己写） | 只下需要的字节，断了接着下 |
| 媒体处理 | FFmpeg / ffprobe（LGPL 2.1+，视构建方式可能为 GPL） | 无损截取、拼接、检查，子进程调用 |
| 语音识别 | faster-whisper + CTranslate2，large-v3，CUDA，失败时退回 CPU | 本地转写 |
| 翻译 | llm-subtrans + OpenAI 兼容接口（只测过 OpenCode） | 按术语表翻译；每 200 条存一次，中断后只补没译完的 |
| 状态 | 每个项目一个 `meta.json`；`taneko/config/*.json` | 项目设置、术语表、检查点记录 |
| 质量 | `unittest`、Mermaid、Git | 测试、架构图、版本管理 |

Taneko 只调用这些工具，不打包它们的代码。请自行安装，并遵守各自的许可证。

</details>

## 使用提醒

- 只下你有权下载的内容。遵守平台条款和当地法律；转载前确认版权。
- 默认读取本机 Firefox 的登录信息（cookies），只在本地用，不写文件、不上传。

## 致敬 BitTorrent

灵感来自 BitTorrent：把大事切成小片，每片单独检查，断了只补缺的。
献给陪我们长大的 BT 下载，感谢 Bram Cohen 和 BitTorrent 社区。

本项目没有 P2P，不会更快（价值在于不丢进度），不是 BitTorrent 的实现或客户端，与 BitTorrent, Inc. 无关。

> Inspired by BitTorrent: split a big job into small pieces, check each piece, and fetch only what is missing. Dedicated to the BT downloads we grew up with. Thanks to Bram Cohen and the BitTorrent community.
>
> Taneko has no P2P and is not faster; its value is that you never lose progress. It is not a BitTorrent implementation or client, and it is not affiliated with BitTorrent, Inc.

## 许可证

[MIT 许可证](https://github.com/coo1white/taneko/blob/main/LICENSE)：可以自由使用、修改、分发，保留版权声明即可。

如果它帮你省了时间，欢迎点右上角的 ⭐ **Star**。这是请求，不是使用条件。

> If taneko saved you time, a ⭐ is the best thanks. It's a request, not a license condition.

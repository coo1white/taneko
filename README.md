# Taneko

[![PyPI](https://img.shields.io/pypi/v/taneko?label=PyPI)](https://pypi.org/project/taneko/)
[![test](https://github.com/coo1white/taneko/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/coo1white/taneko/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](https://github.com/coo1white/taneko#快速上手)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/coo1white/taneko/blob/main/LICENSE)

*Stay with me, even when the connection drops.*

> 只下长视频里的一段：和下整条一样快，断了接着下。
> Download just one part of a long video: as fast as the whole file, and it resumes if it stops.

## 它能做什么

- **只下你要的一段**：写好开始和结束时间，只下这段，速度和下整条一样。
- **断了接着下**：断网、关机、链接过期，再跑一次就行，已下的部分不会丢。
- **旧的半截文件接着用**：以前没下完的文件放进项目文件夹，Taneko 找到它对应的时间，只补缺的部分。
- **画质不变**：不重新编码。下完自动检查画面有没有断档、声音有没有空白。

## 为什么不直接用 yt-dlp？

下**整条**视频时，[yt-dlp](https://github.com/yt-dlp/yt-dlp) 自己就能续传，不需要 Taneko。只下**一段**时就不一样了：

| 下 9 小时直播里的 5 分钟 | yt-dlp `--download-sections` | Taneko |
|---|---|---|
| 用时 | 176 秒 | 约 50 秒 |
| 中途关掉终端，再跑一次 | 从零开始 | 接着下 |

2026-11-16 在 Windows 上实测，YouTube 1440p。yt-dlp 下一段时改用 ffmpeg 下载，ffmpeg 不能续传。Taneko 读视频文件自带的索引，只下这一段的字节。

- **适合**：只要长视频里的一段，比如 9 小时直播里的一局。
- **不太需要**：只下整条视频。直接用 yt-dlp 就够了，Taneko 本来也是用它取视频地址。
- **不做**：字幕。下完后可以用 [VideoLingo](https://github.com/Huanshere/VideoLingo) 或 [pyvideotrans](https://github.com/jianchang512/pyvideotrans)。

## 快速上手

下面是最常见的用法，共 3 步。

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

缺什么，它会告诉你怎么装。

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
检查结果：视频时长 64.5 秒；音频从 0.0 秒到 64.5 秒
完成：C:\Users\你的用户名\taneko\projects\game3\game3.mkv
```

视频比你要的长几秒，这是正常的：画面要从开始时间之前最近的关键帧开始，才能不重新编码。声音也从那里开始，开头不会没声音。检查没通过时，会显示“错误：”和原因，不会覆盖旧文件。

**中途断了？** 再跑一次同样的命令。

**卸载**：`pipx uninstall taneko`。下好的视频在 `taneko/projects/` 里，不会被删。

## 常见问题

**怎么看下到哪了？**
`taneko status` 列出所有项目的进度。

**我有一个以前没下完的文件，能用吗？**
能。把它改名成 `name` 写的名字（例如 `game3.mkv`），放进项目文件夹，再跑 `run`。

**不用 Firefox？**
建项目时加 `--browser chrome`。写 `--browser none` 表示不读浏览器的登录信息。

**在没有浏览器的服务器上下？**
YouTube 和 B 站常常拦云服务器的地址，要求登录。在自己电脑的浏览器里导出 cookies.txt（Netscape 格式，用浏览器扩展导出），传到服务器上，在 `meta.json` 的 `"fetch"` 里写 `"cookies": "文件路径"`（相对路径从项目文件夹算），或者给 `fetch` 加 `--cookies 文件路径`。这个文件等于你的登录状态，别发给别人，也别放进 git。

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

`init` 写出的 `meta.json` 也可以手动改（`cookies` 可选，有它就不读浏览器）：

```json
{
  "source_url": "https://www.youtube.com/watch?v=...",
  "section": { "name": "game3", "download": "4:13:00-5:08:00" },
  "fetch": { "browser": "chrome", "cookies": "cookies.txt" }
}
```

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
- 只下一段时，先读视频文件自带的索引（MP4 的 `sidx`、WebM 的 Cues），只下这段需要的字节；断了从已下的字节接着下。YouTube、B 站是这种。
- 格式是 HLS（`m3u8` 播放列表，例如 X）时，播放列表记着每一片的时长，只下覆盖这一段的分片；断了跳过已下完的分片。
- 两种都不行的格式（例如正在直播的流、加密的分片）改用分段下载：把时间范围切成小片（默认 600 秒），逐片下载、逐片检查，断了只补缺的片。
- 拼接时，视频在关键帧处接，音频在各自的起点处接，不重新编码。

YouTube 偶尔会对新地址返回 403，Taneko 会等几秒再试，再不行就换新地址，最后改用分段下载。

</details>

<details>
<summary><b>退出码（给脚本和 agent）</b></summary>

| 退出码 | 含义 | 下一步 |
|---|---|---|
| `0` | 成功 | 无 |
| `1` | 出错（输出里有“错误：”） | 看报错，修好再跑 |
| `2` | 命令参数不对 | 看 `--help` |
| `130` | 按了 Ctrl+C | 重跑同一条命令，接着下 |

`status --json` 给出每个项目的 `next`（下一步）和每一步的 `state`（`done` / `next` / `todo`）。

</details>

<details>
<summary><b>配置和目录</b></summary>

- 从源码运行时，项目默认在代码文件夹旁边的 `projects/`。用 pip 安装后，默认在用户目录下的 `taneko/projects/`（Windows 是 `C:\Users\你的用户名\taneko\projects`）。`doctor` 会显示实际位置。
- 用环境变量改位置：`TANEKO_ROOT`、`TANEKO_PROJECTS`。

</details>

<details>
<summary><b>测过什么（诚实版）</b></summary>

四个环境实测（2026-11-17，同一份代码，全新安装）：

| 功能 | Windows（PowerShell） | Windows（WSL） | Linux（云服务器，GitHub 的 Ubuntu） | macOS（arm64） |
|---|---|---|---|---|
| 安装、`doctor`、`--version` | ✓ | ✓ | ✓ | ✓ |
| YouTube 下一段 | ✓ | ✓ | 网站要求登录（机房地址）→ 用 cookies 文件 | ✓ |
| X 下一段 | ✓ | ✓ | ✓ | ✓ |
| B 站下一段 | ✓ | ✓ | 网站拒绝（412，机房地址）→ 用 cookies 文件 | ✓ |
| 进度行在终端里原地刷新 | ✓ | ✓ | ✓ | ✓ |
| 下到一半按 Ctrl+C，重跑接着下 | ✓ | ✓ | ✓（X） | ✓ |

Windows 用的是 Firefox 登录信息，其他环境都没登录。

WSL 就是 Linux（Ubuntu），走家里的网络，所以家用 Linux 电脑看 WSL 这一列。云服务器那一列的两处失败是网站拦机房地址，不是 Linux 的问题；带上 cookies 文件（见上面的“在没有浏览器的服务器上下？”）通常能过，但我们没有在云服务器上用真账号测过，YouTube 偶尔还会拦。

| 在真实环境测过 | 还没测过 |
|---|---|
| 分段下载、半截文件对齐、拼接：一局 55 分钟的 1440p60 视频，复用 41 分钟的旧文件，对齐误差 0.00，视频无断档。2026-11-16 前拼的文件接缝处有 0.5～3.5 秒没声音，已修复（issue #1） | |
| 按索引下载一段（issue [#8](https://github.com/coo1white/taneko/issues/8)）：YouTube 1440p60，中途强行停掉再跑，从已下的 160 MiB 接着下；画面和整条下载逐字节相同，音画差 5～21 毫秒；约 8 MiB/s（分段下载约 2 倍实时） | |
| B 站按索引下载一段（2026-11-16，Windows）：1080p，1 分钟和 3 分钟两段都有声音、时长对。从海外下很慢，约 0.1 MiB/s | B 站中途停掉后接着下（机制和 YouTube 相同，有自动测试，但 B 站上还没在下到一半时停过） |
| X 按播放列表下载一段（2026-11-16，Windows）：1080p 的 2 分钟，下到 11 / 41 片时强行停掉，重跑只下剩下的分片；成品 120 秒，有声音 | 其他用 HLS 的网站（如 Twitch 回放） |
| Windows 上按索引下载：用 Firefox 登录信息，格式 308+140 跑了 3 次都成功，每次约 50 秒（分段下载 176 秒）；默认格式（AV1 + Opus）照快速上手走了一遍 |  |
| 边收边写和进度行（2026-11-16，Windows）：下到 29.5 MiB 时强行停掉，重跑从 29.5 MiB 接着下；整条、YouTube 一段、X 一段都显示同样的进度行 | 终端里原地刷新的样子（只有自动测试；实测时输出接到了管道里） |
| 多片同时下载（`--jobs 2`）：同一场比赛的另外 4 段 | |
| 流程、退出码：有自动测试 | |

全部问题见 [Issues](https://github.com/coo1white/taneko/issues)，计划见 [ROADMAP.md](https://github.com/coo1white/taneko/blob/main/ROADMAP.md)，架构见 [ARCHITECTURE.md](https://github.com/coo1white/taneko/blob/main/ARCHITECTURE.md)。

</details>

<details>
<summary><b>技术栈</b></summary>

| 层 | 用到的东西 | 做什么 |
|---|---|---|
| 语言 | Python 3.11+，代码只用标准库 | 整个框架。唯一的依赖是 yt-dlp，pip 安装时一起装上，只作为命令调用 |
| 下载 | yt-dlp（Unlicense）+ deno + 浏览器登录信息 | 取视频地址，子进程调用 |
| 按索引下载 | HTTP Range 请求，读 MP4 `sidx` 和 WebM Cues；HLS 读 `m3u8` 播放列表（都是标准库自己写） | 只下需要的字节或分片，断了接着下 |
| 媒体处理 | FFmpeg / ffprobe（LGPL 2.1+，视构建方式可能为 GPL） | 无损截取、拼接、检查，子进程调用 |
| 状态 | 每个项目一个 `meta.json` | 来源、要下的那一段、下载设置 |
| 质量 | `unittest`、Mermaid、Git | 测试、架构图、版本管理 |

Taneko 只调用这些工具，不打包它们的代码。请自行安装，并遵守各自的许可证。

</details>

## 使用提醒

- 只下你有权下载的内容。遵守平台条款和当地法律；转载前确认版权。
- 默认读取本机 Firefox 的登录信息（cookies），只在本地用，不写文件、不上传。
- 用 cookies 文件时，yt-dlp 会把网站更新的 cookies 写回这个文件；文件只在本地用，不上传。

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

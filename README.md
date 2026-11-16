# Taneko

*Stay with me, even when the connection drops.*

[![GitHub stars](https://img.shields.io/github/stars/coo1white/taneko?style=social)](https://github.com/coo1white/taneko)

> 下载长视频里的一段。断了接着下，不用重来。
> Download part of a long video. If it stops, run it again and it picks up where it stopped.

比如：一场 9 小时的直播，你只要第 3 局。Taneko 只下这一段；网断了，再跑一次同样的命令，它从断的地方接着下。

## 它能做什么

- **只下你要的一段**：写好开始和结束时间，只下这段，速度和下整条一样。
- **断了接着下**：断网、关机、链接过期，再跑一次就行，已下的部分不会丢。
- **旧的半截文件接着用**：以前没下完的文件放进项目文件夹，Taneko 找到它对应的时间，只补缺的部分。
- **画质不变**：不重新编码。下完自动检查画面有没有断档、声音有没有空白。

## 快速上手（5 分钟）

下面是最常见的用法：只下视频，不做字幕。

先建一个空文件夹（下文叫“你的文件夹”），在里面打开终端：Windows 用 PowerShell 或 cmd，macOS 和 Linux 用终端。下面所有命令都在这个文件夹里运行。

### 1. 装工具

| 工具 | 说明 |
|---|---|
| [Python](https://www.python.org/downloads/) 3.11 或更新 | 运行 Taneko |
| [FFmpeg](https://ffmpeg.org/download.html) | 截取和检查视频 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp#installation) 和 [deno](https://deno.com/) | 从网站取视频 |
| Firefox（可选） | Taneko 默认读取 Firefox 的登录信息，能下更多视频，比如会员视频 |

Windows 上可以一次装好（Python 另装）：

```bash
winget install Gyan.FFmpeg yt-dlp.yt-dlp DenoLand.Deno
```

### 2. 下载 Taneko

```bash
git clone https://github.com/coo1white/taneko.git
```

没有 git 时，在 GitHub 页面点 **Code → Download ZIP**，解压即可。

然后检查工具装齐没有：

```bash
python taneko/taneko.py doctor
```

缺什么，它会告诉你怎么装。这几项可以先不管：

- Whisper 和 llm-subtrans：只有做字幕才要。
- 项目目录：第 3 步才建。

Windows 上如果 `python` 不能用，换成 `py`。

### 3. 建一个项目

```bash
python taneko/taneko.py init game3 "https://www.youtube.com/watch?v=..." --section 4:13:00-5:08:00
```

- `game3`：项目名，也是下好的文件名（`game3.mkv`）。
- 网址：前后加英文引号，免得 `&` 之类的符号被终端误读。
- `--section`：开始-结束时间，可写 `4:13:00`、`13:00` 或 `780`（秒）。多短都行，比如 `4:13:00-4:14:00` 只下 1 分钟。不写就下整条视频。

它会在 `taneko` 文件夹旁边建好项目：

```text
你的文件夹/
├── taneko/              ← 第 2 步下载的代码
└── projects/
    └── game3/
        └── meta.json    ← 这个项目的设置
```

### 4. 下载

```bash
python taneko/taneko.py run game3
```

下好后，视频在 `projects/game3/game3.mkv`。屏幕最后会显示检查结果，例如：

```text
检查结果：视频时长 64.5 秒；音频从 4.5 秒到 64.5 秒
完成：projects/game3/game3.mkv
```

视频比你要的长几秒，这是正常的：画面要从开始时间之前最近的关键帧开始，才能不重新编码。声音正好从开始时间开始。检查没通过时，会显示“错误：”和原因，不会覆盖旧文件。

**中途断了？** 再跑一次同样的命令。

## 常见问题

**怎么看下到哪了？**
`python taneko/taneko.py status` 列出所有项目的进度。

**我有一个以前没下完的文件，能用吗？**
能。把它改名成 `name` 写的名字（例如 `game3.mkv`），放进项目文件夹，再跑 `run`。

**不用 Firefox？**
建项目时加 `--browser chrome`。写 `--browser none` 表示不读浏览器的登录信息。

**下载失败了？**
看屏幕上“错误：”后面的说明，照着做，再跑一次。还不行就[提一个 issue](../../issues)，附上屏幕上的输出。

## 进阶

<details>
<summary><b>所有命令</b></summary>

```bash
python taneko/taneko.py init game3 网址 --section 开始-结束   # 新建项目
python taneko/taneko.py run game3            # 跑完所有步骤，已完成的跳过
python taneko/taneko.py run .                # 在项目文件夹里运行；也可以给完整路径
python taneko/taneko.py status game3         # 一个项目的每一步
python taneko/taneko.py status --json        # 进度的 JSON 版，给脚本和 agent 读
python taneko/taneko.py fetch game3 --jobs 2 # 只跑下载这一步
python taneko/taneko.py doctor               # 检查工具
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

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：单独的 venv，建议用 CUDA 显卡。在 `config/asr.json` 的 `home` 里写它的目录。
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
python taneko/taneko.py approve game3 terms   # 术语校对完
python taneko/taneko.py approve game3 spot    # 抽查完
python taneko/taneko.py translate game3 --test  # 先试翻译风格
```

单个步骤也能单独跑：`fetch / subs / asr / terms / fix / translate / check`。

**API 密钥**只放在环境变量 `OPENCODE_API_KEY`，不写进项目文件：

```bash
python taneko/taneko.py key set      # 保存（输入时不显示）
python taneko/taneko.py key status   # 只显示有没有、多长、从哪来
python taneko/taneko.py key check    # 问一次服务器密钥是否有效（用 1 个 token）
python taneko/taneko.py key clear    # 删除
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

- 项目默认在代码文件夹旁边的 `projects/`；翻译工具默认在旁边的 `workflow/vendor/`。
- 用环境变量改位置：`TANEKO_ROOT`、`TANEKO_PROJECTS`、`TANEKO_CONFIG`、`TANEKO_VENDOR`。
- 转写设置在 `config/asr.json`；翻译设置（接口、模型、分段大小）在 `config/translate.json`。

</details>

<details>
<summary><b>测过什么（诚实版）</b></summary>

| 在真实环境测过 | 还没测过 |
|---|---|
| 分段下载、半截文件对齐、拼接：一局 55 分钟的 1440p60 视频，复用 41 分钟的旧文件，对齐误差 0.00，视频无断档。2026-11-16 前拼的文件接缝处有 0.5～3.5 秒没声音，已修复（issue [#1](../../issues/1)） | 转写、术语校对、翻译（实验性，暂停开发） |
| 按索引下载一段（issue [#8](../../issues/8)）：YouTube 1440p60，中途强行停掉再跑，从已下的 160 MiB 接着下；画面和整条下载逐字节相同，音画差 5～21 毫秒；约 8 MiB/s（分段下载约 2 倍实时） | B 站、X 等网站的按索引下载 |
| Windows 上按索引下载：用 Firefox 登录信息，格式 308+140 跑了 3 次都成功，每次约 50 秒（分段下载 176 秒）；默认格式（AV1 + Opus）照快速上手走了一遍 | macOS、Linux 上的真实下载（只有自动测试） |
| 多片同时下载（`--jobs 2`）：同一场比赛的另外 4 段 | |
| 流程、人工检查点、退出码、分段翻译：有自动测试 | |

已知问题：

- 在新电脑上安装还不方便：issue [#5](../../issues/5)。
- 字幕的已知问题随字幕一起暂停，见 [ROADMAP.md](ROADMAP.md) 的“暂停”一节。

全部问题见 [Issues](../../issues)，计划见 [ROADMAP.md](ROADMAP.md)，架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

</details>

<details>
<summary><b>技术栈</b></summary>

| 层 | 用到的东西 | 做什么 |
|---|---|---|
| 语言 | Python 3.11+，只用标准库 | 整个框架，没有第三方 Python 依赖 |
| 下载 | yt-dlp（Unlicense）+ deno + 浏览器登录信息 | 取视频地址，子进程调用 |
| 按索引下载 | HTTP Range 请求，读 MP4 `sidx` 和 WebM Cues（标准库自己写） | 只下需要的字节，断了接着下 |
| 媒体处理 | FFmpeg / ffprobe（LGPL 2.1+，视构建方式可能为 GPL） | 无损截取、拼接、检查，子进程调用 |
| 语音识别 | faster-whisper + CTranslate2，large-v3，CUDA，失败时退回 CPU | 本地转写 |
| 翻译 | llm-subtrans + OpenAI 兼容接口（只测过 OpenCode） | 按术语表翻译；每 200 条存一次，中断后只补没译完的 |
| 状态 | 每个项目一个 `meta.json`；`config/*.json` | 项目设置、术语表、检查点记录 |
| 质量 | `unittest`、Mermaid、Git | 测试、架构图、版本管理 |

Taneko 只调用这些工具，不打包它们的代码。请自行安装，并遵守各自的许可证。

</details>

## 使用提醒

- 只下你有权下载的内容。遵守平台条款和当地法律；转载前确认版权。
- 默认读取本机 Firefox 的登录信息（cookies），只在本地用，不写文件、不上传。

## 致敬 BitTorrent

灵感来自 BitTorrent：把大事切成小片，每片单独检查，断了只补缺的。名字 たね子 是“种子”加昭和女孩名常用的“子”。种子就是断了之后留下的半截文件，它会被接着用。
献给陪我们长大的 BT 下载，感谢 Bram Cohen 和 BitTorrent 社区。

本项目没有 P2P，不会更快（价值在于不丢进度），不是 BitTorrent 的实现或客户端，与 BitTorrent, Inc. 无关。

> Inspired by BitTorrent: split a big job into pieces, check each one, and redo only what is missing. Taneko (たね子) means "seed" with the old Showa-style "-ko" ending; the seed is the half-finished file a broken download leaves behind. Thanks to Bram Cohen and the BitTorrent community. No P2P; not a BitTorrent client; not affiliated with BitTorrent, Inc.

## 许可证

[MIT 许可证](LICENSE)：可以自由使用、修改、分发，保留版权声明即可。

如果它帮你省了时间，欢迎点右上角的 ⭐ **Star**。这是请求，不是使用条件。

> If taneko saved you time, a ⭐ is the best thanks. It's a request, not a license condition.

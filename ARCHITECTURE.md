# taneko 架构

## 1. 核心只有一个概念：阶段

流程里的每一步都是一个阶段（`core.Stage`），一个阶段一个文件，只回答四个问题：

| 字段 | 回答 |
|---|---|
| `name` / `label` | 叫什么 |
| `done(项目目录, meta)` | 做完了吗（只在这里定义一次） |
| `run(参数)` | 怎么做；人工检查点没有 `run` |
| `args(子命令)` | 单独运行时的选项；`run` 调用它时用的也是这些默认值 |

另有两个可选字段：`skip(meta)` 表示这个项目不需要这一步，`hint(...)` 给出人工检查点要人做什么。

加一个阶段 = 在 `stages/` 里加一个文件，并把它放进 `flow.STAGES` 和 `flow.plan`。

> 字幕相关的阶段（asr、subs、terms、fix、translate、check 和两个人工检查点）是实验性功能，暂停开发，见 ROADMAP 的“暂停”一节。架构不变，它们照常能跑。

## 2. 分层

```
cli          命令行：run / status / approve / key，加上每个阶段的单独命令
 └ flow      排顺序、跳过做完的、在人工检查点停下；不知道任何阶段的内部
    └ stages fetch · asr · subs · terms · fix · translate · check · gates
       └ project · srt · keys · stitch · ranges · hls
          └ core   路径、退出码、错误、Stage 约定、外部工具
workers/     在 taneko 之外的环境里运行的脚本（如 Whisper 的 venv），可以用第三方包
```

规则（测试 `Layers` 会检查）：

- 依赖只往下走，下层不引用上层。
- 阶段之间互不引用。
- 阶段出错只抛出 `core.Fail`，不自己退出程序；由 `cli` 打印“错误：……”，并以退出码 1 退出。

外部工具都以子进程调用，不链接：fetch 用 yt-dlp、ffmpeg 和浏览器 cookies；asr 用 Whisper（`taneko/config/asr.json` 的 `home`）；translate 用 llm-subtrans（`TANEKO_VENDOR`）和 API 密钥（环境变量）。

## 3. 一次 `run`

```mermaid
flowchart TD
    A[fetch 下载视频] --> B[asr 或 subs 生成 en.srt]
    B --> C[terms 找专有名词]
    C --> G1{{人工：校对术语<br/>填 corrections}}
    G1 -->|approve terms| D[fix 批量改英文字幕]
    D --> E[translate 翻译成 zh.srt]
    E --> F[check 检查对应]
    F --> G2{{人工：抽查关键片段}}
    G2 -->|approve spot| H([完成])
    B -.中文原文，到此结束.-> H
```

- 每一步先问 `done`：做完了就跳过，没做完就执行。所以重跑同一条命令，就是接着跑。
- 停在人工检查点时，退出码是 10；全部完成是 0；出错是 1；参数不对是 2。

## 4. 项目文件夹 `projects/<项目>/`

命令里的项目可以是名字，也可以是路径（含 `/` 或 `\`，或者就是 `.`）。名字在 `projects/` 下最多 3 层里找，`_` 和 `.` 开头的文件夹跳过；同名的有多个时报错，不猜。`run` 只找一次，之后把路径交给各阶段。

```
meta.json        项目配置：来源、片段范围、术语表、检查点放行记录（review）
<name>.mkv       下载完成的视频
_parts/          下载中的分片（完成后自动删除）
en.srt           英文字幕（转写或抓取）；en.srt.orig 是 fix 之前的备份
terms.txt        高频专有名词清单
_translate/      分段翻译的中间结果，重跑时跳过已译完的段
zh_raw.srt       合并后的译文；zh.srt 是最终的中文字幕（时间轴沿用 en.srt）
```

## 5. 每个阶段的“做完了”

| 阶段 | 做完了 |
|---|---|
| fetch | 有视频、没有 `_parts`、时长不比预期短（长视频容差 25 秒，短的按 1%；和下载代码自己的判断还不一致，见 issue #1） |
| asr / subs | `en.srt`（中文原文是 `zh.srt`）存在且非空 |
| terms | `terms.txt` 存在 |
| ⏸ 术语 | `meta.review.terms` 为真 |
| fix | 没有 corrections 就跳过；否则 `en.srt.orig` 存在 |
| translate | `zh.srt` 存在 |
| check | 中英条数、时间轴一一对应，字数不超读速 |
| ⏸ 抽查 | `meta.review.spot` 为真 |

## 6. fetch：按索引下载、分片下载与续传

只下一段时，先按索引下载（`ranges.py`）：用 yt-dlp 取格式的地址，读 MP4 的 `sidx` 或 WebM 的 Cues，算出这段时间的字节范围，用 HTTP Range 每次 10 MiB 顺序下到 `_parts/*.part`，旁边的 `.json` 记着范围，重跑从已下的字节接着下。下完用 ffmpeg 不重新编码地切到这一段（视频从起点前的关键帧开始，音频也从这个关键帧下、从这里开始，开头才不会没声音），`verify` 通过才替换成品。格式是 HLS 播放列表（例如 X）时按播放列表下载（`hls.py`）：只下覆盖这一段的分片，一片一个文件，重跑跳过已下完的，下完按顺序拼成一个文件再切；分片的时间戳可能不从 0 开始，切的时候用视频第一片对齐播放列表的时间。两种都不行（直播、加密、按字节范围存放的分片），或加了 `--sections`，才走下面的分片下载。

```mermaid
flowchart TD
    S[读取范围 / 已有半截文件] --> P[规划分片，每片 600 秒]
    P --> T[先试探 20 秒：确认时间戳]
    T --> L[逐片下载 -copyts]
    L --> V{校验起止与关键帧}
    V -->|失败| R[删除该片并重试]
    R --> L
    V -->|通过| M[全部完成？]
    M -->|否| L
    M -->|是| ST[与旧半截文件画面对齐 + 关键帧无缝拼接]
    ST --> CK{时间戳连续？}
    CK -->|是| OUT[输出 name.mkv，清理分片]
    CK -->|否| KEEP[保留分片，报错]
```

## 7. 不在本仓库的部分

作者旧的工作流脚本里还有一些功能，暂未迁入：画质检查（4K / Hi-Res）、章节、B 站上传和字幕轨、登录。
llm-subtrans 也不在本仓库，taneko 通过 `TANEKO_VENDOR` 找到它。

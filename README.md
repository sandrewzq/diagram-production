# Diagram Production

用一份 JSON 描述图的结构，坐标全部由代码算，画完立即自检。

给 agent 或人用的业务/技术图渲染器。不用拖拽、不手写 SVG 坐标：你只写「谁、在哪条泳道、接哪一步」，节点位置、泳道高度、连线折点、箭头落点全部自动算。改图只改 JSON 一行，不用重排整张图。输出是自带内联 SVG 的单文件 HTML，可以直接嵌进汇报文档。

零第三方依赖，纯 Python 标准库，macOS / Linux / Windows 都能跑。

---

## 支持哪些图

一共 8 类，共用同一套「节点 + 连线」数据模型，区别只在泳道和节点样式的组织方式。

| 图类型 | 什么时候用 | 主要元素 | 示例 |
| --- | --- | --- | --- |
| 流程图 Process flow | 读者要看清动作顺序和判断分支 | 处理节点、判断节点、出口 | 参考 `examples/swimlane.json` |
| 泳道图 Swimlane | 读者要知道每一步由谁、跨哪个边界完成 | 泳道、处理节点、跨泳道连线 | `examples/swimlane.json` |
| 系统关系图 System map | 读者要看清系统之间、系统与外部服务的关系 | 角色、系统、外部服务、依赖 | `examples/system-map.json` |
| 架构图 Architecture | 读者要看清分层、部署单元、逻辑边界 | 容器、组件、边界 | 参考 `examples/system-map.json` |
| 数据流图 Data flow | 读者要知道信息怎么流动、在哪被加工 | 数据源、加工、存储、消费方 | `examples/data-flow.json` |
| 生命周期 Lifecycle | 读者要知道状态和允许的流转 | 状态节点、带标签的流转 | `examples/lifecycle.json` |
| 时序图 Sequence | 读者要知道消息按时间先后怎么往返 | 参与者、按序的请求与响应 | `examples/sequence.json` |
| 概览图 Overview | 读者要一张紧凑的全景，看几个部分怎么关联 | 分组节点、连线、短标签 | 参考 `examples/system-map.json` |

`type` 字段只是描述性标签，写什么都不会影响渲染；真正决定画法的是你给了 `lanes`（走泳道布局）还是 `participants` + `messages`（走时序布局）。

**什么时候该拆图**：一张图出现两个以上主要阅读方向、或者连线交叉多到看不清，就拆成几张各自聚焦的图。泳道只在「责任归属」或「系统边界」是这张图要讲的东西时才加。

---

## 环境要求

- **Python 3.9 或更高**。没有任何第三方包，不用 `pip install`，没有编译扩展。
- **浏览器（仅导出 PNG 时需要）**。`--png` 会调起 Chromium 系浏览器无头截图，查找顺序：
  1. 环境变量 `CHROME_BIN`（也认 `BROWSER_BIN`）
  2. PATH 里的 `google-chrome`、`google-chrome-stable`、`chromium`、`chromium-browser`、`chrome`、`msedge`、`microsoft-edge`、`microsoft-edge-stable`、`brave-browser`
  3. 各平台常见安装路径：macOS 的 Chrome / Chromium / Edge，Linux 的 `/usr/bin` 与 `/snap/bin/chromium`，Windows 的 `Program Files` 和 `Program Files (x86)` 下 Chrome 与 Edge

  一个都找不到时，HTML 照常写出，PNG 跳过，退出码 2 并提示设置 `CHROME_BIN`。装在非默认目录就手动指定：

  ```bash
  CHROME_BIN="/your/path/to/chrome" python3 scripts/diagram.py spec.json -o out.html --png out.png
  ```

- **字体不用装**。文字宽度按估算（中文 1.0 字宽、英文 0.52 字宽），布局不依赖具体字体；只有 PNG 里的字形会跟随浏览器实际解析到的字体。

---

## 快速开始

```bash
# 1. 画一张泳道图，同时跑校验
python3 scripts/diagram.py examples/swimlane.json -o build/swimlane.html --check

# 2. 顺手导一张 PNG
python3 scripts/diagram.py examples/swimlane.json -o build/swimlane.html --png build/swimlane.png

# 3. 只校验，不写文件
python3 scripts/diagram.py examples/swimlane.json --check

# 4. 跑回归测试（6 份示例往返 + 异常输入 + 版本检查）
python3 tests/test_roundtrip.py
python3 tests/test_update.py
```

命令参数：

| 参数 | 作用 |
| --- | --- |
| `spec` | 输入的 JSON 文件（必填） |
| `-o` / `--output` / `--out` | 输出的 HTML 路径；不写且带 `--png` 时按 PNG 文件名推导 |
| `--png` | 额外导出一张 PNG |
| `--check` | 只校验，有问题退出码 1 |
| `-q` / `--quiet` | 不打印过程信息 |

---

## 版本与更新

仓库发新版本时，本机会知道，但**不会自己动任何东西**。

```bash
python3 scripts/check_update.py
```

- 当前是最新版：**什么都不打印**，退出码 0。
- 上游有新版本：打印三行——新版本号、Release 链接、一条 `git pull --ff-only` 命令。是否执行由你决定。
- 同一个新版本只提示一次，之后静默，除非加 `--always`。

机制：

| 项 | 做法 |
| --- | --- |
| 本地版本 | 读 `SKILL.md` 里的 `metadata.version` |
| 远端版本 | GitHub 的 latest release，取不到就退到最新 tag |
| 缓存 | `~/.cache/diagram-production/update-check.json`，24 小时有效 |
| 网络失败 | 静默返回 0，不重试、不报错、不阻塞画图 |
| 缓存过期 + 联网失败 | 静默。过期的版本信息不当成事实 |
| 完全关闭 | 环境变量 `DIAGRAM_PRODUCTION_NO_UPDATE_CHECK=1` |

可选参数：`--quiet`（只更新缓存不打印）、`--always`（忽略"已提示过"）、`--ttl=秒`（改缓存有效期）、`--repo=OWNER/NAME`（换检查的仓库）。

给 agent 用的时候，这一节写在 `SKILL.md` 最前面：每次会话第一次画图前跑一次 `check_update.py`，有输出就转述给用户，然后**继续干活**，不等确认。

---

## 数据格式

### 泳道图 / 流程图 / 系统关系图等

```json
{
  "type": "swimlane",
  "title": "示例审批流",
  "subtitle": "一句话说明这张图讲什么",
  "lanes": [
    {"id": "people", "name": "业务方", "sub": "发起与确认", "style": "people"},
    {"id": "platform", "name": "平台", "sub": "系统处理", "style": "platform"}
  ],
  "nodes": [
    {"id": "submit", "lane": "people", "column": 0, "kind": "actor", "title": "提交申请", "sub": "补齐必填信息"},
    {"id": "check", "lane": "platform", "column": 1, "kind": "decision", "title": "校验通过？", "sub": "必填项检查"},
    {"id": "done", "lane": "platform", "column": 2, "kind": "state", "title": "已完成", "sub": "记录结果"}
  ],
  "edges": [
    {"from": "submit", "to": "check"},
    {"from": "check", "to": "done", "label": "通过"},
    {"from": "check", "to": "submit", "label": "不通过", "kind": "return"}
  ]
}
```

关键点：**`column` 决定横向阅读顺序，`lane` 决定纵向归属，坐标不要写**。渲染器按列宽和泳道内容自动排布。

字段说明：

- `lanes`（可选）：每条泳道有 `id`、可见的 `name`，可选 `sub`、`style`、`fill`、`stroke`。
- `nodes`：每个节点需要稳定的 `id`、可见的 `title`，可选 `sub`、`meta`、`tag`、`kind`、`lane`、`column`、`width`、`height`、`fill`、`stroke`。
- `columns`：手写紧凑格式，每列有可选 `stage` 和 `nodes` 列表，渲染器会转成带列号的节点。两种写法都接受。
- `edges`：需要 `from` 和 `to`，可选 `label`、`kind`、`color`、`route`、`label_at`。新图不要写 `route`，让自动走线处理。
- `legend`（可选）：`{label, color}` 列表，用来解释颜色约定。

节点样式 `kind` 可选值（决定配色）：

| kind | 用途 |
| --- | --- |
| `actor` | 角色、人 |
| `process` | 普通处理步骤 |
| `decision` | 判断分支 |
| `system` | 系统 |
| `external` | 外部系统或外部方 |
| `state` | 状态 |
| `data` | 数据、存储 |
| `note` | 备注 |

连线样式 `kind` 可选值：`flow`（主路径）、`return`（回退）、`request`、`response`、`dependency`、`external`。后四种会用不同线型区分，并应在图例或注释里说明。

泳道配色 `style` 可选值：`people`、`platform`、`external`，以及旧版遗留的 `yc`（蓝）、`pf`（青）、`ext`（紫虚线）。

### 时序图

时序图不用 `lanes` + `nodes`，改用 `participants` + `messages`：

```json
{
  "type": "sequence",
  "title": "一次请求的往返",
  "participants": [
    {"id": "caller", "title": "调用方", "cls": "hm"},
    {"id": "service", "title": "服务", "cls": "pf"},
    {"id": "store", "title": "数据存储", "cls": "ext"}
  ],
  "messages": [
    {"from": "caller", "to": "service", "label": "请求"},
    {"from": "service", "to": "store", "label": "读数据"},
    {"from": "store", "to": "service", "label": "结果", "kind": "response"},
    {"from": "service", "to": "caller", "label": "响应", "kind": "response"}
  ],
  "annotations": [
    {"text": "响应里带着存储返回的结果。"}
  ]
}
```

参与者框、竖向生命线、消息行、箭头方向、响应线型、标签位置、注释框全部自动算。`kind` 用 `response` 或 `return` 时线变虚线并指回发起方。

`annotations` 不写 `y` 时自动排在对应消息行的下方（第一条注释跟在第 1 行后面）。校验器会拦下压住参与者框、超出画布、装不下文字的注释。

---

## 自动校验

每次渲染完自动跑，共 25 条规则，发现问题打印出来并把退出码设为 1。

**通用几何**

| 规则 | 拦什么 |
| --- | --- |
| `node-overlap` | 两个节点框重叠 |
| `edge-cross` | 连线穿过无关节点的框 |
| `edge-too-close` | 连线离节点框不到 10 像素 |
| `label-overlap` | 两个标签互相压住 |
| `label-out-of-viewbox` | 标签超出画布 |
| `label-lane-boundary` | 标签压在泳道分隔线上 |
| `arrow-off-border` | 箭头落点不在目标节点边框上 |
| `arrow-runs-along-target-border` | 箭头沿着目标边框走，看起来像在挤压节点 |
| `arrow-short-approach` | 箭头最后一段短于 12 像素，指向不明 |
| `arrow-short-dogleg` | 箭头前一格里有个不到 20 像素的横向侧移，最后一段又不超过 30 像素，看起来像抖了一下 |
| `text-overflow` | 单个不可断的词宽过节点内宽 |
| `text-too-dense` | 折行数超过该位置上限，节点被撑高 |

**节点与判断**

| 规则 | 拦什么 |
| --- | --- |
| `lane-overflow` | 节点超出所属泳道带 |
| `decision-without-path` | 判断节点没有出口 |
| `decision-outcome-unlabeled` | 判断节点的出口没写结果标签 |

**时序图**

| 规则 | 拦什么 |
| --- | --- |
| `participant-overlap` | 参与者框重叠 |
| `lifeline-out-of-viewbox` | 生命线超出画布 |
| `message-order` | 消息行没有自上而下递增 |
| `message-zero-length` | 消息起点终点重合 |
| `message-out-of-viewbox` | 消息超出画布 |
| `message-endpoint-misaligned` | 消息端点没落在生命线上 |
| `message-outside-lifelines` | 消息跨到了参与者之外 |
| `annotation-out-of-viewbox` | 注释框超出画布 |
| `annotation-text-overflow` | 注释框装不下文字 |
| `annotation-overlap` | 注释框压住参与者 |

校验器只查几何和结构，**查不出业务含义对不对**。它在判断上刻意保守：过了校验只说明画得没毛病，节点和连线是否忠实于事实，要人自己对着原文核一遍。

---

## 反解已有的图

`extract_svg.py` 把一个现成的 HTML/SVG 图解析回 JSON，让你能在原图基础上改，而不是从零重画。

```bash
# 反解第 1 张图
python3 scripts/extract_svg.py old.html --svg-index 0 -o build/extracted.json

# 一个文件里有多张图时全部反解
python3 scripts/extract_svg.py report.html --all -d build/extracted

# 改了之后重新渲染
python3 scripts/diagram.py build/extracted.json -o build/rebuilt.html --check

# 比对新旧两张图的结构是否一致
python3 scripts/verify_render.py old.html build/rebuilt.html
```

`verify_render.py` 逐个比对元素坐标，输出最大偏差和是否一致：

```
elements: source 35 / rendered 35
maximum coordinate drift: 1.00px
result: MATCH
```

参数 `--tolerance` 改容差，`--svg-index` 指定源图的第几张，`--rendered-svg-index` 指定渲染结果的第几张（默认跟源图一致，源图只有一张时用 0）。

反解出来的 JSON 带 `_legacy_extracted: true` 标记。有些信息（比如判断节点每个出口的文字）在像素和 SVG 文本里已经丢了，反解会打 `warning` 提示，不会假装恢复了。

---

## 退出码

| 脚本 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| `diagram.py` | 成功 | `--check` 发现问题 | 读不了文件，或 spec 里没有任何可画的元素（仍会写出空图并打 warning） |
| `extract_svg.py` | 成功 | 参数或结构问题 | 读不了文件，或没识别出任何图形（写 `type: unknown`） |
| `verify_render.py` | 一致（MATCH） | 不一致（DIFFERENT） | — |

---

## 目录结构

```
SKILL.md                     agent 使用说明
README.md                    本文件
agents/openai.yaml           Codex skill 元数据
scripts/
  diagram.py                 渲染 + 校验（主入口）
  extract_svg.py             从已有 HTML/SVG 反解出 JSON
  verify_render.py           比对两张图的结构
  check_update.py            查上游有没有新版本（只读，不动文件）
examples/                    6 份可直接运行的示例
references/
  diagram-types.md           怎么选图类型
  spec-format.md             JSON 字段全集
  layout-rules.md            布局约定
  quality-gates.md           交付前的检查清单
  legacy-svg.md              旧格式判定规则
tests/
  test_roundtrip.py          渲染 → 反解 → 重渲染的一致性回归
  test_update.py             版本检查（离线运行，不联网）
```

---

## 交付前的检查清单

1. 每条连线都指向存在的节点。
2. 节点 id 唯一且有语义。
3. 节点不重叠、不越出泳道。
4. 连线不穿过无关节点。
5. 每个判断节点都有出口标签，且每个有意义的结果都有路径。
6. 回退、响应、依赖、外部连线用了不同线型，并在图例或注释里解释。
7. 文字装得下节点，长解释挪到注释。
8. 主路径能顺着一个方向读完。
9. 在目标视口里实际看一眼，确认没有裁切、没有指不明白的箭头。

---

## 许可证

MIT，见 [LICENSE](LICENSE)。

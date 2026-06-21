# 儿童绘本工坊（PictureBook-Agent）

> 面向儿童创意表达场景的多工具绘本生成智能体。  
> 用户输入主角、故事想法、页数和绘本风格后，系统自动完成 **安全审核 → 故事规划 → 人机协同编辑 → 提示词优化 → 图像生成 → 角色一致性控制 → 绘本排版 → 本地书架保存**。

本项目基于 **DeepSeek 文本生成模型** 与 **千问 / DashScope 图像生成模型** 构建，采用 **Plan-and-Execute + Human-in-the-loop** 智能体设计模式，面向《人工智能基础》课程的智能体项目工程实践要求进行设计和实现。

---

## 项目简介

儿童在进行绘本创作时，常常有丰富的想象力，但缺少完整故事组织能力、绘画能力和排版能力。本项目希望降低儿童绘本创作门槛，让用户只需要输入一句故事想法，即可生成一本结构完整、画风统一、适合儿童阅读的绘本。

系统支持：

- 输入主角描述、故事想法、页数和绘本风格
- 自动生成分页故事脚本
- 用户二次编辑故事标题、文字和场景描述
- 生成 3 张首页候选图供用户选择
- 基于用户选中的首页作为参考图，保持后续页面角色一致
- 自动完成图片与文字排版
- 保存到本地书架，支持历史绘本查看
- 加入伦理合规模块，拦截儿童不适内容、Prompt 注入和隐私泄露风险

---

---

## 项目结构

```
PictureBook-Agent/
├── app/                          # 应用入口层（Web UI）
│   └── collect_input_web.py      # Flask Web 前端（主入口）
│
├── agent/                        # Agent 编排层（流程调度）
│   ├── easy_storybook.py         # 简单模式：想法 → DeepSeek 写故事 → 生图
│   └── generate_from_yaml.py     # YAML 模式：从 story_input.yaml 生成绘本
│
├── services/                     # 服务层（原子能力模块）
│   ├── storybook_generator.py    # 核心生图引擎 + 排版输出
│   ├── prompt_optimizer.py       # 提示词优化器（中文 → 英文 SD 提示词）
│   └── safety_guard.py           # 伦理合规与安全防护
│
├── tools/                        # 工具层（API 客户端封装）
│   └── qwen_client.py            # 千问 Image API 客户端
│
├── config/                       # 配置层
│   ├── __init__.py               # load_config() 统一配置加载入口
│   └── config.yaml               # API Key、模型、风格、一致性参数
│
├── scripts/                      # 脚本层
│   ├── run.bat                   # 一键启动
│   └── setup_env.bat             # 环境安装
│
├── storybooks/                   # 绘本输出目录
├── requirements.txt
└── README.md
```

---

## 快速开始

### 1. 安装依赖

```powershell
# 方式一：使用安装脚本
scripts\setup_env.bat

# 方式二：手动安装
pip install -r requirements.txt
```

### 2. 配置 API Key

编辑 `config/config.yaml`，填入你的 API Key：

```yaml
qwen:
  api_key: "sk-xxxxxx"        # DashScope API Key（千问图片生成）

deepseek:
  api_key: "sk-xxxxxx"        # DeepSeek API Key（故事创作）
```

也可以通过环境变量配置：

| 环境变量 | 用途 |
|----------|------|
| `DASHSCOPE_API_KEY` | 千问图片生成 |
| `DEEPSEEK_API_KEY` | 故事创作 |

DashScope API Key 申请：https://dashscope.console.aliyun.com/apiKey

### 3. 运行

```powershell
# 方式一：一键启动（推荐）
scripts\run.bat

# 方式二：手动启动
python app\collect_input_web.py
```

启动后访问：http://127.0.0.1:5001

---

## 架构设计

```
用户输入 (Web UI)
  │
  ▼
DeepSeek API (故事创作)
  │  生成 JSON: {title, pages: [{text, scene}]}
  ▼
PromptOptimizer (提示词优化)
  │  中文场景 → 英文关键词映射 + 氛围扩写
  ▼
千问 Image API (图片生成)
  │  第1页: wan2.6-t2i 文生图
  │  第2页起: wan2.6-image 参考图模式（保角色换场景）
  ▼
PIL 排版 (绘本合成)
  │  图片 + 文字 + 页码 → 1024x1280 绘本页
  ▼
输出文件 (storybooks/)
```

### 分层职责

| 层 | 目录 | 职责 | 核心文件 |
|----|------|------|----------|
| **应用入口** | `app/` | Web UI、HTTP 路由、前端交互 | `collect_input_web.py` |
| **Agent 编排** | `agent/` | 端到端流程调度、多步骤串联 | `easy_storybook.py`, `generate_from_yaml.py` |
| **服务层** | `services/` | 原子业务能力（生图、优化提示词、安全检查） | `storybook_generator.py`, `prompt_optimizer.py`, `safety_guard.py` |
| **工具层** | `tools/` | 第三方 API 客户端封装 | `qwen_client.py` |
| **配置层** | `config/` | 集中管理所有配置参数 | `config.yaml` |
| **脚本层** | `scripts/` | 环境安装、启动脚本 | `run.bat`, `setup_env.bat` |

---

## 角色一致性机制

跨页面保持主角形象统一的核心方案：

| 策略 | 原理 | 适用模型 |
|------|------|----------|
| **参考图模式**（默认） | 第1页纯文生图，第2页起将第1页图片作为参考传入 `wan2.6-image`，保持角色一致同时更换场景 | wan2.6 |
| **seed 模式** | 所有页面使用相同随机种子 + 角色描述前缀 | 所有模型 |

配置方式（`config/config.yaml`）：

```yaml
consistency:
  mode: "reference"    # 参考图模式（推荐）
  # mode: "seed"       # 种子模式（兼容所有模型）
```

参考图模式通过三层手段实现"保角色换场景"：
1. 专用 prompt 结构三次强调"角色一致、场景不同"
2. 关闭 `prompt_extend` 防止模型偏向参考图场景
3. 负面提示词排除 "same background as reference"

---

## 核心模块说明

### `tools/qwen_client.py` — 千问 API 客户端

封装 DashScope 图像生成的三种调用方式：

| 函数 | 作用 |
|------|------|
| `get_api_key()` | 获取 DashScope API Key（config → 环境变量 → 运行时输入） |
| `generate_image_with_qwen()` | 异步文生图（wanx2.1 系列），提交任务 → 轮询 → 下载 |
| `generate_image_sync()` | 同步文生图（wan2.6 / wan2.5 系列），一次请求返回结果 |
| `generate_image_with_reference()` | 参考图生图（wan2.6-image），传入参考图保持角色一致 |
| `_is_wan26_model()` | 判断是否为 wan2.6/2.5 同步 API 模型 |

### `services/storybook_generator.py` — 核心生图引擎

负责模型选择、绘本生成、排版输出的核心业务逻辑：

| 函数 | 作用 |
|------|------|
| `generate_storybook()` | 生成完整绘本，第1页文生图，第2页起参考图模式 |
| `create_layout_page()` | 图片+文字合成排版（1024x1280 画布） |
| `build_qwen_prompt()` | 构建千问专用简洁 prompt |
| `_build_reference_prompt()` | 构建参考图模式专用 prompt |
| `revise_pages()` | 生成后选择页面重新生成 |

### `services/prompt_optimizer.py` — 提示词优化器

将用户中文口语描述转换为专业英文提示词：

| 方法 | 作用 |
|------|------|
| `optimize()` | 主优化函数：关键词映射 + 场景扩写 + 质量标签 |
| `analyze_keywords()` | 按长度优先匹配 8 类关键词映射库 |
| `expand_scene()` | 根据情绪/时间/室内外自动补充氛围描述 |
| `generate_negative()` | 智能生成负面提示词 |

关键词映射库覆盖：30 个地点、24 种动物、14 种人物、26 种动作、18 种情绪、16 种时间、29 种物品、8 种构图。

### `services/safety_guard.py` — 安全防护模块

| 功能 | 说明 |
|------|------|
| 儿童友好内容检测 | 暴力、血腥、色情、自伤、仇恨、危险内容 |
| Prompt 注入/越狱检测 | 忽略规则、泄露系统提示词、DAN 等攻击 |
| 隐私保护 | 手机号、邮箱、身份证号等个人信息脱敏 |
| 审计日志 | 记录每次安全检查结果 |

### `agent/easy_storybook.py` — 简单模式 Agent

用户只需输入一句话想法，由 DeepSeek 自动生成故事脚本，再调用千问生图。

### `agent/generate_from_yaml.py` — YAML 模式 Agent

从 `story_input.yaml` 读取输入，支持分步生成：故事 → 候选首页 → 用户选择 → 后续页面。

### `app/collect_input_web.py` — Web 前端

Flask 应用，提供完整的 Web UI：输入表单 → 故事编辑 → 候选图选择 → 绘本查看器 → 书架管理。

---

## 输出说明

运行后，绘本文件保存在 `storybooks/storybook_YYYYMMDD_HHMMSS/` 目录下：

```
storybook_20260620_010138/
├── page_01.png           # 原始生成的图片
├── page_02.png
├── layout_01.png         # 排版后的绘本页（图片+文字）
├── layout_02.png
├── story_input.yaml      # 用户输入
└── story_script.json     # 故事脚本（标题、想法、角色、各页内容）
```

---

## 配置说明

所有配置集中在 `config/config.yaml` 中：

| 配置项 | 说明 |
|--------|------|
| `qwen.api_key` | DashScope API Key |
| `qwen.base_url` | DashScope API 地址 |
| `qwen.default_model` | 默认文生图模型 |
| `qwen.ref_model` | 参考图专用模型 |
| `qwen.models` | 可用模型列表 |
| `deepseek.api_key` | DeepSeek API Key |
| `deepseek.base_url` | DeepSeek API 地址 |
| `style_templates` | 4 种绘本风格（水彩/卡通/蜡笔/剪纸） |
| `consistency.mode` | 角色一致性策略 |
| `consistency.fixed_seed` | 固定随机种子 |

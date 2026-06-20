# 儿童绘本生成器

基于千问 Image 模型（DashScope API）+ DeepSeek AI 的自动化儿童绘本生成工具。

用户只需输入一个故事想法，系统自动完成：**故事创作 → 图片生成 → 排版输出**，生成完整的绘本。

---

## 项目结构

```
A_user/
├── easy_storybook.py        # 简单模式入口（推荐）
├── storybook_generator.py   # 核心生图引擎
├── prompt_optimizer.py      # 提示词优化器
├── run.py                   # API 连通测试（旧）
├── test_qwen_api.py         # 千问 API 连通测试
├── generate_easy.py         # 生成脚本（开发用）
├── test_fix.py              # 修复测试
├── api_outputs/             # 测试图片输出
├── output/                  # 旧版输出目录
└── storybooks/              # 绘本输出目录（运行后生成）
```

---

## 快速开始

### 1. 安装依赖

```powershell
pip install requests Pillow
```

### 2. 配置 API Key

| API Key | 用途 | 配置位置 |
|---------|------|----------|
| DashScope API Key | 千问图片生成 | `storybook_generator.py` 顶部 `QWEN_API_KEY` |
| DeepSeek API Key | 故事创作（仅简单模式） | `easy_storybook.py` 顶部 `DEEPSEEK_API_KEY` |

DashScope API Key 申请：https://dashscope.console.aliyun.com/apiKey

### 3. 运行

```powershell
# 简单模式（推荐）：输入想法 → AI自动写故事 → 生图
python easy_storybook.py

# 手动模式：自己逐页输入故事和场景描述
python storybook_generator.py
```

---

## 运行流程

```
简单模式 (easy_storybook.py)
│
├─ 1. 获取 DeepSeek API Key
├─ 2. 选择千问图片模型 (wan2.6-t2i / wan2.5 / wanx2.1)
├─ 3. 选择绘本风格 (水彩 / 卡通 / 蜡笔 / 剪纸)
├─ 4. 输入主角描述（优化器自动补充英文关键词）
├─ 5. 输入故事想法 + 页数
├─ 6. DeepSeek 生成故事脚本 → 预览 → 确认
├─ 7. 逐页生成图片（第1页文生图，第2页起参考图模式保角色换场景）
├─ 8. 排版输出（图片+文字合成绘本页）
└─ 9. 保存故事脚本 JSON
```

---

## 角色一致性机制

跨页面保持主角形象统一的核心方案：

| 策略 | 原理 | 适用模型 |
|------|------|----------|
| **参考图模式**（默认） | 第1页纯文生图，第2页起将第1页图片作为参考传入 `wan2.6-image`，保持角色一致同时更换场景 | wan2.6 |
| **seed 模式** | 所有页面使用相同随机种子 + 角色描述前缀 | 所有模型 |

配置方式（`storybook_generator.py` 顶部）：

```python
CHARACTER_CONSISTENCY_MODE = "reference"  # 参考图模式（推荐）
CHARACTER_CONSISTENCY_MODE = "seed"       # 种子模式（兼容）
```

参考图模式通过三层手段实现"保角色换场景"：
1. 专用 prompt 结构（`_build_reference_prompt`）三次强调场景差异
2. 关闭 `prompt_extend` 防止模型偏向参考图场景
3. 负面提示词排除"same background as reference"

---

## 文件详细说明

### `easy_storybook.py` — 简单模式入口

用户只需输入一句话想法，由 DeepSeek AI 自动生成完整分页故事脚本，再调用千问模型生图。

| 函数 | 作用 |
|------|------|
| `get_deepseek_api_key()` | 获取 DeepSeek API Key，优先级：配置文件 > 环境变量 > 运行时输入 |
| `generate_story_with_deepseek(idea, character_desc, num_pages, api_key)` | 调用 DeepSeek API，根据故事想法和主角描述生成完整分页绘本脚本。返回 `{"title", "pages": [{"text", "scene"}, ...]}` |
| `display_story_preview(story)` | 在终端展示生成的故事预览（标题、每页文字和场景） |
| `main()` | 主流程：获取Key → 选模型 → 选风格 → 输入角色 → 输入想法 → DeepSeek生故事 → 确认 → 生图 → 排版 → 保存 |

---

### `storybook_generator.py` — 核心生图引擎

负责模型选择、图片生成、角色一致性、排版输出的核心模块。

#### 配置常量

| 常量 | 作用 |
|------|------|
| `QWEN_API_KEY` | DashScope API Key |
| `QWEN_BASE_URL` | DashScope API 基础地址 |
| `QWEN_MODELS` | 可用文生图模型列表（wan2.6-t2i / wan2.5 / wanx2.1-turbo / wanx2.1-plus） |
| `DEFAULT_QWEN_MODEL` | 默认模型（wan2.6-t2i） |
| `REF_MODEL` | 角色一致性参考图专用模型（wan2.6-image） |
| `DEFAULT_IMAGE_SIZE` | 默认图片尺寸（1024*1024） |
| `STYLE_TEMPLATES` | 4种绘本风格模板（水彩/卡通/蜡笔/剪纸），每种含英文 prompt |
| `USE_CHARACTER_PREFIX` | 是否在每页 prompt 中加入角色描述前缀 |
| `CHARACTER_CONSISTENCY_MODE` | 角色一致性策略（"reference" / "seed"） |
| `FIXED_SEED` | 固定随机种子（仅 seed 模式生效） |
| `REFERENCE_NEGATIVE_PROMPT` | 参考图模式负面提示词，排除场景复制 |

#### API 工具函数

| 函数 | 作用 |
|------|------|
| `get_api_key()` | 获取 DashScope API Key，优先级：配置文件 > 环境变量 > 运行时输入 |
| `_pil_to_base64(img)` | 将 PIL Image 对象转为 Base64 字符串（用于参考图传输） |
| `generate_image_with_qwen(prompt, api_key, model, size, seed)` | 异步文生图（适用于 wanx2.1 / wanx-v1）。提交任务 → 轮询状态 → 下载图片 |
| `generate_image_sync(prompt, api_key, model, size, seed)` | 同步文生图（适用于 wan2.6-t2i / wan2.5-t2i）。一次请求直接返回结果 |
| `generate_image_with_reference(prompt, ref_image, api_key, model, size, seed, negative_prompt)` | 参考图生图（适用于 wan2.6-image）。传入参考图保持角色一致，prompt 描述新场景 |

#### 提示词工具函数

| 函数 | 作用 |
|------|------|
| `_clean_prompt(prompt, max_words)` | 清理提示词：去重、去除 SD 专用质量标签（masterpiece/8k uhd 等）、限制总词数 |
| `build_qwen_prompt(scene, character_desc, style_prompt)` | 为千问模型构建简洁 prompt，结构：风格 + 角色 + 场景 |
| `_build_reference_prompt(character_desc, scene_desc, style_prompt)` | 构建参考图模式专用 prompt，三次强调"角色一致、场景不同" |
| `_is_wan26_model(model)` | 判断是否为 wan2.6/2.5 同步 API 模型 |

#### 交互函数

| 函数 | 作用 |
|------|------|
| `select_model()` | 让用户从 QWEN_MODELS 中选择千问图片模型 |
| `select_style()` | 让用户从 STYLE_TEMPLATES 中选择绘本风格 |
| `input_story()` | 逐页输入故事文字和场景描述（手动模式用） |
| `input_character(optimizer)` | 输入主角描述并优化。始终保留用户原始描述，优化器仅补充英文关键词 |

#### 核心生成函数

| 函数 | 作用 |
|------|------|
| `generate_storybook(pages, character_desc, style, api_key, model, size)` | 生成完整绘本。第1页纯文生图并设为参考图，第2页起用参考图模式保角色换场景。失败自动回退普通文生图 |
| `create_layout_page(img, text, page_num, total_pages)` | 将图片和故事文字合成为排版好的绘本页（1024x1280 画布，图片在上文字在下） |
| `wrap_text(text, font, max_width, draw)` | 中文文本自动换行，逐字符计算宽度 |
| `load_chinese_font(size)` | 加载 Windows 系统中文字体（微软雅黑/宋体/黑体等） |
| `create_pdf_or_images(pages_data, book_dir)` | 批量排版所有页面，输出到 layout 子目录 |
| `revise_pages(images_data, pages, ...)` | 生成后修改流程：选择某几页重新生成（支持参考图模式），重新排版 |
| `main()` | 手动模式主流程：获取Key → 选模型 → 选风格 → 输入角色 → 输入故事 → 生图 → 排版 → 修改模式 |

---

### `prompt_optimizer.py` — 提示词优化器

将用户的中文口语化描述转换为专业的英文提示词。

#### `PromptOptimizer` 类

| 方法 | 作用 |
|------|------|
| `__init__(enable_quality_tags, enable_auto_negative)` | 初始化优化器，合并所有关键词映射库 |
| `analyze_keywords(text)` | 分析输入文本，按长度优先匹配关键词映射库中的条目，返回匹配到的关键词和对应英文描述 |
| `expand_scene(user_input)` | 场景扩写：根据情绪、时间、室内外自动补充光线和氛围描述 |
| `optimize(user_input, character_desc, style_prompt, composition_hint)` | 主优化函数：组合角色描述 + 关键词映射 + 场景扩写 + 风格 + 质量标签，返回优化 prompt 和负面 prompt |
| `generate_negative(user_input)` | 根据场景类型（室内/室外/人物/动物）智能生成负面提示词 |

#### 关键词映射库（类属性）

| 映射库 | 内容 | 示例 |
|--------|------|------|
| `LOCATION_MAP` | 30个地点 | "森林" → "lush forest, tall trees, dappled sunlight..." |
| `ANIMAL_MAP` | 24种动物 | "小兔子" → "cute little rabbit, soft white fur, pink nose..." |
| `CHARACTER_MAP` | 14种人物 | "小女孩" → "cute little girl, innocent face, bright eyes..." |
| `ACTION_MAP` | 26种动作 | "跳" → "jumping, mid-air, energetic, happy, dynamic pose" |
| `MOOD_MAP` | 18种情绪 | "开心" → "joyful, happy atmosphere, bright and cheerful..." |
| `TIME_MAP` | 16种时间/季节 | "黄昏" → "sunset, golden hour, warm orange sky..." |
| `OBJECT_MAP` | 29种物品 | "蝴蝶结" → "cute bow tie, ribbon accessory..." |
| `COMPOSITION_MAP` | 8种构图 | "特写" → "close-up shot, detailed facial expression..." |

#### `LLMPromptOptimizer` 类

基于 LLM API 的提示词优化器（可选），无 API Key 时自动回退到 `PromptOptimizer`。

---

### `test_qwen_api.py` — API 连通测试

独立测试 DashScope API 连通性的脚本。提交一个简单的生图任务，轮询等待完成后下载图片。用于排查 API Key 和网络问题。

### `run.py` — 旧版 SD API 测试

原始的 Stable Diffusion WebUI API 测试脚本，已不再使用。

### `generate_easy.py` — 开发工具

用于生成 `easy_storybook.py` 文件的脚本（开发辅助工具）。

---

## 输出说明

运行后，绘本文件保存在 `storybooks/storybook_YYYYMMDD_HHMMSS/` 目录下：

```
storybook_20260617_092428/
├── page_01.png           # 原始生成的图片
├── page_02.png
├── page_03.png
├── layout_01.png         # 排版后的绘本页（图片+文字）
├── layout_02.png
├── layout_03.png
└── story_script.json     # 故事脚本（标题、想法、角色、各页内容）
```

---

## 技术架构

```
用户输入
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
输出文件
```

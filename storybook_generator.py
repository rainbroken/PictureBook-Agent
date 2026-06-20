#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
儿童绘本生成器 - 基于千问 Image 模型 (DashScope API)
功能：选择模型 → 输入故事 → 固定角色 → 生成绘本
"""

import os
import sys
import io
import builtins

# 解决 Windows GBK 编码无法输出特殊字符的问题
os.environ["PYTHONIOENCODING"] = "utf-8"
if not hasattr(builtins, '_print_patched'):
    _original_print = builtins.print
    def _safe_print(*args, **kwargs):
        try:
            _original_print(*args, **kwargs)
        except UnicodeEncodeError:
            safe_args = []
            for a in args:
                if isinstance(a, str):
                    safe_args.append(a.encode('utf-8', errors='replace').decode('ascii', errors='replace'))
                else:
                    safe_args.append(a)
            try:
                _original_print(*safe_args, **kwargs)
            except UnicodeEncodeError:
                pass
    builtins.print = _safe_print
    builtins._print_patched = True

import requests
import base64
import json
import time

from PIL import Image, ImageDraw, ImageFont
import io
from datetime import datetime

from prompt_optimizer import PromptOptimizer

# ==================== 配置 ====================
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storybooks")

# ============== 千问 Image 模型配置 ==============
# 在此填入你的 DashScope API Key，或设置环境变量 DASHSCOPE_API_KEY
QWEN_API_KEY = "sk-ws-H.REXDMEE.oxrt.MEUCIQCMgnZ5hH90TsuyHgxgSNYUdJq3y9hAZr4KxXXzlCK4lQIgEd-4hkWlUVjkAWUSf2ffyT1hu7FuM-Tm9Iawm_hOI8I"
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"

# 可用模型列表（文生图）
QWEN_MODELS = {
    "1": {"name": "wan2.6-t2i",          "desc": "万相2.6 (推荐，支持角色一致性)"},
    "2": {"name": "wan2.5-t2i-preview",  "desc": "万相2.5 preview"},
    "3": {"name": "wanx2.1-t2i-turbo",   "desc": "万相2.1 快速版"},
    "4": {"name": "wanx2.1-t2i-plus",    "desc": "万相2.1 专业版"},
}
# 默认模型
DEFAULT_QWEN_MODEL = "wan2.6-t2i"

# 角色一致性专用模型（内部使用，生成第2页起用此模型+参考图）
REF_MODEL = "wan2.6-image"

# 默认图片尺寸
DEFAULT_IMAGE_SIZE = "1024*1024"

# 绘本风格模板
STYLE_TEMPLATES = {
    "1": {
        "name": "水彩绘本",
        "prompt": "children's book illustration, watercolor painting, soft pastel colors, gentle lighting, storybook art style, cute and friendly"
    },
    "2": {
        "name": "卡通绘本",
        "prompt": "children's book illustration, cartoon style, flat colors, bold outlines, cute chibi characters, bright and cheerful"
    },
    "3": {
        "name": "蜡笔绘本",
        "prompt": "children's book illustration, crayon drawing style, textured paper, warm colors, handmade feeling, cute"
    },
    "4": {
        "name": "剪纸绘本",
        "prompt": "children's book illustration, paper cutout style, layered paper art, colorful collage, folk art style"
    }
}

# ============== 角色一致性配置 ==============
# 所有页面使用相同角色描述前缀 (True=角色更一致, False=场景更多样)
USE_CHARACTER_PREFIX = True

# 角色一致性策略:
#   "reference" - 使用第1页图片作为参考图，后续页面保持角色一致 (推荐，需wan2.6)
#   "seed"      - 使用固定seed+角色描述前缀 (兼容所有模型，效果一般)
CHARACTER_CONSISTENCY_MODE = "reference"

# 固定种子 (仅seed模式生效)
FIXED_SEED = 42


# ==================== API 工具函数 ====================

def get_api_key():
    """获取 DashScope API Key"""
    if QWEN_API_KEY:
        return QWEN_API_KEY
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if key:
        return key
    print()
    print("=" * 50)
    print("  千问 Image API Key 未配置")
    print("=" * 50)
    print("请先在 storybook_generator.py 顶部填入 QWEN_API_KEY，")
    print("或设置环境变量: set DASHSCOPE_API_KEY=sk-xxxxxx")
    print("获取 API Key: https://dashscope.console.aliyun.com/apiKey")
    print()
    key = input("临时输入 API Key (直接回车可跳过): ").strip()
    return key


def _pil_to_base64(img):
    """将 PIL Image 转为 Base64 字符串"""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def generate_image_with_qwen(prompt, api_key, model=None, size=None, seed=None):
    """
    调用千问 Image 模型生成图片 (异步任务模式，适用于 wanx2.1 / wanx-v1)
    返回: (Image对象, 信息文本)
    """
    if not api_key:
        print("  [X] 未提供 API Key")
        return None, ""

    model = model or DEFAULT_QWEN_MODEL
    size = size or DEFAULT_IMAGE_SIZE

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable"
    }

    params = {"size": size, "n": 1}
    if seed is not None:
        params["seed"] = seed

    payload = {
        "model": model,
        "input": {
            "prompt": prompt
        },
        "parameters": params
    }

    try:
        # 绕过系统代理，直连 DashScope
        no_proxy = {"http": None, "https": None}

        # 提交异步任务
        resp = requests.post(
            f"{QWEN_BASE_URL}/services/aigc/text2image/image-synthesis",
            headers=headers,
            json=payload,
            timeout=60,
            proxies=no_proxy
        )
        resp.raise_for_status()
        result = resp.json()

        # 检查是否直接返回了结果 (部分模型支持同步)
        if result.get("output", {}).get("task_status") == "SUCCEEDED":
            image_url = result["output"]["results"][0]["url"]
            img_resp = requests.get(image_url, timeout=30, proxies=no_proxy)
            img = Image.open(io.BytesIO(img_resp.content))
            return img, json.dumps(result.get("output", {}), ensure_ascii=False)

        # 获取任务 ID
        task_id = result.get("output", {}).get("task_id")
        if not task_id:
            print(f"  [X] 任务提交失败: {result}")
            return None, ""

        # 轮询等待任务完成
        max_wait = 180  # 最长等待 3 分钟
        elapsed = 0
        poll_interval = 3

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            status_resp = requests.get(
                f"{QWEN_BASE_URL}/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
                proxies=no_proxy
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            task_status = status_data.get("output", {}).get("task_status", "")

            if task_status == "SUCCEEDED":
                results = status_data["output"].get("results", [])
                if results:
                    image_url = results[0]["url"]
                    # 下载图片
                    img_resp = requests.get(image_url, timeout=60, proxies=no_proxy)
                    img = Image.open(io.BytesIO(img_resp.content))
                    info = json.dumps(status_data.get("output", {}), ensure_ascii=False)
                    return img, info
                else:
                    print(f"  [X] 任务成功但无图片结果")
                    return None, ""

            elif task_status == "FAILED":
                error_msg = status_data.get("output", {}).get("message", "未知错误")
                print(f"  [X] 图片生成失败: {error_msg}")
                return None, ""

            # 仍在处理中
            print(f"  [...] 等待生成中... ({elapsed}s)")

        print(f"  [X] 生成超时 ({max_wait}s)")
        return None, ""

    except requests.exceptions.ConnectionError:
        print("  [X] 无法连接到 DashScope API，请检查网络")
        return None, ""
    except Exception as e:
        print(f"  [X] 图片生成异常: {e}")
        return None, ""


def generate_image_sync(prompt, api_key, model=None, size=None, seed=None):
    """
    调用万相2.6+ 同步文生图API (适用于 wan2.6-t2i / wan2.5-t2i)
    返回: (Image对象, 信息文本)
    """
    if not api_key:
        print("  [X] 未提供 API Key")
        return None, ""

    model = model or DEFAULT_QWEN_MODEL
    size = size or DEFAULT_IMAGE_SIZE
    no_proxy = {"http": None, "https": None}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    params = {
        "size": size,
        "n": 1,
        "prompt_extend": True,
        "watermark": False,
    }
    if seed is not None:
        params["seed"] = seed

    payload = {
        "model": model,
        "input": {
            "messages": [{
                "role": "user",
                "content": [{"text": prompt}]
            }]
        },
        "parameters": params
    }

    try:
        resp = requests.post(
            f"{QWEN_BASE_URL}/services/aigc/multimodal-generation/generation",
            headers=headers,
            json=payload,
            timeout=120,
            proxies=no_proxy
        )
        resp.raise_for_status()
        result = resp.json()

        # 检查错误
        if "code" in result:
            print(f"  [X] API 错误: {result.get('message', result.get('code'))}")
            return None, ""

        # 提取图片 URL
        choices = result.get("output", {}).get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", [])
            for item in content:
                if item.get("type") == "image":
                    image_url = item["image"]
                    img_resp = requests.get(image_url, timeout=60, proxies=no_proxy)
                    img = Image.open(io.BytesIO(img_resp.content))
                    info = json.dumps(result.get("output", {}), ensure_ascii=False)
                    return img, info

        print(f"  [X] 未返回图片: {json.dumps(result, ensure_ascii=False)[:300]}")
        return None, ""

    except requests.exceptions.ConnectionError:
        print("  [X] 无法连接到 DashScope API，请检查网络")
        return None, ""
    except Exception as e:
        print(f"  [X] 同步生图异常: {e}")
        return None, ""


def generate_image_with_reference(prompt, ref_image, api_key, model=None, size=None, seed=None, negative_prompt=""):
    """
    使用参考图生成图片 — 保持角色一致性，但更换场景 (wan2.6-image 同步API)
    prompt: 新场景的文本描述
    ref_image: 参考图的 PIL Image 对象
    negative_prompt: 反向提示词，排除不需要的元素
    返回: (Image对象, 信息文本)
    """
    if not api_key:
        print("  [X] 未提供 API Key")
        return None, ""

    model = model or REF_MODEL
    size = size or DEFAULT_IMAGE_SIZE
    no_proxy = {"http": None, "https": None}

    # 将参考图转为 Base64
    ref_b64 = _pil_to_base64(ref_image)
    ref_data_uri = f"data:image/jpeg;base64,{ref_b64}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    params = {
        "size": size,
        "n": 1,
        "prompt_extend": False,   # 关闭智能改写，精确控制场景
        "watermark": False,
        "enable_interleave": False,  # 图像编辑模式（主体一致性）
    }
    if seed is not None:
        params["seed"] = seed
    if negative_prompt:
        params["negative_prompt"] = negative_prompt

    payload = {
        "model": model,
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"text": prompt},
                    {"image": ref_data_uri}
                ]
            }]
        },
        "parameters": params
    }

    try:
        print(f"  [REF] 使用参考图模式 (角色一致性)")
        resp = requests.post(
            f"{QWEN_BASE_URL}/services/aigc/multimodal-generation/generation",
            headers=headers,
            json=payload,
            timeout=180,
            proxies=no_proxy
        )
        resp.raise_for_status()
        result = resp.json()

        # 检查错误
        if "code" in result:
            print(f"  [X] API 错误: {result.get('message', result.get('code'))}")
            return None, ""

        # 提取图片 URL
        choices = result.get("output", {}).get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", [])
            for item in content:
                if item.get("type") == "image":
                    image_url = item["image"]
                    img_resp = requests.get(image_url, timeout=60, proxies=no_proxy)
                    img = Image.open(io.BytesIO(img_resp.content))
                    info = json.dumps(result.get("output", {}), ensure_ascii=False)
                    return img, info

        print(f"  [X] 未返回图片: {json.dumps(result, ensure_ascii=False)[:300]}")
        return None, ""

    except requests.exceptions.ConnectionError:
        print("  [X] 无法连接到 DashScope API，请检查网络")
        return None, ""
    except Exception as e:
        print(f"  [X] 参考图生图异常: {e}")
        return None, ""


# ==================== 绘本生成核心 ====================

def _build_reference_prompt(character_desc, scene_desc, style_prompt):
    """
    构建参考图模式的专用提示词
    核心原则：角色必须与参考图一致，场景必须完全不同
    """
    # 场景描述强化：在提示词中场景描述占据主导地位
    parts = []
    # 1. 风格
    if style_prompt:
        parts.append(style_prompt)
    # 2. 明确指令：角色一致，场景不同
    parts.append("The character must look identical to the reference image")
    if character_desc:
        parts.append(f"(same {character_desc})")
    # 3. 强调新场景（放在最核心的位置）
    parts.append("in a completely different scene and background.")
    parts.append(f"NEW SCENE: {scene_desc}")
    # 4. 再次强调场景差异
    parts.append("The environment, background, and setting are entirely new and different from the reference image.")

    prompt = " ".join(parts)
    return _clean_prompt(prompt, max_words=100)


REFERENCE_NEGATIVE_PROMPT = (
    "same background as reference, same scene as reference, "
    "identical environment to reference, duplicate background, "
    "low resolution, blurry, distorted"
)


def _is_wan26_model(model):
    """判断是否为 wan2.6/2.5 同步API模型"""
    return any(m in model for m in ["wan2.6", "wan2.5"])


def select_model():
    """让用户选择千问图片模型"""
    print("\n" + "=" * 50)
    print("[*] 可用千问图片模型:")
    print("=" * 50)
    for key, m in QWEN_MODELS.items():
        print(f"  [{key}] {m['name']} - {m['desc']}")

    while True:
        choice = input(f"\n请选择模型 (1-{len(QWEN_MODELS)}, 直接回车使用默认): ").strip()
        if not choice:
            return DEFAULT_QWEN_MODEL
        if choice in QWEN_MODELS:
            return QWEN_MODELS[choice]["name"]
        print("[!] 无效选择")


def select_style():
    """让用户选择绘本风格"""
    print("\n" + "=" * 50)
    print("[*] 绘本风格模板:")
    print("=" * 50)
    for key, style in STYLE_TEMPLATES.items():
        print(f"  [{key}] {style['name']}")

    while True:
        choice = input("\n请选择风格 (1-4): ").strip()
        if choice in STYLE_TEMPLATES:
            return STYLE_TEMPLATES[choice]
        print("[!] 无效选择")


def input_story():
    """输入故事内容"""
    print("\n" + "=" * 50)
    print("故事输入")
    print("=" * 50)
    print("请逐页输入绘本内容。每页包含：")
    print("  - 故事文字 (会显示在绘本上)")
    print("  - 场景描述 (用于AI生成图片的提示词)")
    print("输入空场景描述表示结束\n")

    pages = []
    page_num = 1

    while True:
        print(f"\n--- 第 {page_num} 页 ---")
        text = input("故事文字: ").strip()
        scene = input("场景描述 (AI绘图提示词): ").strip()

        if not scene:
            if page_num == 1:
                print("[!] 至少需要一页内容")
                continue
            break

        pages.append({
            "page": page_num,
            "text": text,
            "scene": scene
        })
        page_num += 1

        if page_num > 12:
            print("[!] 已达到最大页数限制 (12页)")
            break

    return pages


def input_character(optimizer):
    """输入角色描述，并自动优化为英文专业提示词"""
    print("\n" + "=" * 50)
    print("角色设定（详细描述 = 更一致的形象）")
    print("=" * 50)
    print("请尽可能详细地描述主角外观，越具体角色越一致：")
    print("  - 种类/性别（小白兔/小女孩）")
    print("  - 体型特征（圆圆的/瘦瘦的）")
    print("  - 毛色/发型/发色（白色毛/金色短发）")
    print("  - 衣着配饰（蓝色马甲/红色蝴蝶结）")
    print("  - 表情特征（大眼睛/微笑）")
    print()
    print("示例: 一只白色的小兔子，圆圆的大眼睛，穿着蓝色背带裤，戴着红色蝴蝶结")
    print()

    character = input("主角描述: ").strip()
    if not character:
        character = "a cute little white rabbit, round big eyes, wearing blue overalls, red bow tie"
        print(f"使用默认描述: {character}")
        return character

    # 优化角色描述（仅用关键词映射，不加质量标签）
    optimized_char, _ = optimizer.optimize(user_input=character, style_prompt="")
    # 去除重复和冗余的质量标签，保留核心角色描述
    optimized_char = _clean_prompt(optimized_char)
    print(f"  [opt] 角色优化: {character}")
    print(f"       → {optimized_char}")

    return optimized_char


def _clean_prompt(prompt, max_words=60):
    """清理提示词：去重、去冗余质量标签、限制长度"""
    # 冗余的质量/技术标签（千问模型不需要这些）
    noise_words = {
        "masterpiece", "best quality", "highly detailed", "8k uhd",
        "sharp focus", "professional artwork", "medium shot",
        "balanced composition", "clear view",
    }
    parts = [p.strip() for p in prompt.split(",")]
    seen = set()
    clean_parts = []
    for part in parts:
        part_lower = part.lower().strip()
        if not part_lower:
            continue
        # 跳过噪声标签
        if part_lower in noise_words:
            continue
        # 去重
        if part_lower not in seen:
            seen.add(part_lower)
            clean_parts.append(part.strip())
    result = ", ".join(clean_parts)
    # 限制总词数
    words = result.split()
    if len(words) > max_words:
        result = " ".join(words[:max_words])
    return result


def build_qwen_prompt(scene, character_desc, style_prompt):
    """
    为千问模型构建简洁高效的提示词
    结构: 风格 + 角色 + 场景动作 + 环境
    """
    parts = []
    # 1. 风格前缀
    if style_prompt:
        parts.append(style_prompt)
    # 2. 角色描述（核心一致性保证）
    if character_desc:
        parts.append(character_desc)
    # 3. 场景描述
    if scene:
        parts.append(scene)
    raw = ", ".join(parts)
    return _clean_prompt(raw, max_words=80)


def generate_storybook(pages, character_desc, style, api_key=None, model=None, size=None):
    """
    生成完整绘本
    pages: 故事页列表
    character_desc: 角色描述
    style: 风格模板字典
    api_key: DashScope API Key
    model: 千问图片模型名称
    size: 图片尺寸
    """
    api_key = api_key or get_api_key()
    if not api_key:
        print("[X] 未提供 API Key，无法生成图片")
        return [], ""

    model = model or DEFAULT_QWEN_MODEL
    size = size or DEFAULT_IMAGE_SIZE

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    book_dir = os.path.join(OUTPUT_DIR, f"storybook_{timestamp}")
    os.makedirs(book_dir, exist_ok=True)

    print(f"\n{'=' * 50}")
    print(f"[*] 开始生成绘本，共 {len(pages)} 页")
    print(f"模型: {model}")
    print(f"尺寸: {size}")
    print(f"输出目录: {book_dir}")
    print(f"{'=' * 50}\n")

    # 初始化提示词优化器
    optimizer = PromptOptimizer(enable_quality_tags=True, enable_auto_negative=False)

    generated_images = []
    ref_image = None  # 第1页图片将作为后续页的参考图
    use_reference = (CHARACTER_CONSISTENCY_MODE == "reference") and _is_wan26_model(model)

    for i, page in enumerate(pages):
        page_num = page["page"]
        scene = page["scene"]
        text = page["text"]

        # ========== 构建提示词 ==========
        print(f"[{page_num}/{len(pages)}] 生成第 {page_num} 页...")
        print(f"  [scene] 用户描述: {scene}")

        # 构建千问专用简洁提示词
        # 先用优化器提取场景关键词，再组合成简洁 prompt
        optimized_scene, _ = optimizer.optimize(
            user_input=scene,
            character_desc="",  # 角色单独处理，避免重复
            style_prompt=""       # 风格单独处理，避免重复
        )
        qwen_prompt = build_qwen_prompt(
            scene=_clean_prompt(optimized_scene),
            character_desc=character_desc if USE_CHARACTER_PREFIX else "",
            style_prompt=style['prompt']
        )

        # ===== 角色一致性策略 =====
        if i == 0 or not use_reference or ref_image is None:
            # 第1页：纯文生图
            print(f"  [prompt] 千问提示词: {qwen_prompt}")
            if _is_wan26_model(model):
                img, info = generate_image_sync(
                    prompt=qwen_prompt, api_key=api_key, model=model, size=size, seed=FIXED_SEED
                )
            else:
                img, info = generate_image_with_qwen(
                    prompt=qwen_prompt, api_key=api_key, model=model, size=size, seed=FIXED_SEED
                )
        else:
            # 第2页起：使用第1页图片作为参考，保持角色一致但更换场景
            ref_prompt = _build_reference_prompt(
                character_desc=character_desc,
                scene_desc=_clean_prompt(optimized_scene),
                style_prompt=style['prompt']
            )
            print(f"  [prompt] 千问提示词(参考图模式): {ref_prompt}")
            img, info = generate_image_with_reference(
                prompt=ref_prompt,
                ref_image=ref_image,
                api_key=api_key,
                model=REF_MODEL,
                size=size,
                seed=FIXED_SEED,
                negative_prompt=REFERENCE_NEGATIVE_PROMPT
            )
            # 如果参考图模式失败，回退到普通文生图
            if img is None:
                print(f"  [!] 参考图模式失败，回退到普通文生图")
                if _is_wan26_model(model):
                    img, info = generate_image_sync(
                        prompt=qwen_prompt, api_key=api_key, model=model, size=size, seed=FIXED_SEED
                    )
                else:
                    img, info = generate_image_with_qwen(
                        prompt=qwen_prompt, api_key=api_key, model=model, size=size, seed=FIXED_SEED
                    )

        if img is None:
            print(f"  [X] 第 {page_num} 页生成失败，跳过")
            continue

        # 保存原图
        img_path = os.path.join(book_dir, f"page_{page_num:02d}.png")
        img.save(img_path)
        print(f"  [OK] 已保存: {img_path}")

        # 第1页成功后，将其设为参考图
        if i == 0 and img is not None:
            ref_image = img
            print(f"  [REF] 第1页已设为角色参考图，后续页面将保持角色一致")

        generated_images.append({
            "page": page_num,
            "text": text,
            "image": img,
            "path": img_path,
            "optimized_prompt": qwen_prompt
        })

    return generated_images, book_dir


def load_chinese_font(size):
    """
    加载支持中文的字体
    按优先级尝试 Windows 系统自带中文字体
    """
    font_paths = [
        f"C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        f"C:/Windows/Fonts/simsun.ttc",     # 宋体
        f"C:/Windows/Fonts/simhei.ttf",     # 黑体
        f"C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑粗体
        f"C:/Windows/Fonts/simkai.ttf",     # 楷体
    ]

    for path in font_paths:
        try:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            continue

    # 如果都失败了，尝试 arial 作为最后回退
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def create_layout_page(img, text, page_num, total_pages):
    """
    创建排版好的单页
    图片在上，文字在下
    """
    # 画布尺寸
    canvas_w = 1024
    canvas_h = 1280

    # 创建白色背景
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)

    # 图片区域 (留边距)
    img_margin = 40
    img_top = 60
    img_w = canvas_w - img_margin * 2
    img_h = 800

    # 缩放图片
    img_resized = img.resize((img_w, img_h), Image.LANCZOS)
    canvas.paste(img_resized, (img_margin, img_top))

    # 绘制页码
    font_page = load_chinese_font(24)

    page_label = f"第 {page_num} 页"
    bbox = draw.textbbox((0, 0), page_label, font=font_page)
    text_w = bbox[2] - bbox[0]
    draw.text(((canvas_w - text_w) // 2, 20), page_label, fill="#888888", font=font_page)

    # 绘制故事文字
    text_top = img_top + img_h + 40
    text_margin = 80
    max_text_w = canvas_w - text_margin * 2

    font_text = load_chinese_font(32)

    # 自动换行
    lines = wrap_text(text, font_text, max_text_w, draw)
    line_h = font_text.getbbox("A")[3] - font_text.getbbox("A")[1] + 10
    y = text_top

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_text)
        line_w = bbox[2] - bbox[0]
        x = (canvas_w - line_w) // 2
        draw.text((x, y), line, fill="#333333", font=font_text)
        y += line_h

    # 绘制页脚
    font_footer = load_chinese_font(18)

    footer = "儿童绘本"
    bbox = draw.textbbox((0, 0), footer, font=font_footer)
    footer_w = bbox[2] - bbox[0]
    draw.text(((canvas_w - footer_w) // 2, canvas_h - 40), footer, fill="#aaaaaa", font=font_footer)

    return canvas


def wrap_text(text, font, max_width, draw):
    """自动换行"""
    if not text:
        return [""]

    words = text
    lines = []
    current_line = ""

    for char in words:
        test_line = current_line + char
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = char

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


def revise_pages(images_data, pages, character_desc, style, optimizer, book_dir, api_key, model, size):
    """
    生成后修改流程
    用户可以选择某几页进行重新生成
    """
    while True:
        print("\n" + "=" * 50)
        print("修改插画")
        print("=" * 50)
        print("当前绘本页面:")
        for data in images_data:
            print(f"  第 {data['page']} 页: {data['text'][:40]}...")
        print(f"\n  [0] 完成修改，退出")

        # 选择要修改的页
        page_input = input("\n请输入要修改的页码 (如: 1 或 1,3,5): ").strip()
        if page_input == "0" or not page_input:
            print("退出修改模式")
            break

        # 解析页码
        try:
            page_nums = [int(p.strip()) for p in page_input.split(",")]
        except ValueError:
            print("[!] 页码格式错误，请用逗号分隔，如 1,3,5")
            continue

        # 验证页码
        valid_pages = {data["page"] for data in images_data}
        invalid = [p for p in page_nums if p not in valid_pages]
        if invalid:
            print(f"[!] 无效页码: {invalid}，有效页码为: {sorted(valid_pages)}")
            continue

        for page_num in page_nums:
            # 找到对应的数据
            data_idx = None
            for idx, d in enumerate(images_data):
                if d["page"] == page_num:
                    data_idx = idx
                    break

            if data_idx is None:
                continue

            data = images_data[data_idx]
            original_scene = pages[data_idx]["scene"]

            print(f"\n--- 修改第 {page_num} 页 ---")
            print(f"  原场景描述: {original_scene}")

            # === 重新生成 ===
            new_scene = input(f"  新场景描述 (直接回车保持原描述): ").strip()
            if not new_scene:
                new_scene = original_scene

            # 优化提示词
            optimized_prompt, _ = optimizer.optimize(
                user_input=new_scene,
                character_desc="",
                style_prompt=""
            )
            qwen_prompt = build_qwen_prompt(
                scene=_clean_prompt(optimized_prompt),
                character_desc=character_desc if USE_CHARACTER_PREFIX else "",
                style_prompt=style['prompt']
            )
            print(f"  [prompt] 千问提示词: {qwen_prompt}")

            # 使用第1页图片作为参考（如果有）
            ref_img = images_data[0].get("image") if images_data else None
            if ref_img and CHARACTER_CONSISTENCY_MODE == "reference" and page_num != images_data[0]["page"]:
                # 参考图模式：角色一致，场景不同
                optimized_prompt_scene, _ = optimizer.optimize(
                    user_input=new_scene, character_desc="", style_prompt=""
                )
                ref_prompt = _build_reference_prompt(
                    character_desc=character_desc,
                    scene_desc=_clean_prompt(optimized_prompt_scene),
                    style_prompt=style['prompt']
                )
                img, info = generate_image_with_reference(
                    prompt=ref_prompt, ref_image=ref_img,
                    api_key=api_key, model=REF_MODEL, size=size,
                    seed=FIXED_SEED, negative_prompt=REFERENCE_NEGATIVE_PROMPT
                )
                if img is None:
                    print(f"  [!] 参考图模式失败，回退到普通文生图")
                    img = None
            else:
                img = None

            if img is None:
                if _is_wan26_model(model):
                    img, info = generate_image_sync(
                        prompt=qwen_prompt, api_key=api_key, model=model, size=size, seed=FIXED_SEED
                    )
                else:
                    img, info = generate_image_with_qwen(
                        prompt=qwen_prompt, api_key=api_key, model=model, size=size, seed=FIXED_SEED
                    )

            if img is None:
                print(f"  [X] 第 {page_num} 页重新生成失败")
                continue

            # 覆盖保存
            img_path = data["path"]
            img.save(img_path)
            print(f"  [OK] 已覆盖保存: {img_path}")

            # 更新数据
            images_data[data_idx] = {
                "page": page_num,
                "text": data["text"],
                "image": img,
                "path": img_path,
                "optimized_prompt": qwen_prompt
            }
            # 同步更新 pages 中的场景描述
            pages[data_idx]["scene"] = new_scene

        # 重新排版修改过的页面
        print("\n重新排版修改的页面...")
        layout_dir = os.path.join(book_dir, "layout")
        os.makedirs(layout_dir, exist_ok=True)
        total = len(images_data)
        for data in images_data:
            if data["page"] in page_nums:
                img = Image.open(data["path"])
                layout = create_layout_page(img, data["text"], data["page"], total)
                layout_path = os.path.join(layout_dir, f"layout_{data['page']:02d}.png")
                layout.save(layout_path)
                print(f"  [OK] 重新排版: layout_{data['page']:02d}.png")

    return images_data


def create_pdf_or_images(pages_data, book_dir):
    """生成排版好的绘本页面"""
    print(f"\n{'=' * 50}")
    print("正在排版绘本...")
    print(f"{'=' * 50}\n")

    layout_dir = os.path.join(book_dir, "layout")
    os.makedirs(layout_dir, exist_ok=True)

    total = len(pages_data)
    for data in pages_data:
        page_num = data["page"]
        img = Image.open(data["path"])
        text = data["text"]

        layout = create_layout_page(img, text, page_num, total)
        layout_path = os.path.join(layout_dir, f"layout_{page_num:02d}.png")
        layout.save(layout_path)
        print(f"  [OK] 排版完成: layout_{page_num:02d}.png")

    return layout_dir


# ==================== 主程序 ====================

def main():
    print("=" * 60)
    print("     [*] 儿童绘本生成器")
    print("     基于千问 Image 模型 (DashScope API)")
    print("=" * 60)

    # 获取 API Key
    api_key = get_api_key()
    if not api_key:
        print("[X] 未提供 API Key，无法使用")
        print("请在 storybook_generator.py 顶部设置 QWEN_API_KEY")
        input("\n按回车退出...")
        return

    # 1. 选择模型
    model = select_model()

    # 2. 选择风格
    style = select_style()
    print(f"\n已选择风格: {style['name']}")
    print(f"模型: {model}")

    # 3. 初始化优化器并输入角色
    optimizer = PromptOptimizer(enable_quality_tags=True, enable_auto_negative=False)
    character = input_character(optimizer)

    # 4. 输入故事
    pages = input_story()
    if not pages:
        print("[X] 没有故事内容，退出")
        return

    print(f"\n故事共 {len(pages)} 页，准备生成...")
    confirm = input("\n确认生成? (Y/n): ").strip().lower()
    if confirm == "n":
        print("已取消")
        return

    # 5. 生成绘本
    images_data, book_dir = generate_storybook(
        pages=pages,
        character_desc=character,
        style=style,
        api_key=api_key,
        model=model
    )

    if not images_data:
        print("[X] 绘本生成失败")
        return

    # 6. 排版
    layout_dir = create_pdf_or_images(images_data, book_dir)

    # 完成
    print(f"\n{'=' * 50}")
    print("绘本生成完成!")
    print(f"{'=' * 50}")
    print(f"\n文件位置:")
    print(f"   原始图片: {book_dir}")
    print(f"   排版页面: {layout_dir}")
    print(f"\n绘本预览:")
    for data in images_data:
        print(f"   第 {data['page']} 页: {data['text'][:30]}...")

    # 7. 修改模式
    revise = input("\n是否需要修改某几页插画? (y/N): ").strip().lower()
    if revise == "y":
        images_data = revise_pages(
            images_data, pages, character, style, optimizer,
            book_dir, api_key, model, DEFAULT_IMAGE_SIZE
        )
        print("\n[OK] 修改完成，最终文件保存在:" + book_dir)
    else:
        print(f"\n所有文件保存在: {book_dir}")

    input("\n按回车退出...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n已取消")
    except Exception as e:
        print(f"\n[X] 程序错误: {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车退出...")

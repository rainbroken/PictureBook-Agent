#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单模式绘本生成器
用户只需输入粗略想法 → DeepSeek AI 自动生成故事脚本 → 生成绘本图画
"""

import os
import sys
import io
import builtins
import json
import requests

# 解决 Windows GBK 编码问题
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

# 从 services 层导入核心功能
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
from services.storybook_generator import (
    select_model, select_style, input_character,
    generate_storybook, create_layout_page,
    get_api_key as get_qwen_api_key, OUTPUT_DIR,
    DEFAULT_QWEN_MODEL, DEFAULT_IMAGE_SIZE,
    # Web 端额外需要的接口
    STYLE_TEMPLATES, QWEN_MODELS,
    REF_MODEL, FIXED_SEED,
    REFERENCE_NEGATIVE_PROMPT,
    CHARACTER_CONSISTENCY_MODE,
    USE_CHARACTER_PREFIX,
    build_qwen_prompt, _clean_prompt,
    _build_reference_prompt, _is_wan26_model,
    generate_image_sync,
    generate_image_with_qwen,
    generate_image_with_reference,
)
from services.prompt_optimizer import PromptOptimizer
from config import load_config


# ==================== DeepSeek 配置（从 config.yaml 读取）====================
def _ds_cfg():
    return load_config()["deepseek"]


def get_deepseek_api_key():
    """获取 DeepSeek API Key，优先级：config.yaml > 环境变量 > 运行时输入"""
    key = _ds_cfg().get("api_key", "").strip()
    if key:
        return key
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    print()
    print("=" * 50)
    print("[!] DeepSeek API Key 未配置")
    print("=" * 50)
    print("请在 config/config.yaml 的 deepseek.api_key 填入 Key，")
    print("或设置环境变量: set DEEPSEEK_API_KEY=sk-xxxxxx")
    print()
    key = input("临时输入 API Key (直接回车可跳过): ").strip()
    return key


def generate_story_with_deepseek(idea, character_desc, num_pages, api_key):
    """
    调用 DeepSeek API，根据用户想法自动生成完整绘本故事脚本
    返回: {"title": "...", "pages": [{"text": "...", "scene": "..."}, ...]}"
    """
    system_prompt = (
        "你是一位专业的儿童绘本故事作家。"
        "用户会提供一个故事想法和主角描述，你需要将其扩展为完整的分页绘本脚本。\n\n"
        "要求：\n"
        "1. 故事文字简短温馨，每页 2-3 句话，适合 3-8 岁儿童\n"
        "2. 故事结构完整：有开头、发展、高潮、结局\n"
        "3. 场景描述用中文，清晰描述该页画面内容（主角动作+环境），供 AI 绘图使用\n"
        "4. 每一页场景要有变化，不要重复\n\n"
        "请以 JSON 格式返回，格式如下：\n"
        '{\"title\": \"故事标题\", \"pages\": [{\"text\": \"故事文字\", \"scene\": \"画面场景描述\"}, ...]}\n'
        "只返回 JSON，不要有其他文字。"
    )
    user_message = (
        f"故事想法：{idea}\n"
        f"主角描述：{character_desc}\n"
        f"页数：{num_pages}页\n\n"
        f"请生成完整的 {num_pages} 页绘本故事脚本。"
    )
    print(f"  正在调用 DeepSeek ({_ds_cfg()['model']})…")
    try:
        # 绕过系统代理，直连 DeepSeek
        no_proxy = {"http": None, "https": None}
        resp = requests.post(
            f"{_ds_cfg()['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": _ds_cfg()["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.85,
                "max_tokens": 2000
            },
            timeout=60,
            proxies=no_proxy
        )
        resp.raise_for_status()
        result = resp.json()
        content = result["choices"][0]["message"]["content"].strip()
        # 清理 markdown 代码块包裹
        if "```" in content:
            parts = content.split("```")
            for part in parts:
                p = part.strip()
                if p.startswith("json"):
                    p = p[4:]
                if p.startswith("{"):
                    content = p
                    break
        story = json.loads(content.strip())
        return story
    except json.JSONDecodeError as e:
        print(f"  [!] JSON 解析失败: {e}")
        print(f"  原始返回内容: {content[:300]}")
        return None
    except Exception as e:
        print(f"  [X] DeepSeek API 调用失败: {e}")
        return None


def display_story_preview(story):
    """展示生成的故事预览"""
    title = story.get("title", "未命名")
    print()
    print("=" * 50)
    print(f"故事预览：《{title}》")
    print("=" * 50)
    for i, page in enumerate(story.get("pages", []), 1):
        print(f"\n--- 第 {i} 页 ---")
        print(f"  文字: {page['text']}")
        print(f"  场景: {page['scene']}")


def main():
    print("=" * 50)
    print("简单模式 -- 一个想法，生成整本绘本")
    print("=" * 50)

    # 1. 获取 DeepSeek API Key
    api_key = get_deepseek_api_key()
    if not api_key:
        print("[X] 未提供 API Key，无法使用简单模式")
        print("请在 easy_storybook.py 顶部设置 DEEPSEEK_API_KEY")
        return

    # 2. 选择模型
    select_model()

    # 3. 选择绘本风格
    style = select_style()

    # 4. 输入主角描述
    optimizer = PromptOptimizer()
    character_desc = input_character(optimizer)

    # 5. 输入故事想法
    print()
    print("=" * 50)
    print("故事想法输入")
    print("=" * 50)
    print("请用一两句话描述你的故事想法：")
    print("示例：一只小兔子在森林里迷路了，遇到各种小动物的帮助后找到了家")
    print()
    idea = input("你的故事想法: ").strip()
    if not idea:
        print("[X] 输入不能为空")
        return

    # 6. 指定页数
    while True:
        try:
            num_str = input("请输入绘本页数 (3-8页): ").strip()
            num_pages = int(num_str)
            if 3 <= num_pages <= 8:
                break
            print("[!] 请输入 3-8 之间的数字")
        except ValueError:
            print("[!] 请输入有效数字")

    # 7. 调用 DeepSeek 生成故事
    print()
    print(f"正在让 AI 创作 {num_pages} 页的故事...")
    story = generate_story_with_deepseek(idea, character_desc, num_pages, api_key)
    if not story:
        print("[X] 故事生成失败，请检查 API Key 或网络连接")
        return

    # 8. 预览并确认
    while True:
        display_story_preview(story)
        print()
        confirm = input("确认生成绘本? (y=确认 / n=取消 / r=重新生成): ").strip().lower()
        if confirm == "r":
            print(f"\n重新生成故事...")
            story = generate_story_with_deepseek(idea, character_desc, num_pages, api_key)
            if not story:
                print("[X] 重新生成失败")
                return
        elif confirm == "n":
            print("已取消")
            return
        else:
            break

    # 9. 转换为 pages 格式
    pages = [
        {"page": i + 1, "text": p["text"], "scene": p["scene"]}
        for i, p in enumerate(story.get("pages", []))
    ]

    # 10. 生成绘本图片
    qwen_api_key = get_qwen_api_key()
    if not qwen_api_key:
        print("[X] 未提供千问 API Key，无法生成图片")
        return

    generated_images, book_dir = generate_storybook(
        pages=pages,
        character_desc=character_desc,
        style=style,
        api_key=qwen_api_key,
        model=DEFAULT_QWEN_MODEL,
        size=DEFAULT_IMAGE_SIZE
    )

    if not generated_images:
        print("[X] 没有图片生成成功")
        return

    # 11. 排版输出
    print()
    print("正在排版绘本页面...")
    for item in generated_images:
        layout = create_layout_page(
            item["image"], item["text"], item["page"], len(pages)
        )
        layout_path = os.path.join(book_dir, f"layout_{item['page']:02d}.png")
        layout.save(layout_path)
        print(f"  [OK] 排版页 {item['page']}: {layout_path}")

    # 12. 保存故事脚本
    script_path = os.path.join(book_dir, "story_script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(
            {"title": story.get("title"), "idea": idea, "character": character_desc, "pages": pages},
            f, ensure_ascii=False, indent=2
        )
    print(f"  [OK] 故事脚本已保存: {script_path}")

    title = story.get("title", "我的故事")
    print()
    print("=" * 50)
    print(f"绘本《{title}》生成完成！")
    print(f"输出目录: {book_dir}")
    print("=" * 50)


if __name__ == "__main__":
    main()
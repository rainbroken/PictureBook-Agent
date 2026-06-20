#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 YAML 文件生成绘本
读取 storybooks 目录下的 story_input.yaml，
调用 DeepSeek 生成故事脚本 + 千问生图 + 排版，
将所有图片和脚本保存在 YAML 所在的同一目录下。

用法:
  python generate_from_yaml.py                  # 自动找到所有未生成的 YAML
  python generate_from_yaml.py storybook_20260620_004739  # 指定某个绘本目录
"""

import os
import sys
import io
import json
import shutil
import random
import contextlib
import builtins

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

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storybook_generator import (
    generate_storybook, create_layout_page,
    get_api_key as get_qwen_api_key, OUTPUT_DIR,
    DEFAULT_QWEN_MODEL, DEFAULT_IMAGE_SIZE,
    STYLE_TEMPLATES,
    build_qwen_prompt, _clean_prompt, _is_wan26_model,
    _build_reference_prompt,
    generate_image_sync, generate_image_with_qwen,
    generate_image_with_reference,
    REF_MODEL, FIXED_SEED, REFERENCE_NEGATIVE_PROMPT,
    CHARACTER_CONSISTENCY_MODE, USE_CHARACTER_PREFIX,
)
from easy_storybook import (
    generate_story_with_deepseek,
    get_deepseek_api_key,
)
from prompt_optimizer import PromptOptimizer




def _prepare_character_desc(character):
    """优化角色描述"""
    character_desc = character
    if character:
        optimizer = PromptOptimizer()
        optimized, _ = optimizer.optimize(user_input=character, style_prompt="")
        if optimized and optimized != character:
            character_desc = f"{character}, {optimized}"
    return character_desc


def generate_story_only(book_id):
    """
    从 YAML 读取输入 -> DeepSeek 生成故事 -> 保存故事脚本
    返回故事数据 dict 或 None
    """
    yaml_data = load_yaml(book_id)
    if not yaml_data:
        return None

    character = yaml_data.get("character", "")
    idea = yaml_data.get("idea", "")
    num_pages = yaml_data.get("num_pages", 4)

    book_dir = os.path.join(OUTPUT_DIR, book_id)

    print()
    print("=" * 50)
    print(f"  生成故事脚本: {book_id}")
    print("=" * 50)

    # --- 获取 DeepSeek API Key ---
    ds_key = get_deepseek_api_key()
    if not ds_key:
        print("[X] 未配置 DeepSeek API Key")
        return None

    # --- 角色描述优化 ---
    character_desc = _prepare_character_desc(character)

    # --- DeepSeek 生成故事 ---
    print(f"正在调用 DeepSeek 生成 {num_pages} 页故事...")
    story = generate_story_with_deepseek(idea, character_desc, num_pages, ds_key)
    if not story:
        print("[X] 故事生成失败")
        return None

    title = story.get("title", "未命名")
    print(f"  [OK] 故事: 《{title}》")

    # --- 保存故事脚本 ---
    pages = [
        {"page": i + 1, "text": p["text"], "scene": p["scene"]}
        for i, p in enumerate(story.get("pages", []))
    ]
    script_data = {
        "title": story.get("title"),
        "idea": idea,
        "character": character_desc,
        "pages": pages,
    }
    script_path = os.path.join(book_dir, "story_script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script_data, f, ensure_ascii=False, indent=2)

    print(f"  [OK] 故事脚本已保存: story_script.json")
    return script_data


def generate_first_page_candidates(book_id, num_candidates=3):
    """
    读取已保存的故事脚本 -> 生成 num_candidates 张首页候选图（随机种子）
    前置条件：story_script.json 已存在（由 generate_story_only 生成）

    返回: True/False
    """
    yaml_data = load_yaml(book_id)
    if not yaml_data:
        return False

    style_info = yaml_data.get("style", {})
    style_key = style_info.get("id", "1")
    style = STYLE_TEMPLATES.get(style_key, STYLE_TEMPLATES["1"])

    book_dir = os.path.join(OUTPUT_DIR, book_id)

    # --- 读取已保存的故事脚本 ---
    script_path = os.path.join(book_dir, "story_script.json")
    if not os.path.isfile(script_path):
        print("[X] 找不到故事脚本，请先生成故事")
        return False
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    pages = script.get("pages", [])
    character_desc = script.get("character", "")
    if not pages:
        print("[X] 故事脚本无页面")
        return False

    print()
    print("=" * 50)
    print(f"  生成首页候选: {book_id}")
    print("=" * 50)

    # --- 获取千问 API Key ---
    qwen_key = get_qwen_api_key()
    if not qwen_key:
        print("[X] 未配置千问 API Key")
        return False

    # --- 构建首页提示词 ---
    first_page = pages[0]
    optimizer = PromptOptimizer(enable_quality_tags=True, enable_auto_negative=False)
    optimized_scene, _ = optimizer.optimize(
        user_input=first_page["scene"], character_desc="", style_prompt=""
    )
    qwen_prompt = build_qwen_prompt(
        scene=_clean_prompt(optimized_scene),
        character_desc=character_desc if USE_CHARACTER_PREFIX else "",
        style_prompt=style["prompt"],
    )

    # --- 生成 num_candidates 张首页候选（不同风格修饰 + 随机种子）---
    print(f"正在生成 {num_candidates} 张首页候选图（不同风格修饰）...")
    model = DEFAULT_QWEN_MODEL
    size = DEFAULT_IMAGE_SIZE
    candidates = []

    # 3种不同的氛围修饰，确保候选图视觉差异明显
    mood_variants = [
        "bright and cheerful atmosphere, warm sunlight",
        "soft and dreamy atmosphere, gentle pastel tones",
        "dramatic and vivid atmosphere, rich saturated colors",
    ]
    # 3个种子分散在大范围内，确保差异大
    seed_ranges = [(0, 333333), (333333, 666666), (666666, 999999)]
    for idx in range(num_candidates):
        lo, hi = seed_ranges[idx % len(seed_ranges)]
        seed = random.randint(lo, hi)
        # 在提示词末尾附加不同的氛围修饰
        mood = mood_variants[idx % len(mood_variants)]
        variant_prompt = qwen_prompt + ", " + mood
        print(f"  候选 {idx + 1}/{num_candidates} (seed={seed}, mood={mood[:30]}...)...")
        img = None
        if _is_wan26_model(model):
            img, _ = generate_image_sync(
                prompt=variant_prompt, api_key=qwen_key, model=model, size=size, seed=seed,
            )
        else:
            img, _ = generate_image_with_qwen(
                prompt=variant_prompt, api_key=qwen_key, model=model, size=size, seed=seed,
            )
        if img is not None:
            cpath = os.path.join(book_dir, f"candidate_{idx + 1}.png")
            img.save(cpath)
            candidates.append({"index": idx + 1, "seed": seed, "path": cpath})
            print(f"    [OK] 已保存: candidate_{idx + 1}.png")
        else:
            print(f"    [X] 候选 {idx + 1} 生成失败")

    if not candidates:
        print("[X] 所有候选图生成失败")
        return False

    print(f"\n  [OK] 共生成 {len(candidates)} 张候选图，等待用户选择")
    return True


def select_first_page_and_continue(book_id, chosen_index):
    """
    用户选择了第 chosen_index 个候选首页后:
    1. 将选中的候选图移为 page_01.png
    2. 删除其他候选图
    3. 用选中图片作为参考图，生成第 2 页起的所有图片
    4. 排版 + 更新脚本

    chosen_index: 1~5
    返回: True/False
    """
    yaml_data = load_yaml(book_id)
    if not yaml_data:
        return False

    style_info = yaml_data.get("style", {})
    style_key = style_info.get("id", "1")
    style = STYLE_TEMPLATES.get(style_key, STYLE_TEMPLATES["1"])

    book_dir = os.path.join(OUTPUT_DIR, book_id)

    # --- 读取已保存的故事脚本 ---
    script_path = os.path.join(book_dir, "story_script.json")
    if not os.path.isfile(script_path):
        print("[X] 找不到故事脚本")
        return False
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    pages = script.get("pages", [])
    character_desc = script.get("character", "")
    total = len(pages)
    if total < 1:
        print("[X] 故事脚本无页面")
        return False

    # --- 步骤 1: 选中候选 -> page_01.png，删除其他候选 ---
    chosen_path = os.path.join(book_dir, f"candidate_{chosen_index}.png")
    if not os.path.isfile(chosen_path):
        print(f"[X] 候选图 {chosen_index} 不存在")
        return False

    from PIL import Image as PILImage
    chosen_img = PILImage.open(chosen_path)
    page_01_path = os.path.join(book_dir, "page_01.png")
    chosen_img.save(page_01_path)
    print(f"  [OK] 候选 {chosen_index} 已选为首页: page_01.png")

    # 删除所有候选图
    for i in range(1, 4):
        cp = os.path.join(book_dir, f"candidate_{i}.png")
        if os.path.isfile(cp):
            os.remove(cp)
            print(f"  删除候选: candidate_{i}.png")

    # --- 步骤 2: 生成第 2 页起的图片 ---
    qwen_key = get_qwen_api_key()
    if not qwen_key:
        print("[X] 未配置千问 API Key")
        return False

    model = DEFAULT_QWEN_MODEL
    size = DEFAULT_IMAGE_SIZE
    optimizer = PromptOptimizer(enable_quality_tags=True, enable_auto_negative=False)
    use_reference = (CHARACTER_CONSISTENCY_MODE == "reference") and _is_wan26_model(model)

    if use_reference:
        print(f"  [REF] 使用参考图模式，保持角色一致")

    for i in range(1, total):  # 从第2页开始
        page = pages[i]
        scene = page["scene"]
        page_num = page["page"]

        print(f"  [{page_num}/{total}] 生成第 {page_num} 页...")
        optimized_scene, _ = optimizer.optimize(
            user_input=scene, character_desc="", style_prompt=""
        )
        qwen_prompt = build_qwen_prompt(
            scene=_clean_prompt(optimized_scene),
            character_desc=character_desc if USE_CHARACTER_PREFIX else "",
            style_prompt=style["prompt"],
        )

        img = None
        if use_reference and chosen_img is not None:
            ref_prompt = _build_reference_prompt(
                character_desc=character_desc,
                scene_desc=_clean_prompt(optimized_scene),
                style_prompt=style["prompt"],
            )
            print(f"    [prompt] 参考图模式")
            img, _ = generate_image_with_reference(
                prompt=ref_prompt, ref_image=chosen_img,
                api_key=qwen_key, model=REF_MODEL, size=size,
                seed=FIXED_SEED, negative_prompt=REFERENCE_NEGATIVE_PROMPT,
            )
            if img is None:
                print("    [!] 参考图模式失败，回退到普通文生图")

        if img is None:
            if _is_wan26_model(model):
                img, _ = generate_image_sync(
                    prompt=qwen_prompt, api_key=qwen_key, model=model,
                    size=size, seed=FIXED_SEED,
                )
            else:
                img, _ = generate_image_with_qwen(
                    prompt=qwen_prompt, api_key=qwen_key, model=model,
                    size=size, seed=FIXED_SEED,
                )

        if img is None:
            print(f"    [X] 第 {page_num} 页生成失败")
            continue

        img_path = os.path.join(book_dir, f"page_{page_num:02d}.png")
        img.save(img_path)
        print(f"    [OK] 已保存: page_{page_num:02d}.png")

    # --- 步骤 3: 排版 ---
    print(f"  正在排版绘本页面...")
    for page in pages:
        page_num = page["page"]
        raw_path = os.path.join(book_dir, f"page_{page_num:02d}.png")
        if not os.path.isfile(raw_path):
            continue
        img = PILImage.open(raw_path)
        layout = create_layout_page(img, page["text"], page_num, total)
        layout_path = os.path.join(book_dir, f"layout_{page_num:02d}.png")
        layout.save(layout_path)
        print(f"    [OK] 排版页 {page_num}")

    print()
    print("=" * 50)
    print(f"  绘本《{script.get('title', '未命名')}》生成完成！")
    print(f"  输出目录: {book_dir}")
    print("=" * 50)
    return True


def find_yaml_dirs():
    """扫描 storybooks 目录，找出所有含 story_input.yaml 但尚未生成图片的目录"""
    pending = []
    if not os.path.isdir(OUTPUT_DIR):
        return pending
    for name in sorted(os.listdir(OUTPUT_DIR)):
        book_dir = os.path.join(OUTPUT_DIR, name)
        if not os.path.isdir(book_dir) or not name.startswith("storybook_"):
            continue
        yaml_path = os.path.join(book_dir, "story_input.yaml")
        script_path = os.path.join(book_dir, "story_script.json")
        if os.path.isfile(yaml_path) and not os.path.isfile(script_path):
            pending.append(name)
    return pending


def load_yaml(book_id):
    """读取指定绘本目录下的 story_input.yaml"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    yaml_path = os.path.join(book_dir, "story_input.yaml")
    if not os.path.isfile(yaml_path):
        print(f"  [X] YAML 文件不存在: {yaml_path}")
        return None
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def generate_from_yaml(book_id):
    """
    从 YAML 读取输入 → DeepSeek 生成故事 → 千问生图 → 排版 → 保存到 YAML 同目录

    核心流程:
    1. 读取 story_input.yaml 获取 character, idea, num_pages, style
    2. 调用 DeepSeek 生成故事脚本
    3. 调用 generate_storybook 生成图片（会创建新的临时目录）
    4. 将生成的文件移到 YAML 所在的目录
    5. 排版 + 保存 story_script.json
    """
    yaml_data = load_yaml(book_id)
    if not yaml_data:
        return False

    character = yaml_data.get("character", "")
    idea = yaml_data.get("idea", "")
    num_pages = yaml_data.get("num_pages", 4)
    style_info = yaml_data.get("style", {})
    style_key = style_info.get("id", "1")
    style = STYLE_TEMPLATES.get(style_key, STYLE_TEMPLATES["1"])

    book_dir = os.path.join(OUTPUT_DIR, book_id)

    print()
    print("=" * 50)
    print(f"  从 YAML 生成绘本: {book_id}")
    print("=" * 50)
    print(f"  主角: {character}")
    print(f"  想法: {idea}")
    print(f"  页数: {num_pages}")
    print(f"  风格: {style['name']}")
    print()

    # --- 步骤 1: 获取 API Key ---
    ds_key = get_deepseek_api_key()
    if not ds_key:
        print("[X] 未配置 DeepSeek API Key，无法生成故事")
        return False

    qwen_key = get_qwen_api_key()
    if not qwen_key:
        print("[X] 未配置千问 API Key，无法生成图片")
        return False

    # --- 步骤 2: 角色描述优化 ---
    character_desc = character
    if character:
        optimizer = PromptOptimizer()
        optimized, _ = optimizer.optimize(user_input=character, style_prompt="")
        if optimized and optimized != character:
            character_desc = f"{character}, {optimized}"

    # --- 步骤 3: DeepSeek 生成故事 ---
    print(f"[1/4] 正在调用 DeepSeek 生成 {num_pages} 页故事...")
    story = generate_story_with_deepseek(idea, character_desc, num_pages, ds_key)
    if not story:
        print("[X] 故事生成失败，请检查 DeepSeek API Key 或网络")
        return False

    title = story.get("title", "未命名")
    print(f"  [OK] 故事生成成功: 《{title}》")
    for i, p in enumerate(story.get("pages", []), 1):
        print(f"    第{i}页: {p.get('text', '')[:50]}...")

    # --- 步骤 4: 千问生图 ---
    pages = [
        {"page": i + 1, "text": p["text"], "scene": p["scene"]}
        for i, p in enumerate(story.get("pages", []))
    ]
    total = len(pages)

    print(f"\n[2/4] 正在调用千问生成 {total} 页插画...")
    # generate_storybook 会创建新的时间戳目录
    generated_images, gen_book_dir = generate_storybook(
        pages=pages,
        character_desc=character_desc,
        style=style,
        api_key=qwen_key,
        model=DEFAULT_QWEN_MODEL,
        size=DEFAULT_IMAGE_SIZE,
    )

    if not generated_images:
        print("[X] 图片生成失败")
        return False

    # --- 步骤 5: 移动文件到 YAML 所在目录 ---
    print(f"\n[3/4] 正在移动文件到 {book_id}...")
    moved_files = []
    for fname in os.listdir(gen_book_dir):
        src = os.path.join(gen_book_dir, fname)
        dst = os.path.join(book_dir, fname)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.move(src, dst)
            moved_files.append(fname)
            print(f"  移动: {fname}")
    # 删除 generate_storybook 创建的临时目录
    if os.path.isdir(gen_book_dir):
        try:
            shutil.rmtree(gen_book_dir)
        except OSError:
            pass
    print(f"  共移动 {len(moved_files)} 个文件")

    # --- 步骤 6: 排版 ---
    print(f"\n[4/4] 正在排版绘本页面...")
    for item in generated_images:
        layout = create_layout_page(
            item["image"], item["text"], item["page"], total
        )
        layout_path = os.path.join(book_dir, f"layout_{item['page']:02d}.png")
        layout.save(layout_path)
        print(f"  [OK] 排版页 {item['page']}: layout_{item['page']:02d}.png")

    # --- 步骤 7: 保存故事脚本 ---
    script_path = os.path.join(book_dir, "story_script.json")
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": story.get("title"),
                "idea": idea,
                "character": character_desc,
                "pages": pages,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"  [OK] 故事脚本已保存: story_script.json")

    # --- 完成 ---
    print()
    print("=" * 50)
    print(f"  绘本《{title}》生成完成！")
    print(f"  输出目录: {book_dir}")
    print(f"  文件列表:")
    for fname in sorted(os.listdir(book_dir)):
        print(f"    {fname}")
    print("=" * 50)

    return True


def main():
    print("=" * 50)
    print("  YAML → 绘本生成器")
    print("  从 story_input.yaml 读取输入，生成完整绘本")
    print("=" * 50)

    # 检查是否有命令行参数指定了某个绘本目录
    if len(sys.argv) > 1:
        book_id = sys.argv[1]
        if not book_id.startswith("storybook_"):
            book_id = f"storybook_{book_id}"
        yaml_data = load_yaml(book_id)
        if not yaml_data:
            print(f"[X] 找不到 {book_id} 的 YAML 文件")
            return
        # 检查是否已生成
        script_path = os.path.join(OUTPUT_DIR, book_id, "story_script.json")
        if os.path.isfile(script_path):
            print(f"[!] {book_id} 已生成过绘本图片")
            print(f"    如需重新生成，请先删除 {script_path}")
            return
        generate_from_yaml(book_id)
        return

    # 没有指定参数 → 找出所有未生成的 YAML
    pending = find_yaml_dirs()

    if not pending:
        print()
        print("[!] 没有找到未生成的 YAML 文件")
        print("    请先使用 collect_input_web.py 保存输入，")
        print("    或指定绘本目录名运行:")
        print("    python generate_from_yaml.py storybook_20260620_004739")
        return

    print()
    print(f"找到 {len(pending)} 个待生成的绘本:")
    for i, name in enumerate(pending, 1):
        yaml_data = load_yaml(name)
        char = yaml_data.get("character", "")[:30]
        idea = yaml_data.get("idea", "")[:30]
        print(f"  [{i}] {name}")
        print(f"      主角: {char}")
        print(f"      想法: {idea}")

    # 询问用户选择
    print()
    choice = input("请输入序号生成对应绘本 (直接回车=全部生成, 0=退出): ").strip()

    if choice == "0":
        print("已退出")
        return

    if not choice:
        # 全部生成
        for name in pending:
            print()
            generate_from_yaml(name)
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(pending):
            generate_from_yaml(pending[idx])
        else:
            print("[!] 无效序号")
    except ValueError:
        print("[!] 请输入数字")


if __name__ == "__main__":
    main()

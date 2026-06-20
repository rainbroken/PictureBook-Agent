#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绘本输入收集 + 生成器 - 前端网站
收集用户输入的主角描述、故事想法、页数、绘本风格，
保存到 story_input.yaml，然后调用 generate_from_yaml 生成绘本图片，
在前端展示生成的绘本页面。

运行: python collect_input_web.py
访问: http://127.0.0.1:5001
"""

import os
import sys
import io
import json
import uuid
import shutil
import contextlib
import threading
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

from datetime import datetime
from flask import Flask, jsonify, request, render_template_string, send_from_directory

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storybook_generator import STYLE_TEMPLATES, OUTPUT_DIR, QWEN_MODELS, DEFAULT_QWEN_MODEL, DEFAULT_IMAGE_SIZE
from easy_storybook import get_deepseek_api_key
from storybook_generator import get_api_key as get_qwen_api_key
from generate_from_yaml import (
    generate_from_yaml, load_yaml as _load_yaml_data,
    generate_story_only, generate_first_page_candidates, select_first_page_and_continue,
)

app = Flask(__name__)

# ==================== 后台任务 ====================
_jobs = {}
_jobs_lock = threading.Lock()


def _set_job(job_id, **kwargs):
    with _jobs_lock:
        if job_id not in _jobs:
            _jobs[job_id] = {"status": "pending", "progress": 0, "message": "", "book_id": None}
        _jobs[job_id].update(kwargs)


def _silent_call(func, *args, **kwargs):
    """静默调用 -- 避免 Windows GBK 编码问题"""
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        return func(*args, **kwargs)


def _run_story_job(job_id, book_id):
    """后台线程：调用 DeepSeek 生成故事脚本"""
    try:
        _set_job(job_id, status="running", progress=5, message="正在生成故事脚本...")

        ds_key = get_deepseek_api_key()
        if not ds_key:
            _set_job(job_id, status="error", message="未配置 DeepSeek API Key")
            return

        result = _silent_call(generate_story_only, book_id)

        if result is not None:
            _set_job(job_id, status="story_ready", progress=30, message="故事已生成，请查看编辑！", book_id=book_id)
        else:
            _set_job(job_id, status="error", message="故事生成失败，请检查 DeepSeek API Key 或网络")
    except Exception as e:
        _set_job(job_id, status="error", message=str(e))


def _run_candidate_job(job_id, book_id):
    """后台线程：调用 generate_first_page_candidates 生成3张候选首页"""
    try:
        _set_job(job_id, status="running", progress=35, message="正在生成3张首页候选...")

        qwen_key = get_qwen_api_key()
        if not qwen_key:
            _set_job(job_id, status="error", message="未配置千问 API Key")
            return

        success = _silent_call(generate_first_page_candidates, book_id)

        if success:
            _set_job(job_id, status="candidates_ready", progress=50, message="3张首页候选已生成，请选择！", book_id=book_id)
        else:
            _set_job(job_id, status="error", message="候选图生成失败，请检查千问 API Key 或网络")
    except Exception as e:
        _set_job(job_id, status="error", message=str(e))


def _run_continue_job(job_id, book_id, chosen_index):
    """后台线程：用户选好首页后，生成剩余页面"""
    try:
        _set_job(job_id, status="running", progress=55, message="正在生成后续页面...")
        success = _silent_call(select_first_page_and_continue, book_id, chosen_index)
        if success:
            _set_job(job_id, status="done", progress=100, message="绘本生成完成！", book_id=book_id)
        else:
            _set_job(job_id, status="error", message="后续页面生成失败")
    except Exception as e:
        _set_job(job_id, status="error", message=str(e))


# ==================== API 路由 ====================

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/config")
def api_config():
    """返回可用的绘本风格列表和 API Key 状态"""
    return jsonify({
        "styles": [
            {"id": k, "name": v["name"], "prompt": v["prompt"]}
            for k, v in STYLE_TEMPLATES.items()
        ],
        "has_deepseek": bool(get_deepseek_api_key()),
        "has_qwen": bool(get_qwen_api_key()),
    })


@app.route("/api/save", methods=["POST"])
def api_save():
    """接收用户输入，保存为 YAML 文件"""
    data = request.get_json(force=True)

    character = (data.get("character") or "").strip()
    idea = (data.get("idea") or "").strip()
    num_pages = int(data.get("num_pages") or 4)
    style_key = str(data.get("style") or "1")

    if not character:
        return jsonify({"error": "请填写主角描述"}), 400
    if not idea:
        return jsonify({"error": "请填写故事想法"}), 400
    if not 3 <= num_pages <= 8:
        return jsonify({"error": "页数需在 3-8 之间"}), 400
    if style_key not in STYLE_TEMPLATES:
        return jsonify({"error": "无效的绘本风格"}), 400

    style = STYLE_TEMPLATES[style_key]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    book_dir = os.path.join(OUTPUT_DIR, f"storybook_{timestamp}")
    os.makedirs(book_dir, exist_ok=True)

    yaml_data = {
        "character": character,
        "idea": idea,
        "num_pages": num_pages,
        "style": {
            "id": style_key,
            "name": style["name"],
            "prompt": style["prompt"],
        },
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    yaml_path = os.path.join(book_dir, "story_input.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    book_id = os.path.basename(book_dir)
    return jsonify({
        "ok": True,
        "book_id": book_id,
        "yaml_path": yaml_path,
        "data": yaml_data,
    })


@app.route("/api/generate/<book_id>", methods=["POST"])
def api_generate(book_id):
    """启动故事生成任务（第一步：DeepSeek 生成故事）"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    if not os.path.isdir(book_dir):
        return jsonify({"error": "绘本目录不存在"}), 404
    yaml_path = os.path.join(book_dir, "story_input.yaml")
    if not os.path.isfile(yaml_path):
        return jsonify({"error": "YAML 文件不存在"}), 404

    job_id = str(uuid.uuid4())
    _set_job(job_id, status="queued", progress=0, message="任务已加入队列...")

    t = threading.Thread(target=_run_story_job, args=(job_id, book_id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "book_id": book_id})


@app.route("/api/story/<book_id>")
def api_get_story(book_id):
    """返回已生成的故事脚本"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    script_path = os.path.join(book_dir, "story_script.json")
    if not os.path.isfile(script_path):
        return jsonify({"error": "故事脚本不存在"}), 404
    with open(script_path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/story/<book_id>", methods=["PUT"])
def api_update_story(book_id):
    """用户编辑后更新故事脚本"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    script_path = os.path.join(book_dir, "story_script.json")
    if not os.path.isfile(script_path):
        return jsonify({"error": "故事脚本不存在"}), 404
    data = request.get_json(force=True)
    # 保留原有字段，仅更新用户可编辑的部分
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    if "title" in data:
        script["title"] = str(data["title"]).strip()
    if "pages" in data and isinstance(data["pages"], list):
        updated_pages = []
        for i, p in enumerate(data["pages"]):
            updated_pages.append({
                "page": i + 1,
                "text": str(p.get("text", "")).strip(),
                "scene": str(p.get("scene", "")).strip(),
            })
        script["pages"] = updated_pages
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "script": script})


@app.route("/api/generate-candidates/<book_id>", methods=["POST"])
def api_generate_candidates(book_id):
    """启动候选首页生成任务（第二步：千问生图）"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    if not os.path.isdir(book_dir):
        return jsonify({"error": "绘本目录不存在"}), 404
    script_path = os.path.join(book_dir, "story_script.json")
    if not os.path.isfile(script_path):
        return jsonify({"error": "请先生成故事"}), 400

    job_id = str(uuid.uuid4())
    _set_job(job_id, status="queued", progress=30, message="正在准备生成候选图...")
    t = threading.Thread(target=_run_candidate_job, args=(job_id, book_id), daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "book_id": book_id})


@app.route("/api/jobs/<job_id>")
def api_job_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(job)


@app.route("/api/candidates/<book_id>")
def api_candidates(book_id):
    """返回某绘本的候选首页图片列表"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    if not os.path.isdir(book_dir):
        return jsonify({"error": "绘本目录不存在"}), 404
    candidates = []
    for i in range(1, 4):
        fname = f"candidate_{i}.png"
        if os.path.isfile(os.path.join(book_dir, fname)):
            candidates.append({
                "index": i,
                "url": f"/api/books/{book_id}/image/{fname}",
            })
    return jsonify({"candidates": candidates, "book_id": book_id})


@app.route("/api/select-candidate/<book_id>/<int:chosen_index>", methods=["POST"])
def api_select_candidate(book_id, chosen_index):
    """用户选择第 chosen_index 个候选首页，启动后续生成"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    if not os.path.isdir(book_dir):
        return jsonify({"error": "绘本目录不存在"}), 404
    # 验证候选图存在
    chosen_path = os.path.join(book_dir, f"candidate_{chosen_index}.png")
    if not os.path.isfile(chosen_path):
        return jsonify({"error": f"候选图 {chosen_index} 不存在"}), 404
    job_id = str(uuid.uuid4())
    _set_job(job_id, status="queued", progress=50, message="正在准备后续生成...")
    t = threading.Thread(target=_run_continue_job, args=(job_id, book_id, chosen_index), daemon=True)
    t.start()
    return jsonify({"job_id": job_id, "book_id": book_id, "chosen_index": chosen_index})


@app.route("/api/books")
def api_list_books():
    """列出所有绘本目录"""
    books = []
    if not os.path.isdir(OUTPUT_DIR):
        return jsonify(books)
    for name in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        book_dir = os.path.join(OUTPUT_DIR, name)
        if not os.path.isdir(book_dir) or not name.startswith("storybook_"):
            continue
        # 基本信息：优先从 YAML 读取，否则从 JSON
        character = ""
        idea = ""
        num_pages = 0
        style_name = ""

        yaml_path = os.path.join(book_dir, "story_input.yaml")
        if os.path.isfile(yaml_path):
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                character = data.get("character", "")
                idea = data.get("idea", "")
                num_pages = data.get("num_pages", 0)
                style_name = data.get("style", {}).get("name", "")
            except (yaml.YAMLError, OSError):
                pass

        script_path = os.path.join(book_dir, "story_script.json")
        title = ""
        if os.path.isfile(script_path):
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not character:
                    character = data.get("character", "")
                    idea = data.get("idea", "")
                title = data.get("title", "")
            except (json.JSONDecodeError, OSError):
                pass

        has_images = os.path.isfile(script_path)
        has_story = os.path.isfile(script_path)
        layout_count = len([
            f for f in os.listdir(book_dir)
            if f.startswith("layout_") and f.endswith(".png")
        ])
        candidate_count = len([
            f for f in os.listdir(book_dir)
            if f.startswith("candidate_") and f.endswith(".png")
        ])

        ts = name.replace("storybook_", "")
        try:
            created = datetime.strptime(ts, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            created = ts

        books.append({
            "id": name,
            "character": character,
            "idea": idea,
            "num_pages": num_pages,
            "style_name": style_name,
            "created_at": created,
            "has_images": has_images,
            "has_story": has_story,
            "title": title,
            "layout_count": layout_count,
            "has_candidates": candidate_count > 0,
            "candidate_count": candidate_count,
        })
    return jsonify(books)


@app.route("/api/books/<book_id>/detail")
def api_book_detail(book_id):
    """返回绘本详情（含图片 URL）"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    if not os.path.isdir(book_dir):
        return jsonify({"error": "绘本不存在"}), 404

    result = {"id": book_id}

    # YAML 输入信息
    yaml_path = os.path.join(book_dir, "story_input.yaml")
    if os.path.isfile(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as f:
            result["input"] = yaml.safe_load(f)

    # 故事脚本 + 图片 URL
    script_path = os.path.join(book_dir, "story_script.json")
    if os.path.isfile(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)
        pages = []
        for p in script.get("pages", []):
            num = p.get("page", len(pages) + 1)
            layout = f"layout_{num:02d}.png"
            has_layout = os.path.isfile(os.path.join(book_dir, layout))
            pages.append({
                **p,
                "page": num,
                "layout_url": f"/api/books/{book_id}/image/{layout}" if has_layout else None,
            })
        result["title"] = script.get("title", "")
        result["pages"] = pages

    return jsonify(result)


@app.route("/api/books/<book_id>/image/<filename>")
def api_book_image(book_id, filename):
    """返回绘本图片"""
    book_dir = os.path.join(OUTPUT_DIR, book_id)
    if not os.path.isdir(book_dir):
        return jsonify({"error": "绘本不存在"}), 404
    safe = os.path.basename(filename)
    if not safe.endswith(".png"):
        return jsonify({"error": "无效文件"}), 400
    return send_from_directory(book_dir, safe)


# ==================== 前端页面 ====================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>&#x1F4D6; 绘本工坊</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=ZCOOL+KuaiLe&family=Ma+Shan+Zheng&display=swap" rel="stylesheet">
<style>
:root {
  --sky: #b8e8ff;
  --grass: #c8f7c5;
  --sun: #ffe566;
  --pink: #ff8fab;
  --pink-dark: #ff6b8a;
  --blue: #74b9ff;
  --mint: #7bed9f;
  --card: #fffef8;
  --text: #4a3728;
  --muted: #9a8575;
  --crayon: #ff9f43;
  --shadow: 0 6px 0 rgba(0,0,0,.08), 0 12px 28px rgba(255,143,171,.15);
  --radius: 24px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'ZCOOL KuaiLe', cursive, sans-serif;
  background: linear-gradient(180deg, var(--sky) 0%, #fff5e6 45%, var(--grass) 100%);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}
.deco { position: fixed; pointer-events: none; z-index: 0; font-size: 1.6rem; opacity: .55; animation: float 4s ease-in-out infinite; }
.deco:nth-child(1) { top: 8%; left: 5%; animation-delay: 0s; }
.deco:nth-child(2) { top: 15%; right: 8%; animation-delay: 1s; font-size: 2rem; }
.deco:nth-child(3) { bottom: 20%; left: 10%; animation-delay: 2s; }
.deco:nth-child(4) { bottom: 12%; right: 6%; animation-delay: .5s; font-size: 1.3rem; }
@keyframes float { 0%,100% { transform: translateY(0) rotate(-3deg); } 50% { transform: translateY(-12px) rotate(3deg); } }
@keyframes pop { 0% { transform: scale(.8); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }

header, main { position: relative; z-index: 1; }
header { text-align: center; padding: 1.8rem 1rem .8rem; }
header h1 {
  font-family: 'Ma Shan Zheng', 'ZCOOL KuaiLe', cursive;
  font-size: 2.8rem;
  color: var(--pink-dark);
  text-shadow: 3px 3px 0 var(--sun), 5px 5px 0 rgba(255,143,171,.3);
  animation: float 4s ease-in-out infinite;
  letter-spacing: .08em;
}
header p { color: var(--muted); margin-top: .5rem; font-size: 1rem; }

nav.tabs {
  display: flex; justify-content: center; gap: .8rem;
  padding: 0 1rem 1.2rem; flex-wrap: wrap;
}
nav.tabs button {
  font-family: inherit; font-size: 1.05rem;
  padding: .65rem 1.8rem;
  border: 3px solid var(--text);
  border-radius: 999px;
  background: var(--card);
  color: var(--text);
  cursor: pointer;
  transition: all .15s;
  box-shadow: 0 4px 0 rgba(0,0,0,.12);
}
nav.tabs button:hover { transform: translateY(-2px); }
nav.tabs button.active {
  background: var(--pink); color: #fff;
  border-color: var(--pink-dark);
  box-shadow: 0 4px 0 var(--pink-dark);
}

main { max-width: 700px; margin: 0 auto; padding: 0 1.2rem 3rem; }
.panel { display: none; animation: pop .4s ease; }
.panel.active { display: block; }

.form-card {
  background: var(--card); border-radius: var(--radius);
  padding: 2rem; box-shadow: var(--shadow);
  border: 3px solid var(--text);
}
.form-group { margin-bottom: 1.2rem; }
.form-group label {
  display: block; font-size: 1rem; margin-bottom: .4rem; color: var(--text);
}
.form-group label::before { content: '\2B50 '; font-size: .85rem; }
.form-group .hint { font-size: .82rem; color: var(--muted); margin-top: .3rem; }
input[type=text], input[type=number], textarea, select {
  width: 100%; font-family: inherit; font-size: .95rem;
  padding: .75rem 1rem;
  border: 2.5px solid var(--text); border-radius: 16px;
  background: #fff; color: var(--text);
}
input:focus, textarea:focus, select:focus {
  outline: none; border-color: var(--pink);
  box-shadow: 0 0 0 3px rgba(255,143,171,.25);
}
textarea { resize: vertical; min-height: 80px; }

.style-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .6rem; }
.style-option {
  padding: .75rem; border: 2.5px solid var(--text); border-radius: 16px;
  cursor: pointer; text-align: center; font-size: .92rem;
  background: #fff; transition: all .15s;
}
.style-option.selected {
  background: var(--sun); border-color: var(--crayon);
  transform: rotate(-1deg);
}

.btn {
  font-family: inherit; font-size: 1rem;
  padding: .75rem 1.6rem; border: 2.5px solid var(--text);
  border-radius: 999px; cursor: pointer; font-weight: bold;
  transition: all .15s;
  box-shadow: 0 4px 0 rgba(0,0,0,.12);
}
.btn-primary { background: var(--pink); color: #fff; border-color: var(--pink-dark); box-shadow: 0 4px 0 var(--pink-dark); }
.btn-primary:hover { transform: translateY(-2px); }
.btn-primary:disabled { opacity: .5; cursor: not-allowed; transform: none; }
.btn-secondary { background: var(--card); color: var(--text); }
.btn-secondary:hover { background: var(--sky); }
.btn-row { display: flex; gap: .7rem; justify-content: flex-end; margin-top: 1.5rem; flex-wrap: wrap; }

/* API 状态徽章 */
.api-status { display: flex; gap: .6rem; justify-content: center; flex-wrap: wrap; margin-bottom: 1.2rem; }
.badge { font-size: .82rem; padding: .3rem .8rem; border-radius: 999px; background: #fff; border: 2px solid var(--text); }
.badge.ok { background: #d4edda; border-color: var(--mint); }
.badge.err { background: #ffe0e0; border-color: #ff6b6b; }

/* 保存结果展示区 */
.result-card {
  background: #dff9fb; border-radius: var(--radius);
  padding: 1.5rem; box-shadow: var(--shadow);
  border: 3px solid var(--mint);
  margin-top: 1.5rem;
}
.result-card h3 {
  font-size: 1.3rem; color: #2ed573; text-align: center; margin-bottom: 1rem;
}
.result-card h3::before { content: '\2714 '; }
.result-table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
.result-table td { padding: .6rem .8rem; border-bottom: 2px dashed #c8f7c5; font-size: .95rem; vertical-align: top; }
.result-table td:first-child { width: 100px; color: var(--muted); font-weight: bold; }

/* 进度条 */
.progress-wrap { margin: 1.5rem 0; }
.progress-bar {
  height: 14px; background: #eee;
  border-radius: 999px; overflow: hidden;
  border: 2px solid var(--text);
}
.progress-fill {
  height: 100%;
  background: repeating-linear-gradient(90deg, var(--pink), var(--pink) 12px, var(--sun) 12px, var(--sun) 24px);
  border-radius: 999px; transition: width .4s ease; width: 0%;
}
.progress-msg { font-size: .9rem; color: var(--muted); margin-top: .6rem; text-align: center; }

/* 故事编辑区 */
.story-editor { margin-top: 1rem; }
.story-title-input {
  width: 100%; font-family: inherit; font-size: 1.2rem; font-weight: bold;
  padding: .6rem 1rem; border: 2.5px solid var(--text); border-radius: 16px;
  background: #fff; color: var(--pink-dark); margin-bottom: 1rem;
}
.story-title-input:focus { outline: none; border-color: var(--pink); box-shadow: 0 0 0 3px rgba(255,143,171,.25); }
.story-page-item {
  background: #fff; border: 2.5px solid var(--text); border-radius: 16px;
  padding: 1rem; margin-bottom: .8rem;
}
.story-page-num {
  display: inline-block; background: var(--sun); color: var(--text);
  font-size: .85rem; font-weight: bold; padding: .2rem .7rem;
  border-radius: 999px; margin-bottom: .5rem;
}
.story-page-item textarea {
  min-height: 55px; font-size: .9rem;
}
.story-page-item .scene-input { margin-top: .4rem; border-color: var(--blue); }
.story-page-item .scene-label { font-size: .8rem; color: var(--blue); margin-top: .4rem; display: block; }

/* 绘本查看器 */
.viewer { max-width: 720px; margin: 0 auto; }
.viewer-header { display: flex; align-items: center; gap: .6rem; margin-bottom: 1rem; flex-wrap: wrap; }
.back-btn {
  font-family: inherit; font-size: .92rem;
  border: 2.5px solid var(--text); border-radius: 999px;
  padding: .45rem 1rem; cursor: pointer;
  background: var(--card); color: var(--text);
  box-shadow: 0 3px 0 rgba(0,0,0,.1); transition: all .15s;
}
.back-btn:hover { transform: translateY(-1px); }
.viewer-title { flex: 1; font-size: 1.4rem; color: var(--pink-dark); text-align: center; min-width: 120px; }
.page-frame {
  background: var(--card); border-radius: var(--radius);
  box-shadow: var(--shadow); overflow: hidden;
  border: 4px solid var(--text);
}
.page-frame img { width: 100%; display: block; background: #fff8f0; min-height: 280px; object-fit: contain; }
.page-text { padding: 1.4rem 1.8rem 2rem; font-size: 1.15rem; line-height: 2; text-align: center; color: var(--text); }
.page-nav { display: flex; align-items: center; justify-content: center; gap: 1.2rem; margin-top: 1.2rem; }
.page-nav button {
  font-family: inherit; width: 50px; height: 50px; border-radius: 50%;
  border: 3px solid var(--text); background: var(--sun);
  font-size: 1.4rem; cursor: pointer;
  box-shadow: 0 4px 0 rgba(0,0,0,.12); transition: all .15s;
}
.page-nav button:hover:not(:disabled) { transform: translateY(-2px); background: var(--pink); color: #fff; }
.page-nav button:disabled { opacity: .35; cursor: not-allowed; }
.page-indicator { font-size: 1rem; color: var(--muted); min-width: 90px; text-align: center; }
.page-dots { display: flex; justify-content: center; gap: .5rem; margin-top: .8rem; }
.page-dots span {
  width: 12px; height: 12px; border-radius: 50%;
  background: #ddd; border: 2px solid var(--text);
  cursor: pointer; transition: all .2s;
}
.page-dots span.on { background: var(--pink); transform: scale(1.25); }

/* 历史列表 */
.history-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
}
.history-item {
  background: var(--card); border-radius: var(--radius);
  padding: 1.2rem; box-shadow: var(--shadow);
  border: 3px solid var(--text); transition: transform .2s;
}
.history-item:hover { transform: rotate(-1deg) scale(1.02); }
.history-item h3 { font-size: 1rem; color: var(--pink-dark); margin-bottom: .5rem; }
.history-item .meta { font-size: .82rem; color: var(--muted); line-height: 1.6; }
.history-item .actions { margin-top: .8rem; text-align: center; }

.btn-gen { background: #dff9fb; color: #2ed573; border-color: #2ed573; box-shadow: 0 4px 0 #2ed573; }
.btn-gen:hover { transform: translateY(-2px); }
.btn-gen:disabled { opacity: .5; cursor: not-allowed; }
.btn-view { background: var(--blue); color: #fff; border-color: #0984e3; box-shadow: 0 4px 0 #0984e3; }
.btn-view:hover { transform: translateY(-2px); }

/* 候选图选择 */
.candidate-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 1rem; margin: 1.2rem 0;
}
.candidate-card {
  border: 4px solid var(--text); border-radius: 20px;
  overflow: hidden; background: var(--card);
  cursor: pointer; transition: all .2s;
  box-shadow: 0 4px 0 rgba(0,0,0,.1);
  position: relative;
}
.candidate-card:hover {
  transform: translateY(-4px) rotate(-1deg);
  box-shadow: 0 8px 16px rgba(255,143,171,.3);
}
.candidate-card.selected {
  border-color: var(--pink-dark);
  box-shadow: 0 0 0 4px var(--sun), 0 8px 16px rgba(255,143,171,.4);
  transform: scale(1.04);
}
.candidate-card.selected::after {
  content: '\2714'; position: absolute; top: 8px; right: 10px;
  background: var(--pink); color: #fff; font-size: 1.2rem;
  width: 32px; height: 32px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 2px solid #fff;
}
.candidate-card img { width: 100%; display: block; min-height: 140px; object-fit: cover; background: #fff8f0; }
.candidate-label {
  text-align: center; padding: .4rem; font-size: .9rem; color: var(--muted);
  border-top: 2px dashed #eee;
}
.candidate-hint {
  text-align: center; color: var(--muted); font-size: .9rem; margin-bottom: .8rem;
}

.toast {
  position: fixed; bottom: 2rem; left: 50%;
  transform: translateX(-50%) translateY(80px);
  background: var(--text); color: #fff;
  padding: .75rem 1.6rem; border-radius: 999px;
  font-size: .95rem; opacity: 0; transition: all .3s;
  z-index: 999; pointer-events: none; border: 2px solid var(--sun);
}
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

@media (max-width: 600px) {
  header h1 { font-size: 2rem; }
  .form-card { padding: 1.3rem; }
  .style-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="deco">&#x2601;&#xFE0F;</div>
<div class="deco">&#x2B50;</div>
<div class="deco">&#x1F338;</div>
<div class="deco">&#x1F388;</div>

<header>
  <h1>绘本工坊</h1>
  <p>写下想法，一键画绘本 ~</p>
</header>

<nav class="tabs">
  <button class="active" data-tab="create">&#x1F3A8; 画新绘本</button>
  <button data-tab="shelf">&#x1F4DA; 我的书架</button>
</nav>

<main>
  <!-- 创建面板 -->
  <section id="panel-create" class="panel active">
    <div class="api-status" id="api-status"></div>
    <div class="form-card">
      <div class="form-group">
        <label>主角是谁呀？</label>
        <textarea id="input-character" placeholder="比如：一只白白胖胖的小兔子，戴着红色蝴蝶结"></textarea>
        <div class="hint">说得越详细，小主角就越可爱哦~</div>
      </div>
      <div class="form-group">
        <label>故事讲什么？</label>
        <textarea id="input-idea" placeholder="比如：小兔子在森林里迷路了，朋友们帮它找回家的路"></textarea>
      </div>
      <div class="form-group">
        <label>要画几页？</label>
        <input type="number" id="input-pages" value="4" min="3" max="8">
        <div class="hint">3 到 8 页之间</div>
      </div>
      <div class="form-group">
        <label>绘本风格</label>
        <div class="style-grid" id="style-grid"></div>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" id="btn-save-and-gen">&#x1F3A8; 保存并开始画绘本</button>
      </div>
    </div>

    <!-- 进度区（生成故事中） -->
    <div id="progress-area" style="display:none">
      <div class="form-card" style="border-color:var(--crayon)">
        <h3 style="text-align:center;color:var(--crayon);margin-bottom:.5rem">&#x1F4DD; 正在编写故事...</h3>
        <p style="text-align:center;color:var(--muted);font-size:.92rem;margin-bottom:1rem">DeepSeek 正在为你构思故事，请稍等~</p>
        <div class="progress-wrap">
          <div class="progress-bar"><div class="progress-fill" id="gen-progress-fill"></div></div>
          <div class="progress-msg" id="gen-progress-msg">准备中...</div>
        </div>
      </div>
    </div>

    <!-- 故事编辑区 -->
    <div id="story-area" style="display:none">
      <div class="form-card" style="border-color:var(--mint)">
        <h3 style="text-align:center;color:#2ed573;margin-bottom:.5rem">&#x1F4DC; 故事写好了！看看满意吗？</h3>
        <p style="text-align:center;color:var(--muted);font-size:.88rem;margin-bottom:.5rem">可以编辑标题、故事文字和场景描述，确认后开始画图</p>
        <div class="story-editor" id="story-editor"></div>
        <div class="btn-row" style="justify-content:center;margin-top:1.2rem">
          <button class="btn btn-primary" id="btn-confirm-story">&#x1F3A8; 满意，开始画图</button>
        </div>
      </div>
    </div>

    <!-- 候选图进度区 -->
    <div id="candidate-progress-area" style="display:none">
      <div class="form-card" style="border-color:var(--crayon)">
        <h3 style="text-align:center;color:var(--crayon);margin-bottom:.5rem">&#x1F58D;&#xFE0F; 正在画首页候选...</h3>
        <p style="text-align:center;color:var(--muted);font-size:.92rem;margin-bottom:1rem">生成3张不同的首页，每张大概半分钟~</p>
        <div class="progress-wrap">
          <div class="progress-bar"><div class="progress-fill" id="cand-progress-fill"></div></div>
          <div class="progress-msg" id="cand-progress-msg">准备中...</div>
        </div>
      </div>
    </div>

    <!-- 候选图选择区 -->
    <div id="candidate-area" style="display:none">
      <div class="form-card" style="border-color:var(--pink-dark)">
        <h3 style="text-align:center;color:var(--pink-dark);margin-bottom:.5rem">&#x1F3AF; 选一个你喜欢的首页吧！</h3>
        <p class="candidate-hint">点击选择一张作为绘本的首页风格，后续页面会保持一致</p>
        <div class="candidate-grid" id="candidate-grid"></div>
        <div class="btn-row" style="justify-content:center;margin-top:1.2rem">
          <button class="btn btn-primary" id="btn-confirm-candidate" disabled>&#x1F3A8; 用这个风格继续画绘本</button>
        </div>
      </div>
    </div>

    <!-- 续生进度区 -->
    <div id="continue-progress-area" style="display:none">
      <div class="form-card" style="border-color:var(--blue)">
        <h3 style="text-align:center;color:var(--blue);margin-bottom:.5rem">&#x1F58D;&#xFE0F; 正在画后续页面...</h3>
        <p style="text-align:center;color:var(--muted);font-size:.92rem;margin-bottom:1rem">根据你选的首页风格继续画，每页大概半分钟~</p>
        <div class="progress-wrap">
          <div class="progress-bar"><div class="progress-fill" id="continue-progress-fill"></div></div>
          <div class="progress-msg" id="continue-progress-msg">准备中...</div>
        </div>
        <div class="btn-row" id="continue-done-actions" style="display:none;justify-content:center">
          <button class="btn btn-view" id="btn-view-result">&#x1F4D6; 去看绘本</button>
          <button class="btn btn-secondary" id="btn-new-after-gen">&#x1F4DD; 再画一本</button>
        </div>
      </div>
    </div>
  </section>

  <!-- 书架面板 -->
  <section id="panel-shelf" class="panel">
    <div id="history-list" class="history-grid"></div>
    <div id="empty-history" style="display:none;text-align:center;padding:3rem;background:var(--card);border-radius:var(--radius);border:3px dashed var(--crayon)">
      <p style="font-size:3rem">&#x1F9F8;</p>
      <p style="color:var(--muted)">还没有绘本哦，快去画第一本吧！</p>
    </div>
  </section>

  <!-- 绘本查看器 -->
  <section id="panel-viewer" class="panel">
    <div class="viewer">
      <div class="viewer-header">
        <button class="back-btn" id="viewer-back">&#x1F3E0; 回书架</button>
        <div class="viewer-title" id="viewer-title"></div>
      </div>
      <div class="page-frame">
        <img id="viewer-img" src="" alt="绘本插图">
        <div class="page-text" id="viewer-text"></div>
      </div>
      <div class="page-nav">
        <button id="v-prev">&#x25C0;</button>
        <span class="page-indicator" id="v-indicator">1 / 1</span>
        <button id="v-next">&#x25B6;</button>
      </div>
      <div class="page-dots" id="v-dots"></div>
    </div>
  </section>
</main>

<div class="toast" id="toast"></div>

<script>
var state = {
  selectedStyle: '1',
  styles: [],
  savedBookId: null,
  jobId: null,
  currentBook: null,
  currentPage: 0,
  chosenCandidate: null,
};

function toast(msg) {
  var el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(function() { el.classList.remove('show'); }, 2800);
}

function esc(s) {
  var d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function showPanel(name) {
  document.querySelectorAll('.panel').forEach(function(p) { p.classList.remove('active'); });
  document.getElementById('panel-' + name).classList.add('active');
  document.querySelectorAll('nav.tabs button').forEach(function(b) { b.classList.remove('active'); });
  var btn = document.querySelector('nav.tabs button[data-tab="' + name + '"]');
  if (btn) btn.classList.add('active');
  if (name === 'shelf') loadHistory();
}

function hideAllCreateAreas() {
  var formCard = document.querySelector('#panel-create > .form-card');
  if (formCard) formCard.style.display = 'none';
  document.getElementById('progress-area').style.display = 'none';
  document.getElementById('story-area').style.display = 'none';
  document.getElementById('candidate-progress-area').style.display = 'none';
  document.getElementById('candidate-area').style.display = 'none';
  document.getElementById('continue-progress-area').style.display = 'none';
}

function showCreateForm() {
  hideAllCreateAreas();
  var formCard = document.querySelector('#panel-create > .form-card');
  if (formCard) formCard.style.display = 'block';
}

function showCreateArea(areaId) {
  hideAllCreateAreas();
  document.getElementById(areaId).style.display = 'block';
}

// ---- Tab 切换 ----
document.querySelectorAll('nav.tabs button').forEach(function(btn) {
  btn.addEventListener('click', function() { showPanel(btn.dataset.tab); });
});

// ---- 加载配置 ----
async function loadConfig() {
  var res = await fetch('/api/config');
  var data = await res.json();
  state.styles = data.styles;
  var grid = document.getElementById('style-grid');
  grid.innerHTML = state.styles.map(function(s) {
    return '<div class="style-option ' + (s.id === '1' ? 'selected' : '') + '" data-id="' + s.id + '">' + s.name + '</div>';
  }).join('');
  grid.querySelectorAll('.style-option').forEach(function(el) {
    el.addEventListener('click', function() {
      grid.querySelectorAll('.style-option').forEach(function(o) { o.classList.remove('selected'); });
      el.classList.add('selected');
      state.selectedStyle = el.dataset.id;
    });
  });
  // API 状态徽章
  var statusEl = document.getElementById('api-status');
  statusEl.innerHTML =
    '<span class="badge ' + (data.has_deepseek ? 'ok' : 'err') + '">DeepSeek ' + (data.has_deepseek ? '已配置' : '未配置') + '</span>' +
    '<span class="badge ' + (data.has_qwen ? 'ok' : 'err') + '">千问 ' + (data.has_qwen ? '已配置' : '未配置') + '</span>';
}

// ---- 保存 + 生成故事 ----
document.getElementById('btn-save-and-gen').addEventListener('click', async function() {
  var character = document.getElementById('input-character').value.trim();
  var idea = document.getElementById('input-idea').value.trim();
  var num_pages = parseInt(document.getElementById('input-pages').value) || 4;

  if (!character) { toast('请填写主角描述'); return; }
  if (!idea) { toast('请填写故事想法'); return; }
  if (num_pages < 3 || num_pages > 8) { toast('页数需在 3-8 之间'); return; }

  var btn = document.getElementById('btn-save-and-gen');
  btn.disabled = true;
  btn.textContent = '保存中...';

  try {
    var saveRes = await fetch('/api/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ character: character, idea: idea, num_pages: num_pages, style: state.selectedStyle }),
    });
    var saveData = await saveRes.json();
    if (!saveRes.ok) { toast(saveData.error || '保存失败'); btn.disabled = false; btn.textContent = '\uD83C\uDFA8 保存并开始画绘本'; return; }

    state.savedBookId = saveData.book_id;
    toast('保存成功！正在编写故事...');

    document.getElementById('input-character').value = '';
    document.getElementById('input-idea').value = '';
    document.getElementById('input-pages').value = '4';

    // 启动故事生成
    showCreateArea('progress-area');
    document.getElementById('gen-progress-fill').style.width = '0%';
    document.getElementById('gen-progress-msg').textContent = '提交任务...';

    var genRes = await fetch('/api/generate/' + state.savedBookId, { method: 'POST' });
    var genData = await genRes.json();
    if (!genRes.ok) {
      toast(genData.error || '启动生成失败');
      showCreateForm();
      return;
    }

    state.jobId = genData.job_id;
    pollStoryJob();
  } catch (e) {
    toast('网络出错啦');
    showCreateForm();
  } finally {
    btn.disabled = false;
    btn.textContent = '\uD83C\uDFA8 保存并开始画绘本';
  }
});

function pollStoryJob() {
  var timer = setInterval(async function() {
    var res = await fetch('/api/jobs/' + state.jobId);
    var job = await res.json();
    document.getElementById('gen-progress-fill').style.width = job.progress + '%';
    document.getElementById('gen-progress-msg').textContent = job.message || '';

    if (job.status === 'story_ready') {
      clearInterval(timer);
      toast('故事已生成，请查看编辑！');
      loadStoryEditor(job.book_id);
    } else if (job.status === 'error') {
      clearInterval(timer);
      toast(job.message || '故事生成失败');
    }
  }, 2000);
}

async function loadStoryEditor(bookId) {
  var res = await fetch('/api/story/' + bookId);
  if (!res.ok) { toast('加载故事失败'); return; }
  var story = await res.json();

  var editor = document.getElementById('story-editor');
  var html = '<input type="text" class="story-title-input" id="story-title" value="' + esc(story.title || '') + '" placeholder="故事标题">';
  for (var i = 0; i < story.pages.length; i++) {
    var p = story.pages[i];
    html += '<div class="story-page-item">' +
      '<span class="story-page-num">\u7B2C ' + (i + 1) + ' \u9875</span>' +
      '<textarea id="story-text-' + i + '" placeholder="\u6545\u4E8B\u6587\u5B57">' + esc(p.text || '') + '</textarea>' +
      '<span class="scene-label">\u573A\u666F\u63CF\u8FF0\uFF08\u7528\u4E8E\u751F\u56FE\u7684\u63D0\u793A\u8BCD\uFF09</span>' +
      '<textarea class="scene-input" id="story-scene-' + i + '" placeholder="\u573A\u666F\u63CF\u8FF0">' + esc(p.scene || '') + '</textarea>' +
      '</div>';
  }
  editor.innerHTML = html;
  showCreateArea('story-area');
}

// 确认故事 -> 开始生成候选图
document.getElementById('btn-confirm-story').addEventListener('click', async function() {
  if (!state.savedBookId) return;
  var btn = document.getElementById('btn-confirm-story');
  btn.disabled = true;
  btn.textContent = '保存中...';

  try {
    // 收集编辑后的故事数据
    var titleEl = document.getElementById('story-title');
    var pages = [];
    var i = 0;
    while (document.getElementById('story-text-' + i)) {
      pages.push({
        text: document.getElementById('story-text-' + i).value.trim(),
        scene: document.getElementById('story-scene-' + i).value.trim(),
      });
      i++;
    }
    var storyData = { title: titleEl.value.trim(), pages: pages };

    // 保存编辑后的故事
    var updateRes = await fetch('/api/story/' + state.savedBookId, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(storyData),
    });
    if (!updateRes.ok) { toast('保存故事失败'); btn.disabled = false; btn.textContent = '\uD83C\uDFA8 满意，开始画图'; return; }

    // 启动候选图生成
    showCreateArea('candidate-progress-area');
    document.getElementById('cand-progress-fill').style.width = '30%';
    document.getElementById('cand-progress-msg').textContent = '正在生成3张首页候选...';

    var candRes = await fetch('/api/generate-candidates/' + state.savedBookId, { method: 'POST' });
    var candData = await candRes.json();
    if (!candRes.ok) { toast(candData.error || '启动失败'); showCreateArea('story-area'); btn.disabled = false; btn.textContent = '\uD83C\uDFA8 满意，开始画图'; return; }

    state.jobId = candData.job_id;
    pollCandidateJob();
  } catch (e) {
    toast('网络出错啦');
    showCreateArea('story-area');
    btn.disabled = false;
    btn.textContent = '\uD83C\uDFA8 满意，开始画图';
  }
});

async function showCandidates(bookId) {
  var res = await fetch('/api/candidates/' + bookId);
  if (!res.ok) { toast('加载候选图失败'); return; }
  var data = await res.json();
  var candidates = data.candidates;
  if (!candidates.length) { toast('没有候选图'); return; }

  state.chosenCandidate = null;
  var grid = document.getElementById('candidate-grid');
  var moodNames = ['\u660E\u4EAE\u6E29\u6696', '\u67D4\u548C\u68A6\u5E7B', '\u6D53\u70C8\u9C9C\u8273'];
  grid.innerHTML = candidates.map(function(c) {
    var moodLabel = moodNames[c.index - 1] || ('\u98CE\u683C ' + c.index);
    return '<div class="candidate-card" data-index="' + c.index + '">' +
      '<img src="' + c.url + '?t=' + Date.now() + '" alt="\u5019\u9009 ' + c.index + '">' +
      '<div class="candidate-label">' + moodLabel + '</div>' +
      '</div>';
  }).join('');

  grid.querySelectorAll('.candidate-card').forEach(function(card) {
    card.addEventListener('click', function() {
      grid.querySelectorAll('.candidate-card').forEach(function(c) { c.classList.remove('selected'); });
      card.classList.add('selected');
      state.chosenCandidate = parseInt(card.dataset.index);
      document.getElementById('btn-confirm-candidate').disabled = false;
    });
  });

  document.getElementById('btn-confirm-candidate').disabled = true;
  showCreateArea('candidate-area');
}

function pollCandidateJob() {
  var timer = setInterval(async function() {
    var res = await fetch('/api/jobs/' + state.jobId);
    var job = await res.json();
    document.getElementById('cand-progress-fill').style.width = job.progress + '%';
    document.getElementById('cand-progress-msg').textContent = job.message || '';

    if (job.status === 'candidates_ready') {
      clearInterval(timer);
      toast('3张首页候选已生成，请选择！');
      showCandidates(job.book_id);
    } else if (job.status === 'error') {
      clearInterval(timer);
      toast(job.message || '候选图生成失败');
    }
  }, 2000);
}

// 确认选择候选
document.getElementById('btn-confirm-candidate').addEventListener('click', async function() {
  if (!state.chosenCandidate || !state.savedBookId) return;
  var btn = document.getElementById('btn-confirm-candidate');
  btn.disabled = true;
  btn.textContent = '正在提交...';

  try {
    var res = await fetch('/api/select-candidate/' + state.savedBookId + '/' + state.chosenCandidate, { method: 'POST' });
    var data = await res.json();
    if (!res.ok) { toast(data.error || '选择失败'); btn.disabled = false; btn.textContent = '\uD83C\uDFA8 用这个风格继续画绘本'; return; }

    state.jobId = data.job_id;
    showCreateArea('continue-progress-area');
    document.getElementById('continue-progress-fill').style.width = '50%';
    document.getElementById('continue-progress-msg').textContent = '正在生成后续页面...';
    document.getElementById('continue-done-actions').style.display = 'none';
    pollContinueJob();
  } catch (e) {
    toast('网络出错啦');
    btn.disabled = false;
    btn.textContent = '\uD83C\uDFA8 用这个风格继续画绘本';
  }
});

function pollContinueJob() {
  var timer = setInterval(async function() {
    var res = await fetch('/api/jobs/' + state.jobId);
    var job = await res.json();
    document.getElementById('continue-progress-fill').style.width = job.progress + '%';
    document.getElementById('continue-progress-msg').textContent = job.message || '';

    if (job.status === 'done') {
      clearInterval(timer);
      document.getElementById('continue-done-actions').style.display = 'flex';
      toast('绘本生成完成！');
    } else if (job.status === 'error') {
      clearInterval(timer);
      document.getElementById('continue-done-actions').style.display = 'flex';
      toast(job.message || '生成失败');
    }
  }, 2000);
}

document.getElementById('btn-view-result').addEventListener('click', function() {
  if (state.savedBookId) openViewer(state.savedBookId);
});

document.getElementById('btn-new-after-gen').addEventListener('click', function() {
  showCreateForm();
})

// ---- 绘本查看器 ----
async function openViewer(bookId) {
  var res = await fetch('/api/books/' + bookId + '/detail');
  if (!res.ok) { toast('加载失败'); return; }
  state.currentBook = await res.json();
  state.currentPage = 0;
  showPanel('viewer');
  document.getElementById('viewer-title').textContent = state.currentBook.title || bookId;
  renderViewerPage();
}

function renderViewerPage() {
  var book = state.currentBook;
  if (!book || !book.pages || !book.pages.length) return;
  var p = book.pages[state.currentPage];
  var img = document.getElementById('viewer-img');
  var url = p.layout_url || '';
  img.src = url ? url + '?t=' + Date.now() : '';
  img.alt = '第 ' + p.page + ' 页';
  document.getElementById('viewer-text').textContent = p.text || '';
  document.getElementById('v-indicator').textContent = (state.currentPage + 1) + ' / ' + book.pages.length;
  document.getElementById('v-prev').disabled = state.currentPage === 0;
  document.getElementById('v-next').disabled = state.currentPage >= book.pages.length - 1;
  var dots = document.getElementById('v-dots');
  dots.innerHTML = book.pages.map(function(_, i) {
    return '<span class="' + (i === state.currentPage ? 'on' : '') + '" data-idx="' + i + '"></span>';
  }).join('');
  dots.querySelectorAll('span').forEach(function(dot) {
    dot.addEventListener('click', function() {
      state.currentPage = parseInt(dot.dataset.idx);
      renderViewerPage();
    });
  });
}

document.getElementById('viewer-back').addEventListener('click', function() { showPanel('shelf'); });
document.getElementById('v-prev').addEventListener('click', function() {
  if (state.currentPage > 0) { state.currentPage--; renderViewerPage(); }
});
document.getElementById('v-next').addEventListener('click', function() {
  if (state.currentBook && state.currentPage < state.currentBook.pages.length - 1) {
    state.currentPage++; renderViewerPage();
  }
});
document.addEventListener('keydown', function(e) {
  if (!document.getElementById('panel-viewer').classList.contains('active')) return;
  if (e.key === 'ArrowLeft') document.getElementById('v-prev').click();
  if (e.key === 'ArrowRight') document.getElementById('v-next').click();
});

// ---- 历史列表 ----
async function loadHistory() {
  var res = await fetch('/api/books');
  var books = await res.json();
  var list = document.getElementById('history-list');
  var empty = document.getElementById('empty-history');

  if (!books.length) {
    list.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  list.innerHTML = books.map(function(b) {
    var actions = '';
    if (b.has_images) {
      actions = '<div class="actions"><button class="btn btn-view" data-action="view" data-id="' + b.id + '">&#x1F4D6; 看绘本</button></div>';
    } else if (b.has_candidates) {
      actions = '<div class="actions"><button class="btn btn-view" data-action="select" data-id="' + b.id + '">&#x1F3AF; 选首页</button></div>';
    } else if (b.has_story) {
      actions = '<div class="actions"><button class="btn btn-gen" data-action="edit-story" data-id="' + b.id + '">&#x1F4DC; 编辑故事</button></div>';
    } else {
      actions = '<div class="actions"><button class="btn btn-gen" data-action="gen" data-id="' + b.id + '">&#x1F3A8; 画绘本</button></div>';
    }
    return '<div class="history-item">' +
      '<h3>' + esc(b.title || b.id) + '</h3>' +
      '<div class="meta">' +
      '&#x1F43E; ' + esc(b.character) + '<br>' +
      '&#x1F4AC; ' + esc(b.idea) + '<br>' +
      '&#x1F4D0; ' + b.num_pages + ' 页 &middot; ' + esc(b.style_name) + '<br>' +
      '&#x1F552; ' + b.created_at +
      '</div>' +
      actions +
      '</div>';
  }).join('');

  // 绑定按钮事件
  list.querySelectorAll('[data-action=view]').forEach(function(btn) {
    btn.addEventListener('click', function() { openViewer(btn.dataset.id); });
  });
  list.querySelectorAll('[data-action=select]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      state.savedBookId = btn.dataset.id;
      showPanel('create');
      showCandidates(btn.dataset.id);
    });
  });
  list.querySelectorAll('[data-action=edit-story]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      state.savedBookId = btn.dataset.id;
      showPanel('create');
      loadStoryEditor(btn.dataset.id);
    });
  });
  list.querySelectorAll('[data-action=gen]').forEach(function(btn) {
    btn.addEventListener('click', async function() {
      var bookId = btn.dataset.id;
      btn.disabled = true;
      btn.textContent = '生成中...';
      try {
        var res = await fetch('/api/generate/' + bookId, { method: 'POST' });
        var data = await res.json();
        if (!res.ok) { toast(data.error || '启动失败'); btn.disabled = false; btn.textContent = '\uD83C\uDFA8 画绘本'; return; }
        state.savedBookId = bookId;
        state.jobId = data.job_id;
        showPanel('create');
        showCreateArea('progress-area');
        document.getElementById('gen-progress-fill').style.width = '0%';
        document.getElementById('gen-progress-msg').textContent = '提交任务...';
        pollStoryJob();
      } catch (e) {
        toast('网络出错啦');
        btn.disabled = false;
        btn.textContent = '\uD83C\uDFA8 画绘本';
      }
    });
  });
}

// ---- 初始化 ----
loadConfig();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=" * 50)
    print("  绘本工坊 Web 服务")
    print("  收集输入 + 生成绘本 + 查看展示")
    print("  访问: http://127.0.0.1:5001")
    print("=" * 50)
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)

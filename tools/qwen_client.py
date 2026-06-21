# -*- coding: utf-8 -*-
"""
千问 Image API 客户端工具
封装 DashScope 图像生成的三种调用方式：
  - generate_image_with_qwen  : 异步任务模式 (wanx2.1 系列)
  - generate_image_sync       : 同步文生图 (wan2.6 / wan2.5 系列)
  - generate_image_with_reference : 参考图模式，用于角色一致性
"""

import os
import sys
import io
import base64
import json
import time
import requests

from PIL import Image

# 确保项目根目录在 sys.path 中
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from config import load_config


# ==================== 工具函数 ====================

def _is_wan26_model(model: str) -> bool:
    """判断是否为 wan2.6 / wan2.5 同步 API 模型"""
    return any(m in model for m in ["wan2.6", "wan2.5"])


def _pil_to_base64(img: Image.Image) -> str:
    """将 PIL Image 转为 Base64 字符串 (JPEG)"""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def get_api_key() -> str:
    """
    获取 DashScope API Key。
    优先级: config.yaml > 环境变量 DASHSCOPE_API_KEY > 运行时输入
    """
    cfg = load_config()
    key = cfg["qwen"].get("api_key", "").strip()
    if key:
        return key
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if key:
        return key
    print()
    print("=" * 50)
    print("  千问 Image API Key 未配置")
    print("=" * 50)
    print("请在 config/config.yaml 的 qwen.api_key 填入 Key，")
    print("或设置环境变量: set DASHSCOPE_API_KEY=sk-xxxxxx")
    print("获取 API Key: https://dashscope.console.aliyun.com/apiKey")
    print()
    key = input("临时输入 API Key (直接回车可跳过): ").strip()
    return key


# ==================== 图像生成 ====================

def generate_image_with_qwen(prompt, api_key, model=None, size=None, seed=None):
    """
    异步任务模式文生图，适用于 wanx2.1 / wanx-v1 系列。
    返回: (PIL.Image | None, info_str)
    """
    if not api_key:
        print("  [X] 未提供 API Key")
        return None, ""

    cfg = load_config()
    model = model or cfg["qwen"]["default_model"]
    size = size or cfg["qwen"]["default_image_size"]
    base_url = cfg["qwen"]["base_url"]
    no_proxy = {"http": None, "https": None}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    params = {"size": size, "n": 1}
    if seed is not None:
        params["seed"] = seed

    payload = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": params,
    }

    try:
        resp = requests.post(
            f"{base_url}/services/aigc/text2image/image-synthesis",
            headers=headers, json=payload, timeout=60, proxies=no_proxy,
        )
        resp.raise_for_status()
        result = resp.json()

        # 部分模型支持同步直接返回
        if result.get("output", {}).get("task_status") == "SUCCEEDED":
            image_url = result["output"]["results"][0]["url"]
            img_resp = requests.get(image_url, timeout=30, proxies=no_proxy)
            img = Image.open(io.BytesIO(img_resp.content))
            return img, json.dumps(result.get("output", {}), ensure_ascii=False)

        task_id = result.get("output", {}).get("task_id")
        if not task_id:
            print(f"  [X] 任务提交失败: {result}")
            return None, ""

        # 轮询等待
        max_wait, elapsed, poll_interval = 180, 0, 3
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            status_resp = requests.get(
                f"{base_url}/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30, proxies=no_proxy,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()
            task_status = status_data.get("output", {}).get("task_status", "")

            if task_status == "SUCCEEDED":
                results = status_data["output"].get("results", [])
                if results:
                    img_resp = requests.get(results[0]["url"], timeout=60, proxies=no_proxy)
                    img = Image.open(io.BytesIO(img_resp.content))
                    return img, json.dumps(status_data.get("output", {}), ensure_ascii=False)
                print("  [X] 任务成功但无图片结果")
                return None, ""
            elif task_status == "FAILED":
                print(f"  [X] 图片生成失败: {status_data.get('output', {}).get('message', '未知错误')}")
                return None, ""
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
    同步文生图，适用于 wan2.6-t2i / wan2.5-t2i 系列。
    返回: (PIL.Image | None, info_str)
    """
    if not api_key:
        print("  [X] 未提供 API Key")
        return None, ""

    cfg = load_config()
    model = model or cfg["qwen"]["default_model"]
    size = size or cfg["qwen"]["default_image_size"]
    base_url = cfg["qwen"]["base_url"]
    no_proxy = {"http": None, "https": None}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    params = {"size": size, "n": 1, "prompt_extend": True, "watermark": False}
    if seed is not None:
        params["seed"] = seed

    payload = {
        "model": model,
        "input": {
            "messages": [{"role": "user", "content": [{"text": prompt}]}]
        },
        "parameters": params,
    }

    try:
        resp = requests.post(
            f"{base_url}/services/aigc/multimodal-generation/generation",
            headers=headers, json=payload, timeout=120, proxies=no_proxy,
        )
        resp.raise_for_status()
        result = resp.json()

        if "code" in result:
            print(f"  [X] API 错误: {result.get('message', result.get('code'))}")
            return None, ""

        choices = result.get("output", {}).get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", [])
            for item in content:
                if item.get("type") == "image":
                    img_resp = requests.get(item["image"], timeout=60, proxies=no_proxy)
                    img = Image.open(io.BytesIO(img_resp.content))
                    return img, json.dumps(result.get("output", {}), ensure_ascii=False)

        print(f"  [X] 未返回图片: {json.dumps(result, ensure_ascii=False)[:300]}")
        return None, ""

    except requests.exceptions.ConnectionError:
        print("  [X] 无法连接到 DashScope API，请检查网络")
        return None, ""
    except Exception as e:
        print(f"  [X] 同步生图异常: {e}")
        return None, ""


def generate_image_with_reference(prompt, ref_image, api_key, model=None, size=None,
                                   seed=None, negative_prompt=""):
    """
    参考图模式文生图 (wan2.6-image)，用于保持角色一致性并更换场景。
    返回: (PIL.Image | None, info_str)
    """
    if not api_key:
        print("  [X] 未提供 API Key")
        return None, ""

    cfg = load_config()
    model = model or cfg["qwen"]["ref_model"]
    size = size or cfg["qwen"]["default_image_size"]
    base_url = cfg["qwen"]["base_url"]
    no_proxy = {"http": None, "https": None}

    ref_b64 = _pil_to_base64(ref_image)
    ref_data_uri = f"data:image/jpeg;base64,{ref_b64}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    params = {
        "size": size, "n": 1,
        "prompt_extend": False,
        "watermark": False,
        "enable_interleave": False,
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
                    {"image": ref_data_uri},
                ],
            }]
        },
        "parameters": params,
    }

    try:
        print("  [REF] 使用参考图模式 (角色一致性)")
        resp = requests.post(
            f"{base_url}/services/aigc/multimodal-generation/generation",
            headers=headers, json=payload, timeout=180, proxies=no_proxy,
        )
        resp.raise_for_status()
        result = resp.json()

        if "code" in result:
            print(f"  [X] API 错误: {result.get('message', result.get('code'))}")
            return None, ""

        choices = result.get("output", {}).get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", [])
            for item in content:
                if item.get("type") == "image":
                    img_resp = requests.get(item["image"], timeout=60, proxies=no_proxy)
                    img = Image.open(io.BytesIO(img_resp.content))
                    return img, json.dumps(result.get("output", {}), ensure_ascii=False)

        print(f"  [X] 未返回图片: {json.dumps(result, ensure_ascii=False)[:300]}")
        return None, ""

    except requests.exceptions.ConnectionError:
        print("  [X] 无法连接到 DashScope API，请检查网络")
        return None, ""
    except Exception as e:
        print(f"  [X] 参考图生图异常: {e}")
        return None, ""

# -*- coding: utf-8 -*-
import requests
import base64
from PIL import Image
import io
import os
from datetime import datetime

# WebUI 的 API 地址
URL = "http://127.0.0.1:7860/sdapi/v1/txt2img"

# 生成参数
payload = {
    "prompt": "a beautiful sunset over mountains, highly detailed, masterpiece, 8k",
    "negative_prompt": "blurry, low quality, distorted, ugly, deformed",
    "width": 512,
    "height": 512,
    "steps": 25,
    "cfg_scale": 7,
    "sampler_index": "DPM++ 2M Karras",
    "seed": -1,           # -1 表示随机种子
    "batch_size": 1,
    "n_iter": 1,          # 生成批次
    "save_images": False, # 设为 True 可让 WebUI 自动保存到 outputs 目录
    "send_images": True   # 必须 True，否则不返回图片数据
}

print("正在生成图片...")

try:
    response = requests.post(URL, json=payload, timeout=120)
    response.raise_for_status()
    result = response.json()

    # 创建输出目录
    output_dir = "api_outputs"
    os.makedirs(output_dir, exist_ok=True)

    # 保存返回的图片
    for i, img_base64 in enumerate(result.get("images", [])):
        img_bytes = base64.b64decode(img_base64)
        img = Image.open(io.BytesIO(img_bytes))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/generated_{timestamp}_{i}.png"
        img.save(filename)
        print(f"? 图片已保存: {filename}")

    # 打印生成信息
    print(f"\n生成参数信息:\n{result.get('info', '')}")

except requests.exceptions.ConnectionError:
    print("? 连接失败，请确认 WebUI 已启动并且带 --api 参数")
except Exception as e:
    print(f"? 发生错误: {e}")
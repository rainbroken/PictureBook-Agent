# -*- coding: utf-8 -*-
"""
config 包 — 统一配置加载入口
使用方式:
    from config import load_config
    cfg = load_config()
    api_key = cfg["qwen"]["api_key"]
"""

import os
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
_cache = None


def load_config(reload: bool = False) -> dict:
    """
    加载并返回 config.yaml 配置字典。
    结果会缓存，避免重复读取文件；传入 reload=True 可强制重新加载。
    """
    global _cache
    if _cache is None or reload:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _cache = yaml.safe_load(f)
    return _cache

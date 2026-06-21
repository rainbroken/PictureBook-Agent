#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
儿童绘本 Agent 伦理合规与安全防护模块

功能覆盖：
1. 儿童友好内容检测：暴力、血腥、色情、自伤、仇恨歧视、违法危险内容。
2. Prompt 注入 / 越狱检测：忽略规则、泄露系统提示词、DAN、角色扮演绕过等。
3. 隐私保护：手机号、邮箱、身份证号等个人信息脱敏。
4. 审计日志：记录每次安全检查结果，便于路演展示“安全防护与日志”。

本模块只依赖 Python 标准库，可直接放在 collect_input_web.py 同目录下使用。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class SafetyResult:
    """一次安全检查的结构化结果。"""

    allowed: bool
    message: str = "通过安全检查"
    risk_level: str = "low"  # low / medium / high
    categories: List[str] = field(default_factory=list)
    hits: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sanitized_text: str = ""
    sanitized_fields: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "allowed": self.allowed,
            "message": self.message,
            "risk_level": self.risk_level,
            "categories": self.categories,
            "hits": self.hits,
            "warnings": self.warnings,
            "sanitized_text": self.sanitized_text,
            "sanitized_fields": self.sanitized_fields,
        }


# ==================== 检测规则 ====================

PROMPT_INJECTION_PATTERNS: List[Tuple[str, str]] = [
    (r"忽略.{0,12}(以上|之前|前面).{0,8}(规则|指令|要求|提示)", "提示注入：要求忽略已有规则"),
    (r"无视.{0,12}(以上|之前|前面).{0,8}(规则|指令|要求|提示)", "提示注入：要求无视已有规则"),
    (r"(输出|打印|泄露|告诉我).{0,10}(系统提示词|system prompt|开发者消息|developer message|隐藏指令)", "提示注入：试图泄露系统提示词"),
    (r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions", "Prompt injection: ignore previous instructions"),
    (r"reveal\s+(your\s+)?(system\s+prompt|developer\s+message|hidden\s+instructions)", "Prompt injection: reveal hidden prompt"),
    (r"dan\s*mode|do\s+anything\s+now|jailbreak|越狱", "越狱攻击：DAN/Jailbreak"),
    (r"角色扮演.{0,20}(绕过|不受限制|无限制|没有限制)", "越狱攻击：角色扮演绕过"),
    (r"你现在不是.{0,20}(儿童绘本|安全|受限|AI)", "上下文混淆：改变系统角色"),
    (r"base64|unicode|rot13|十六进制|hex|编码后执行", "编码注入：试图用编码绕过检测"),
]

UNSAFE_CONTENT_PATTERNS: Dict[str, List[Tuple[str, str]]] = {
    "sexual_content": [
        (r"色情|裸露|成人内容|性行为|猥亵|性暗示|nsfw|porn|sexual", "儿童不适内容：色情/裸露"),
    ],
    "graphic_violence": [
        (r"血腥|肢解|砍头|尸体|内脏|虐杀|gore|dismember", "儿童不适内容：血腥暴力"),
        (r"杀死|杀掉|谋杀|屠杀|自杀|自残", "儿童不适内容：严重伤害"),
    ],
    "weapons_or_crime": [
        (r"炸弹|爆炸物|毒药|制毒|枪击|抢劫|绑架|bomb|poison|kidnap", "违法危险内容：武器/犯罪"),
    ],
    "hate_or_discrimination": [
        (r"仇恨|种族歧视|性别歧视|辱骂.{0,8}(群体|民族|国家)|hate speech|racist", "仇恨/歧视内容"),
    ],
    "horror_for_children": [
        (r"恐怖血腥|惊悚恐怖|恶心怪物|吓哭小孩|nightmare horror", "不适合儿童绘本的恐怖内容"),
    ],
}

# 单独列出“轻微风险词”，不直接拦截，而是作为 warning。
CAUTION_PATTERNS: List[Tuple[str, str]] = [
    (r"害怕|迷路|黑夜|怪物", "包含轻微紧张元素，建议处理成温和、积极、儿童友好表达"),
    (r"真实姓名|家庭住址|学校名称|班级|电话|身份证", "可能包含个人隐私，系统会尝试脱敏"),
]

PII_PATTERNS: List[Tuple[str, str, str]] = [
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[邮箱已脱敏]"),
    ("phone", r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", "[手机号已脱敏]"),
    ("id_card", r"(?<!\d)\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)", "[身份证号已脱敏]"),
    ("qq", r"(?<!\d)QQ[:：]?\s*\d{5,12}(?!\d)", "[QQ号已脱敏]"),
]


# ==================== 核心函数 ====================


def _normalize(text: str) -> str:
    text = text or ""
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def mask_pii(text: str) -> Tuple[str, List[str]]:
    """脱敏个人信息，返回脱敏文本和命中的隐私类型。"""
    masked = text or ""
    found: List[str] = []
    for name, pattern, replacement in PII_PATTERNS:
        if re.search(pattern, masked, flags=re.IGNORECASE):
            found.append(name)
            masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)
    return masked, found


def sanitize_for_prompt(text: str) -> str:
    """轻量清洗，减少特殊分隔符、代码块和控制字符对后续 LLM 的影响。"""
    text = _normalize(text)
    text = text.replace("```", "'''")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text[:800]


def evaluate_text(text: str, field_name: str = "text") -> SafetyResult:
    """对单段文本进行安全评估。"""
    original = _normalize(text)
    sanitized = sanitize_for_prompt(original)
    sanitized, pii_hits = mask_pii(sanitized)

    categories: List[str] = []
    hits: List[str] = []
    warnings: List[str] = []

    # 1. Prompt 注入 / 越狱
    for pattern, desc in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, original, flags=re.IGNORECASE):
            categories.append("prompt_injection")
            hits.append(desc)

    # 2. 儿童不适 / 违法 / 歧视内容
    for category, rules in UNSAFE_CONTENT_PATTERNS.items():
        for pattern, desc in rules:
            if re.search(pattern, original, flags=re.IGNORECASE):
                categories.append(category)
                hits.append(desc)

    # 3. 隐私信息：脱敏后可继续，但给 warning
    if pii_hits:
        categories.append("privacy")
        warnings.append("检测到个人信息，已在保存前自动脱敏：" + "、".join(sorted(set(pii_hits))))

    # 4. 轻微风险提示
    for pattern, desc in CAUTION_PATTERNS:
        if re.search(pattern, original, flags=re.IGNORECASE):
            warnings.append(desc)

    # 去重但保持顺序
    categories = list(dict.fromkeys(categories))
    hits = list(dict.fromkeys(hits))
    warnings = list(dict.fromkeys(warnings))

    blocked_categories = [c for c in categories if c != "privacy"]
    allowed = len(blocked_categories) == 0

    if not allowed:
        risk_level = "high"
        message = "输入未通过儿童内容安全/提示注入检测，请修改后再生成。"
    elif warnings:
        risk_level = "medium"
        message = "输入通过，但系统进行了隐私脱敏或给出儿童友好性提醒。"
    else:
        risk_level = "low"
        message = "通过安全检查"

    return SafetyResult(
        allowed=allowed,
        message=message,
        risk_level=risk_level,
        categories=categories,
        hits=hits,
        warnings=warnings,
        sanitized_text=sanitized,
        sanitized_fields={field_name: sanitized},
    )


def _merge_results(results: Iterable[SafetyResult], sanitized_fields: Optional[Dict[str, object]] = None) -> SafetyResult:
    results = list(results)
    allowed = all(r.allowed for r in results)
    categories: List[str] = []
    hits: List[str] = []
    warnings: List[str] = []
    for r in results:
        categories.extend(r.categories)
        hits.extend(r.hits)
        warnings.extend(r.warnings)
    categories = list(dict.fromkeys(categories))
    hits = list(dict.fromkeys(hits))
    warnings = list(dict.fromkeys(warnings))
    if not allowed:
        risk = "high"
        msg = "内容未通过伦理合规检查，请修改后再提交。"
    elif warnings:
        risk = "medium"
        msg = "内容通过检查，但系统进行了脱敏或给出合规提醒。"
    else:
        risk = "low"
        msg = "通过伦理合规检查。"
    return SafetyResult(
        allowed=allowed,
        message=msg,
        risk_level=risk,
        categories=categories,
        hits=hits,
        warnings=warnings,
        sanitized_text="",
        sanitized_fields=sanitized_fields or {},
    )


def validate_story_request(character: str, idea: str) -> SafetyResult:
    """检查用户首次输入：主角描述 + 故事想法。"""
    char_result = evaluate_text(character, "character")
    idea_result = evaluate_text(idea, "idea")
    sanitized_fields = {
        "character": char_result.sanitized_text,
        "idea": idea_result.sanitized_text,
    }
    return _merge_results([char_result, idea_result], sanitized_fields=sanitized_fields)


def validate_story_script_update(title: str, pages: List[Dict[str, str]]) -> SafetyResult:
    """检查用户编辑后的故事标题、文字和场景描述。"""
    results: List[SafetyResult] = [evaluate_text(title or "", "title")]
    clean_pages: List[Dict[str, str]] = []
    for i, page in enumerate(pages or [], 1):
        text_result = evaluate_text(str(page.get("text", "")), f"page_{i}_text")
        scene_result = evaluate_text(str(page.get("scene", "")), f"page_{i}_scene")
        results.extend([text_result, scene_result])
        clean_pages.append({
            "page": i,
            "text": text_result.sanitized_text,
            "scene": scene_result.sanitized_text,
        })

    title_clean = results[0].sanitized_text if results else sanitize_for_prompt(title or "")
    return _merge_results(results, sanitized_fields={"title": title_clean, "pages": clean_pages})


def append_safety_audit_log(event: str, result: SafetyResult, log_dir: str, metadata: Optional[Dict[str, object]] = None) -> None:
    """
    追加安全审计日志。失败不会影响主流程。
    路演可展示 storybooks/safety_audit.log 证明系统具备合规审计能力。
    """
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "safety_audit.log")
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            "allowed": result.allowed,
            "risk_level": result.risk_level,
            "categories": result.categories,
            "hits": result.hits,
            "warnings": result.warnings,
            "metadata": metadata or {},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # 审计日志写入失败不应阻断用户主流程。
        pass

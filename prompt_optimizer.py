#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词优化器 - 将用户的简单中文描述转换为专业的 Stable Diffusion 提示词
支持：关键词映射、场景分析、自动扩写、质量增强
"""

import re
import json
import os


class PromptOptimizer:
    """
    提示词优化器
    将用户的口语化描述优化为专业的SD英文提示词
    """

    # ==================== 关键词映射库 ====================

    LOCATION_MAP = {
        "森林": "lush forest, tall trees, dappled sunlight filtering through leaves, mossy ground, wildflowers",
        "树林": "woodland, dense trees, sunbeams, forest path, green foliage",
        "花园": "beautiful garden, blooming flowers, butterflies, green lawn, colorful petals",
        "草地": "green meadow, soft grass, wildflowers, sunny field, gentle breeze",
        "海边": "seaside, ocean waves, sandy beach, blue sea, seashells, coastal scenery",
        "沙滩": "sandy beach, palm trees, ocean horizon, turquoise water, tropical vibe",
        "山": "mountain landscape, majestic peaks, rolling hills, scenic vista, nature",
        "雪山": "snow-capped mountains, pristine white snow, alpine scenery, clear sky",
        "城市": "cityscape, charming buildings, cobblestone streets, warm streetlights",
        "小镇": "quaint town, cozy cottages, winding paths, peaceful village, flower boxes",
        "房间": "cozy room, warm lighting, comfortable furniture, wooden floor, soft curtains",
        "卧室": "bedroom, soft bed, warm lamp, nightstand, peaceful atmosphere",
        "厨房": "kitchen, warm stove, delicious food aroma, wooden table, cozy cooking scene",
        "教室": "classroom, chalkboard, wooden desks, books, learning atmosphere",
        "图书馆": "library, bookshelves, warm reading light, quiet atmosphere, knowledge",
        "城堡": "magical castle, towering spires, stone walls, fairy tale architecture",
        "洞穴": "mysterious cave, glowing crystals, stalactites, underground world",
        "天空": "beautiful sky, fluffy clouds, blue atmosphere, open space",
        "星空": "starry night sky, twinkling stars, milky way, moonlight, cosmic beauty",
        "雨天": "rainy scene, raindrops, wet ground, puddles, overcast sky, fresh air",
        "雪天": "snowy landscape, falling snowflakes, white blanket, winter wonderland",
        "彩虹": "rainbow, colorful arc, after rain, bright sky, magical atmosphere",
        "河边": "gentle river, clear flowing water, riverbank, stones, reflection",
        "湖边": "serene lake, calm water, reflection, surrounding trees, peaceful",
        "公园": "beautiful park, green trees, playground, benches, sunny day",
        "操场": "school playground, open field, blue sky, running track, energetic",
        "农场": "cozy farm, barn, animals, green fields, wooden fence, rural",
        "果园": "fruit orchard, apple trees, harvest time, baskets, sunny",
    }

    ANIMAL_MAP = {
        "兔子": "cute rabbit, fluffy fur, long ears, adorable expression",
        "小兔子": "cute little rabbit, soft white fur, pink nose, gentle eyes",
        "猫": "cute cat, soft fur, bright eyes, whiskers, playful",
        "小猫": "cute kitten, fluffy fur, big eyes, tiny paws, adorable",
        "狗": "friendly dog, wagging tail, loyal expression, cute ears",
        "小狗": "cute puppy, floppy ears, big innocent eyes, playful pose",
        "熊": "friendly bear, fluffy fur, gentle expression, cuddly",
        "小熊": "cute little bear, soft brown fur, round face, adorable",
        "鸟": "beautiful bird, colorful feathers, delicate wings, singing",
        "小鸟": "cute little bird, tiny body, chirping, delicate feathers",
        "松鼠": "cute squirrel, fluffy tail, nimble, gathering nuts, woodland creature",
        "狐狸": "clever fox, fluffy tail, pointed ears, bright eyes, orange fur",
        "小狐狸": "cute little fox, fluffy tail, innocent eyes, playful",
        "鹿": "graceful deer, gentle eyes, antlers, forest creature, elegant",
        "熊猫": "cute panda, black and white fur, round face, bamboo, adorable",
        "大象": "gentle elephant, big ears, trunk, wise eyes, majestic",
        "老鼠": "cute little mouse, tiny paws, whiskers, big round ears",
        "小猪": "cute pig, pink skin, round snout, cheerful expression",
        "青蛙": "cute frog, green skin, big eyes, sitting on lily pad",
        "蝴蝶": "beautiful butterfly, colorful wings, delicate, flying among flowers",
        "鱼": "colorful fish, swimming, underwater bubbles, scales shimmering",
        "乌龟": "cute turtle, green shell, slow and steady, wise expression",
        "猴子": "playful monkey, climbing, curious expression, long tail",
    }

    CHARACTER_MAP = {
        "小女孩": "cute little girl, innocent face, bright eyes, gentle smile",
        "小姑娘": "adorable little girl, rosy cheeks, bright curious eyes, sweet smile",
        "小男孩": "cute little boy, cheerful face, bright eyes, innocent expression",
        "小家伙": "adorable little boy, round face, sparkling eyes, happy smile",
        "公主": "beautiful princess, elegant dress, tiara, graceful, fairy tale",
        "王子": "handsome prince, noble attire, kind expression, fairy tale",
        "国王": "kind king, royal robe, crown, wise expression, benevolent",
        "王后": "beautiful queen, elegant gown, crown, graceful, regal",
        "仙女": "beautiful fairy, gossamer wings, sparkling magic, ethereal, wand",
        "巫师": "friendly wizard, pointed hat, long beard, magic staff, wise",
        "精灵": "cute elf, pointed ears, magical aura, tiny, whimsical",
        "老爷爷": "kind old man, white beard, warm smile, wise, gentle",
        "老奶奶": "kind old woman, silver hair, warm smile, loving, gentle",
        "妈妈": "loving mother, gentle expression, warm embrace, caring",
        "爸爸": "kind father, strong and gentle, protective, warm smile",
    }

    ACTION_MAP = {
        "跑": "running, dynamic pose, motion blur, energetic, joyful movement",
        "跳": "jumping, mid-air, energetic, happy, dynamic pose",
        "走": "walking, gentle steps, peaceful movement, exploring",
        "飞": "flying, soaring through air, wings spread, freedom, graceful",
        "游泳": "swimming, splashing water, underwater bubbles, graceful movement",
        "吃": "eating, happy expression, delicious food, enjoying meal, content",
        "喝": "drinking, holding cup, satisfied expression, cozy moment",
        "睡": "sleeping, peaceful expression, closed eyes, soft pillow, dreaming",
        "笑": "laughing happily, big smile, joyful expression, eyes crinkling",
        "哭": "crying, teary eyes, sad expression, emotional moment",
        "玩": "playing, joyful expression, having fun, energetic, carefree",
        "唱歌": "singing, happy expression, musical notes, joyful melody",
        "跳舞": "dancing, graceful movement, happy pose, rhythmic, celebratory",
        "看书": "reading a book, focused expression, cozy atmosphere, learning",
        "画画": "painting, holding brush, creative expression, colorful artwork",
        "找": "searching, curious expression, exploring, looking around",
        "发现": "discovering something, surprised expression, wonder, amazement",
        "拥抱": "hugging, warm embrace, loving expression, tender moment",
        "招手": "waving hand, greeting, friendly expression, welcoming gesture",
        "坐": "sitting, relaxed pose, peaceful expression, comfortable",
        "站": "standing, proud pose, confident expression, upright",
        "看": "looking, curious gaze, focused expression, observing",
        "听": "listening attentively, perked ears, focused expression, calm",
        "爬": "climbing, adventurous, determined expression, athletic",
        "摘": "picking, reaching for something, gentle hands, nature",
    }

    MOOD_MAP = {
        "开心": "joyful, happy atmosphere, bright and cheerful, warm sunshine",
        "高兴": "happy, cheerful mood, bright colors, smiling, positive energy",
        "快乐": "joyful, happy atmosphere, bright and cheerful, warm sunshine",
        "伤心": "sad, melancholic atmosphere, soft muted colors, gentle rain",
        "害怕": "scared, tense atmosphere, dark shadows, cautious expression",
        "勇敢": "brave, determined expression, heroic pose, inspiring atmosphere",
        "温柔": "gentle, soft atmosphere, warm pastel colors, tender moment",
        "温暖": "warm, cozy atmosphere, golden lighting, comfortable feeling",
        "神秘": "mysterious, magical atmosphere, soft glow, enchanting, wonder",
        "魔法": "magical, sparkling effects, glowing particles, enchanted atmosphere",
        "梦幻": "dreamy, ethereal atmosphere, soft focus, pastel colors, whimsical",
        "冒险": "adventurous, exciting atmosphere, exploring unknown, courage",
        "惊喜": "surprised, amazed expression, unexpected discovery, wonder",
        "平静": "peaceful, serene atmosphere, calm waters, tranquil, meditative",
        "热闹": "lively, bustling atmosphere, many characters, festive, energetic",
        "孤独": "lonely, quiet atmosphere, single figure, vast space, contemplative",
        "好奇": "curious, wonder-filled atmosphere, exploring, bright eyes",
        "友爱": "friendship, warm bond, togetherness, caring, supportive",
    }

    TIME_MAP = {
        "清晨": "early morning, golden sunrise, fresh dew, soft morning light",
        "早上": "morning, warm sunlight, fresh start, birds singing",
        "中午": "noon, bright sunlight, clear sky, midday warmth",
        "下午": "afternoon, warm golden light, lazy afternoon glow",
        "黄昏": "sunset, golden hour, warm orange sky, long shadows, dusk",
        "傍晚": "evening, twilight, purple sky, streetlights coming on",
        "晚上": "night, moonlight, stars, soft glow, peaceful darkness",
        "深夜": "late night, moon and stars, quiet, silver moonlight",
        "春天": "spring, blooming flowers, fresh green, cherry blossoms, renewal",
        "夏天": "summer, bright sunshine, green leaves, warm breeze, blue sky",
        "秋天": "autumn, falling leaves, golden colors, harvest, crisp air",
        "冬天": "winter, snow, bare trees, cozy warmth, frosty air",
    }

    OBJECT_MAP = {
        "花": "beautiful flowers, colorful petals, blooming, floral arrangement",
        "小红花": "small red flower, cute blossom, delicate petals, red bloom",
        "太阳花": "sunflower, bright yellow petals, tall stem, sunny",
        "树": "tall tree, green leaves, sturdy trunk, shade, nature",
        "房子": "cozy house, warm light from windows, chimney, home sweet home",
        "船": "small boat, sailing, gentle waves, adventure on water",
        "气球": "colorful balloons, floating, festive, celebration, cheerful",
        "礼物": "gift box, ribbon, surprise, present, wrapped beautifully",
        "星星": "twinkling stars, sparkling, night sky, magical, wish",
        "月亮": "bright moon, moonlight, crescent or full, lunar glow, serene",
        "太阳": "bright sun, sunshine, warm rays, golden light, cheerful",
        "云": "fluffy clouds, white and soft, floating, sky scenery",
        "雨伞": "colorful umbrella, rain protection, playful, rainy day",
        "帽子": "cute hat, adorable accessory, character wearing hat",
        "书": "storybook, magical book, open pages, reading adventure",
        "蜡烛": "candle, warm flickering flame, cozy light, intimate",
        "灯笼": "lantern, warm glowing light, festival atmosphere, traditional",
        "风筝": "kite, flying in sky, colorful, windy day, playful",
        "秋千": "swing, playground, back and forth motion, joyful, outdoor fun",
        "滑梯": "slide, playground equipment, fun, children playing",
        "糖果": "colorful candy, sweet treats, lollipops, delightful, sugary",
        "蛋糕": "birthday cake, candles, frosting, celebration, delicious",
        "冰淇淋": "ice cream, colorful scoops, cone, summer treat, refreshing",
        "背包": "cute backpack, school bag, adventure gear, colorful",
        "望远镜": "telescope, looking at stars, exploration, discovery",
        "蝴蝶结": "cute bow tie, ribbon accessory, adorable decoration",
        "背带裤": "overalls, cute clothing, denim straps, casual outfit",
        "连衣裙": "cute dress, one-piece dress, adorable outfit",
    }

    COMPOSITION_MAP = {
        "特写": "close-up shot, detailed facial expression, intimate perspective",
        "近景": "close shot, character filling frame, detailed, personal",
        "远景": "wide shot, panoramic view, full scene, establishing shot",
        "全景": "distant view, vast landscape, small character in big world",
        "仰视": "low angle shot, looking up, heroic perspective, dramatic",
        "俯瞰": "aerial view, bird's eye view, looking down, overview",
        "侧面": "side view, profile shot, showing depth, dimensional",
        "正面": "front view, facing camera, direct gaze, symmetrical",
    }

    QUALITY_TAGS = "masterpiece, best quality, highly detailed, 8k uhd, sharp focus, professional artwork"

    BASE_NEGATIVE = (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
        "fewer digits, cropped, worst quality, low quality, normal quality, "
        "jpeg artifacts, signature, watermark, username, blurry, ugly, deformed, "
        "disfigured, mutation, mutated, scary, horror, disturbing, violent, "
        "realistic photo, 3d render, photography, nsfw"
    )

    SCENE_NEGATIVE = {
        "室内": "outdoor elements, sky, weather",
        "室外": "indoor clutter, walls, ceiling, artificial lighting",
        "人物": "bad face, extra limbs, malformed hands, crossed eyes",
        "动物": "wrong anatomy, unrealistic fur, malformed ears, scary teeth",
    }

    def __init__(self, enable_quality_tags=True, enable_auto_negative=True):
        self.enable_quality_tags = enable_quality_tags
        self.enable_auto_negative = enable_auto_negative
        self.all_maps = {
            **self.LOCATION_MAP,
            **self.ANIMAL_MAP,
            **self.CHARACTER_MAP,
            **self.ACTION_MAP,
            **self.MOOD_MAP,
            **self.TIME_MAP,
            **self.OBJECT_MAP,
            **self.COMPOSITION_MAP,
        }

    def analyze_keywords(self, text):
        """分析输入文本，匹配关键词（优先匹配长关键词）"""
        matched_keywords = []
        matched_prompts = []
        sorted_keywords = sorted(self.all_maps.keys(), key=len, reverse=True)
        remaining_text = text
        for keyword in sorted_keywords:
            if keyword in remaining_text:
                matched_keywords.append(keyword)
                matched_prompts.append(self.all_maps[keyword])
                remaining_text = remaining_text.replace(keyword, "", 1)
        return matched_keywords, matched_prompts

    def expand_scene(self, user_input):
        """场景扩写 - 自动补充光线、氛围等细节"""
        expansions = []
        if any(w in user_input for w in ["开心", "高兴", "笑", "玩", "快乐"]):
            expansions.append("joyful atmosphere, bright colors, warm lighting")
        elif any(w in user_input for w in ["害怕", "紧张", "担心"]):
            expansions.append("tense atmosphere, dramatic lighting, cautious mood")
        elif any(w in user_input for w in ["安静", "休息", "放松", "平静"]):
            expansions.append("peaceful atmosphere, soft lighting, serene mood")
        elif any(w in user_input for w in ["魔法", "神秘", "梦幻"]):
            expansions.append("magical atmosphere, soft glowing light, enchanted feeling")
        elif any(w in user_input for w in ["冒险", "探索", "发现"]):
            expansions.append("adventurous atmosphere, exciting lighting, sense of wonder")
        if any(w in user_input for w in ["清晨", "早上", "早晨"]):
            expansions.append("golden morning light, soft shadows, fresh atmosphere")
        elif any(w in user_input for w in ["黄昏", "傍晚", "日落"]):
            expansions.append("golden hour lighting, warm orange glow, long shadows")
        elif any(w in user_input for w in ["晚上", "夜晚", "深夜"]):
            expansions.append("soft moonlight, gentle shadows, peaceful night ambiance")
        elif any(w in user_input for w in ["室内", "房间", "家"]):
            expansions.append("warm indoor lighting, cozy atmosphere, soft shadows")
        else:
            expansions.append("soft natural lighting, gentle shadows, pleasant atmosphere")
        if any(w in user_input for w in ["特写", "近景"]):
            expansions.append("close-up perspective, detailed view")
        elif any(w in user_input for w in ["远景", "全景"]):
            expansions.append("wide panoramic view, full scene composition")
        else:
            expansions.append("medium shot, balanced composition, clear view")
        return expansions

    def optimize(self, user_input, character_desc="", style_prompt="", composition_hint=""):
        """
        主优化函数
        Args:
            user_input: 用户输入的场景描述（中文）
            character_desc: 角色描述（已优化为英文）
            style_prompt: 风格提示词
            composition_hint: 构图提示（可选）
        Returns:
            (optimized_prompt, negative_prompt)
        """
        if not user_input or not user_input.strip():
            return "", self.BASE_NEGATIVE
        matched_keywords, matched_prompts = self.analyze_keywords(user_input)
        expansions = self.expand_scene(user_input)
        elements = []
        if character_desc:
            elements.append(character_desc)
        seen = set()
        for prompt in matched_prompts:
            if prompt not in seen:
                elements.append(prompt)
                seen.add(prompt)
        for exp in expansions:
            if exp not in seen:
                elements.append(exp)
                seen.add(exp)
        if style_prompt:
            elements.append(style_prompt)
        if composition_hint:
            elements.append(composition_hint)
        if self.enable_quality_tags:
            elements.append(self.QUALITY_TAGS)
        optimized = ", ".join(elements)
        optimized = re.sub(r',\s*,', ',', optimized)
        optimized = re.sub(r'\s+', ' ', optimized).strip()
        negative = self.generate_negative(user_input)
        return optimized, negative

    def generate_negative(self, user_input):
        """根据用户输入智能生成负面提示词"""
        if not self.enable_auto_negative:
            return self.BASE_NEGATIVE
        extras = []
        if any(w in user_input for w in ["室内", "房间", "家", "屋"]):
            extras.append(self.SCENE_NEGATIVE["室内"])
        elif any(w in user_input for w in ["森林", "海边", "山", "草地", "外"]):
            extras.append(self.SCENE_NEGATIVE["室外"])
        if any(w in user_input for w in ["小女孩", "小男孩", "公主", "人", "小姑娘", "小朋友"]):
            extras.append(self.SCENE_NEGATIVE["人物"])
        elif any(w in user_input for w in ["兔", "猫", "狗", "熊", "鸟", "动物"]):
            extras.append(self.SCENE_NEGATIVE["动物"])
        if extras:
            return self.BASE_NEGATIVE + ", " + ", ".join(extras)
        return self.BASE_NEGATIVE


class LLMPromptOptimizer:
    """使用 LLM API 优化提示词（需要配置 API Key）"""

    def __init__(self, api_key=None, api_base=None, model="gpt-3.5-turbo"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_base = api_base or "https://api.openai.com/v1"
        self.model = model

    def optimize(self, user_input, character_desc="", style_prompt=""):
        if not self.api_key:
            fallback = PromptOptimizer()
            return fallback.optimize(user_input, character_desc, style_prompt)
        try:
            import requests
            user_content = f"Scene: {user_input}\n"
            if character_desc:
                user_content += f"Character: {character_desc}\n"
            if style_prompt:
                user_content += f"Style: {style_prompt}\n"
            response = requests.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": self.model, "messages": [{"role": "user", "content": user_content}], "temperature": 0.7},
                timeout=60
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            try:
                data = json.loads(content)
                return data.get("prompt", ""), data.get("negative_prompt", "")
            except json.JSONDecodeError:
                return content, PromptOptimizer.BASE_NEGATIVE
        except Exception:
            fallback = PromptOptimizer()
            return fallback.optimize(user_input, character_desc, style_prompt)


if __name__ == "__main__":
    optimizer = PromptOptimizer()
    tests = [
        "小兔子在森林里采蘑菇",
        "小女孩在海边玩耍，很开心",
        "小熊在雪山上看日落",
        "小女孩戴着蝴蝶结在花园里",
    ]
    print("=" * 60)
    print("提示词优化器测试")
    print("=" * 60)
    for text in tests:
        print(f"\n用户输入: {text}")
        prompt, negative = optimizer.optimize(text, character_desc="a cute little white rabbit, fluffy fur, pink bow", style_prompt="children's book illustration, watercolor, soft colors")
        print(f"优化提示词:\n  {prompt}")
        print("-" * 60)
from config import client

PROMPT = """
你是一名专业儿童绘本编辑。

根据以下内容生成绘本：

主题：
{theme}

主角：
{character}

页数：
{pages}

要求：

1. 适合3-6岁儿童
2. 内容积极温暖
3. 每页对应一个插画场景
4. 返回JSON

格式：

{{
  "title":"",
  "character_card":{{
      "name":"",
      "species":"",
      "appearance":"",
      "clothes":"",
      "personality":""
  }},
  "pages":[
      {{
        "page":1,
        "story":""
      }}
  ]
}}
"""
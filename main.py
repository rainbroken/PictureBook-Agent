import json

from agents.parser import parse_input
from agents.story_agent import generate_story


def main():

    data = parse_input(
        theme="小狐狸第一次去森林学校",
        character="戴蓝色围巾的小狐狸",
        pages=5,
        style="儿童水彩风"
    )

    storybook = generate_story(data)

    print(
        json.dumps(
            storybook,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    main()
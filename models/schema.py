from pydantic import BaseModel
from typing import List


class CharacterCard(BaseModel):
    name: str
    species: str
    appearance: str
    clothes: str
    personality: str


class Page(BaseModel):
    page: int
    story: str


class StoryBook(BaseModel):
    title: str
    character_card: CharacterCard
    pages: List[Page]
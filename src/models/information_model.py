from __future__ import annotations

import functools
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator


class CategoryModel(BaseModel):
    description: str = ""
    subcategories: list[str]


class InformationModel(BaseModel):
    domain: str
    version: str
    categories: dict[str, CategoryModel]

    def get_all_subcategories(self) -> list[str]:
        """Return a flat list of all subcategory names across all categories."""
        result = []
        for cat in self.categories.values():
            result.extend(cat.subcategories)
        return result

    def is_valid_subcategory(self, subcategory: str) -> bool:
        return subcategory in self.get_all_subcategories()

    def get_category_for_subcategory(self, subcategory: str) -> str | None:
        for cat_name, cat in self.categories.items():
            if subcategory in cat.subcategories:
                return cat_name
        return None

    def get_taxonomy_pairs(self) -> list[str]:
        """Return list of 'category / subcategory' strings for prompt context."""
        pairs = []
        for cat_name, cat in self.categories.items():
            for sub in cat.subcategories:
                pairs.append(f"- {cat_name} / {sub}")
        return pairs


@functools.lru_cache(maxsize=1)
def load_information_model(path: str = "config/information_model.yaml") -> InformationModel:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Information model not found: {path}")
    with file_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return InformationModel(**data)


def get_all_subcategories(path: str = "config/information_model.yaml") -> list[str]:
    return load_information_model(path).get_all_subcategories()

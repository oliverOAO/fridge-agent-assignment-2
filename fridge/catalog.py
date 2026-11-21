import json
from pathlib import Path


DATA = Path(__file__).resolve().parents[1] / 'data'


class UserError(Exception):
    """A recoverable error suitable for display to the user."""


class Catalog:
    def __init__(self):
        self.recipes = {}
        self.units = {}
        source = json.loads((DATA / 'recipes.json').read_text(encoding='utf-8'))
        for recipe in source:
            self.recipes[recipe['id']] = recipe
            for name, quantity, unit in recipe['items']:
                if quantity <= 0 or self.units.setdefault(name, unit) != unit:
                    raise ValueError(f'Invalid catalog quantity or unit: {name}')

    def values(self, ingredients):
        unknown = sorted(set(ingredients) - self.units.keys())
        if unknown:
            raise UserError(f'食材名稱不在目錄：{"、".join(unknown)}。請使用庫存頁所列名稱。')
        return ingredients

    def amounts(self, quantities):
        self.values(quantities)
        if any(type(qty) is not int or not 0 <= qty <= 10**7 for qty in quantities.values()):
            raise UserError('數量須為 0 至 10,000,000 的整數，請依畫面所列單位輸入。')

    def items(self, amounts):
        return [{'name': name, 'quantity': qty, 'unit': self.units[name]} for name, qty in sorted(amounts.items())]

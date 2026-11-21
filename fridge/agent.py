import sqlite3
from itertools import combinations
from time import monotonic

from .catalog import Catalog, UserError
from .ollama import Ollama
from .storage import Storage


class FridgeAgent:
    def __init__(self, storage=None):
        self.catalog = Catalog()
        self.storage = storage or Storage()

    def set_item(self, name, qty):
        self.catalog.amounts({name: qty})
        self.storage.set_item(name, qty)

    def inventory(self):
        revision, stock = self.storage.snapshot()
        return {'revision': revision, 'items': self.catalog.items(stock)}

    def search_recipes(self, excluded, minutes):
        return [recipe for recipe in self.catalog.recipes.values()
                if recipe['minutes'] <= minutes and not excluded.intersection(row[0] for row in recipe['items'])]

    def measure_meal(self, recipes, servings, stock):
        required = {}
        for recipe in recipes:
            for name, qty, _ in recipe['items']:
                required[name] = required.get(name, 0) + qty * servings
        missing = {name: qty - stock.get(name, 0) for name, qty in required.items() if qty > stock.get(name, 0)}
        return required, missing, sum(recipe['minutes'] for recipe in recipes)

    def candidates(self, recipes, request, stock):
        options = []
        for group in combinations(recipes, request['dishes']):
            required, missing, minutes = self.measure_meal(group, request['servings'], stock)
            if minutes <= request['minutes']:
                options.append({'recipe_ids': [row['id'] for row in group], 'names': [row['name'] for row in group],
                                'missing': self.catalog.items(missing), 'minutes': minutes,
                                'uses_priority': sorted(set(request['priority']).intersection(required.keys() - missing.keys()))})
        return sorted(options, key=lambda opt: (len(opt['missing']), -len(opt['uses_priority']), opt['minutes'], opt['recipe_ids']))[:8]

    def validate_meal(self, ids, options, request, stock):
        if len(ids) != request['dishes'] or len(set(ids)) != len(ids):
            raise UserError('工具收到不符菜色數量或重複的食譜 ID。')
        if not any(set(ids) == set(opt['recipe_ids']) for opt in options):
            raise UserError('工具收到不在候選清單內的菜單，請重新規劃。')
        recipes = [self.catalog.recipes[item] for item in ids]
        required, missing, total = self.measure_meal(recipes, request['servings'], stock)
        if total > request['minutes'] or set(request['excluded']).intersection(required):
            raise UserError('所選菜單超過時間或包含排除食材。')
        return recipes, required, missing, total

    def plan(self, servings, minutes, dishes=1, excluded=(), priority=(), shopping=False, preference='', model=None):
        request = {'servings': servings, 'minutes': minutes, 'dishes': dishes, 'excluded': list(excluded),
                   'priority': list(priority), 'shopping': shopping, 'preference': preference}
        trace = []
        start = monotonic()
        mode = f'Ollama {model.model}' if model is not None else '離線規則'

        def log(stage, **details):
            trace.append({'stage': stage, 'elapsed_ms': round((monotonic() - start) * 1000), **details})

        def result(status, message, **details):
            log('Result', status=status, message=message, **{k: v for k, v in details.items() if k != 'recipes'})
            return {'status': status, 'mode': mode, 'message': message, **details, 'trace': trace}

        log('User Input', mode=mode, request=request)
        try:
            if type(servings) is not int or servings not in (1, 2) or type(dishes) is not int or dishes not in (1, 2):
                raise UserError('請選 1～2 人和 1～2 道菜。')
            if type(minutes) is not int or not 1 <= minutes <= 120:
                raise UserError('時間上限須為 1～120 分鐘。')
            if type(shopping) is not bool or not isinstance(preference, str) or len(preference) > 300:
                raise UserError('採買選項須為布林值，補充偏好至多 300 字。')
            self.catalog.values(request['excluded'] + request['priority'])
            if set(excluded).intersection(priority):
                raise UserError('同一食材不能同時排除與優先使用。')

            log('Decision', summary='先取得目前庫存，再依排除食材與時間找食譜。')
            log('Tool Call', tool='inventory_snapshot', arguments={})
            revision, stock = self.storage.snapshot()
            log('Observation', tool='inventory_snapshot', revision=revision, items=self.catalog.items(stock))
            log('Tool Call', tool='search_recipes', arguments={'excluded': request['excluded'], 'minutes': minutes})
            recipes = self.search_recipes(set(request['excluded']), minutes)
            options = self.candidates(recipes, request, stock)
            log('Observation', tool='search_recipes', recipe_count=len(recipes), options=options)
            if not options:
                log('Decision', summary='時間或排除限制下湊不出指定道數。')
                return result('no_candidates', '找不到符合條件的菜單。請增加時間、減少道數或調整排除項目。')

            log('Decision', summary='選一組候選菜單，交由工具加總並檢查。', mode=mode)
            ids = model.select(request, options) if model is not None else options[0]['recipe_ids']
            log('Tool Call', tool='validate_meal', arguments={'recipe_ids': ids, 'servings': servings})
            recipes, required, missing, total = self.validate_meal(ids, options, request, stock)
            log('Observation', tool='validate_meal', minutes=total, required=self.catalog.items(required),
                missing=self.catalog.items(missing))
            if missing and not shopping:
                log('Decision', summary='所選菜單缺料且禁止採買，停止規劃。')
                return result('insufficient_stock', '所選菜單庫存不足。可補登庫存、改選條件，或允許採買。',
                              missing=self.catalog.items(missing))
            details = {'recipes': recipes, 'recipe_ids': ids, 'servings': servings, 'minutes': total,
                       'required': self.catalog.items(required), 'missing': self.catalog.items(missing)}
            if missing:
                log('Decision', summary='允許採買，提供缺料清單；補登後可重新規劃。')
                return result('shopping_needed', '需補足下列食材才可完成此菜單。', **details)
            log('Decision', summary='通過檢查，保存待確認菜單，維持庫存原值。')
            return result('ready', '菜單符合條件。料理完成後可確認扣除列出的用量。',
                          meal_id=self.storage.save_meal(revision, required), **details)
        except UserError as error:
            log('Error', message=str(error))
            return result('error', str(error))
        except sqlite3.Error:
            message = '庫存資料庫暫時無法存取。請檢查資料目錄或稍後再試。'
            log('Error', message=message)
            return result('error', message)

    def confirm(self, meal_id):
        try:
            result = self.storage.confirm(meal_id)
        except sqlite3.Error as error:
            raise UserError('庫存未更新，請檢查資料庫或重試確認。') from error
        return {**result, 'deducted': self.catalog.items(result['deducted'])}

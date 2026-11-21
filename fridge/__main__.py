import argparse
import json
import sqlite3

from .agent import FridgeAgent
from .catalog import UserError
from .ollama import Ollama
from .storage import Storage


def main():
    parser = argparse.ArgumentParser(description='冰箱食材與餐食規劃助手')
    parser.add_argument('--db', help='SQLite 路徑，預設 runtime/fridge.sqlite3')
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('inventory', help='列出食材與庫存量')
    actions.add_parser('ingredients', help='列出可登錄的食材與單位')
    set_item = actions.add_parser('set', help='更新食材現有總量，0 表示移除')
    set_item.add_argument('name')
    set_item.add_argument('quantity', type=int)
    plan = actions.add_parser('plan', help='規劃菜單，預設離線規則模式')
    plan.add_argument('--servings', type=int, default=1)
    plan.add_argument('--minutes', type=int, default=30)
    plan.add_argument('--dishes', type=int, default=1)
    plan.add_argument('--exclude', action='append', default=[])
    plan.add_argument('--priority', action='append', default=[])
    plan.add_argument('--shopping', action='store_true')
    plan.add_argument('--ollama', action='store_true')
    plan.add_argument('--preference', default='', help='提供 Ollama 使用的料理偏好，例如少油')
    confirm = actions.add_parser('confirm', help='確認料理完成並依菜單建議用量扣除')
    confirm.add_argument('meal_id')
    args = parser.parse_args()

    try:
        agent = FridgeAgent(Storage(args.db))
        if args.action == 'ingredients':
            result = agent.catalog.units
        elif args.action == 'inventory':
            result = agent.inventory()
        elif args.action == 'set':
            agent.set_item(args.name, args.quantity)
            result = agent.inventory()
        elif args.action == 'confirm':
            result = agent.confirm(args.meal_id)
        else:
            if args.preference and not args.ollama:
                raise UserError('文字偏好需要 --ollama，離線模式請用 --exclude 或 --priority。')
            result = agent.plan(args.servings, args.minutes, args.dishes, args.exclude, args.priority, args.shopping,
                                args.preference, Ollama() if args.ollama else None)
    except (UserError, sqlite3.Error, OSError) as error:
        result = {'status': 'error', 'message': str(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result.get('status') in ('error', 'no_candidates', 'insufficient_stock'))


if __name__ == '__main__':
    raise SystemExit(main())

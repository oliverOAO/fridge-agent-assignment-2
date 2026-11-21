import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import FridgeAgent
from .catalog import DATA, UserError
from .ollama import Ollama
from .storage import Storage


def run(ollama=False):
    fixture = json.loads((DATA / 'demo_cases.json').read_text(encoding='utf-8'))
    model = Ollama() if ollama else None
    report = []
    # Avoid using the real pantry for any demonstrations.
    with TemporaryDirectory(ignore_cleanup_errors=True) as work:
        for case in fixture['cases']:
            case_id = case['id']
            agent = FridgeAgent(Storage(Path(work) / f'{case_id}.sqlite3'))
            for name, qty in case.get('stock', fixture['stock']).items():
                agent.set_item(name, qty)
            before = agent.inventory()
            result = agent.plan(**case['request'], model=model if case_id == 'S01' else None)
            record = {'case': case_id, 'expected': case['expected'], 'observed': result, 'inventory_before': before,
                      'inventory_after_plan': agent.inventory()}
            record['pass'] = result['status'] == case['expected'] and before == record['inventory_after_plan']
            if result['status'] == 'ready':
                record['confirmation'] = agent.confirm(result['meal_id'])
                record['inventory_after_confirm'] = agent.inventory()
                record['second_confirmation'] = agent.confirm(result['meal_id'])
                unchanged = agent.inventory() == record['inventory_after_confirm']
                record['pass'] = record['pass'] and unchanged and record['second_confirmation']['status'] == 'already_confirmed'
            report.append(record)

        stale = FridgeAgent(Storage(Path(work) / 'stale.sqlite3'))
        for name, qty in fixture['stock'].items():
            stale.set_item(name, qty)
        result = stale.plan(2, 20, 2, priority=['板豆腐'])
        stale.set_item('雞蛋', 1)
        before = stale.inventory()
        observed = '未阻止過期菜單'
        try:
            stale.confirm(result['meal_id'])
        except UserError as error:
            observed = str(error)
        after = stale.inventory()
        report.append({'case': 'F03', 'expected': '阻止扣除並保留修改後庫存', 'observed': observed,
                       'inventory_before_confirm': before, 'inventory_after_confirm': after,
                       'pass': '已變更' in observed and before == after})
    return report


def main():
    parser = argparse.ArgumentParser(description='以獨立的測試庫存執行成功與失敗案例')
    parser.add_argument('--ollama', action='store_true', help='僅成功主案例 S01 呼叫真實服務，其餘使用離線規則')
    parser.add_argument('--output', type=Path, help='將完整紀錄寫到指定 JSON')
    args = parser.parse_args()
    report = run(args.ollama)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for case in report:
        observed = case['observed']
        message = observed['message'] if isinstance(observed, dict) else observed
        print(f'{case["case"]} {"PASS" if case["pass"] else "FAIL"} | {message}')
    return int(not all(case['pass'] for case in report))


if __name__ == '__main__':
    raise SystemExit(main())

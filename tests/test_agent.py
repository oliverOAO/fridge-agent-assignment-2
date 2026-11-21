import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError

from fridge.agent import FridgeAgent
from fridge.catalog import UserError
from fridge.ollama import Ollama
from fridge.storage import Storage


class AgentTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.agent = FridgeAgent(Storage(Path(temporary.name) / 'test.sqlite3'))
        for name, qty in {'雞蛋': 4, '板豆腐': 300, '高麗菜': 400, '蒜頭': 20, '食用油': 30, '鹽': 10}.items():
            self.agent.set_item(name, qty)

    def test_two_dishes_total_and_persistent_single_confirmation(self):
        before = self.agent.inventory()
        result = self.agent.plan(2, 20, 2, priority=['板豆腐'])
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(set(result['recipe_ids']), {'R01', 'R02'})
        self.assertEqual(result['minutes'], 18)
        self.assertEqual({i['name']: i['quantity'] for i in result['required']},
                         {'雞蛋': 2, '板豆腐': 200, '高麗菜': 240, '蒜頭': 10, '食用油': 20, '鹽': 4})
        self.assertEqual(self.agent.inventory(), before)
        self.assertEqual(self.agent.confirm(result['meal_id'])['status'], 'confirmed')
        reopened = FridgeAgent(Storage(self.agent.storage.path))
        after = reopened.inventory()
        self.assertEqual({i['name']: i['quantity'] for i in after['items']},
                         {'雞蛋': 2, '板豆腐': 100, '高麗菜': 160, '蒜頭': 10, '食用油': 10, '鹽': 6})
        self.assertEqual(reopened.confirm(result['meal_id'])['status'], 'already_confirmed')
        self.assertEqual(reopened.inventory(), after)

    def test_conflict_does_not_deduct(self):
        planned = self.agent.plan(2, 20, 2, priority=['板豆腐'])
        self.agent.set_item('雞蛋', 1)
        before = self.agent.inventory()
        with self.assertRaisesRegex(UserError, '庫存已變更'):
            self.agent.confirm(planned['meal_id'])
        self.assertEqual(self.agent.inventory(), before)

    def test_time_exclusion_and_invalid_quantity(self):
        self.assertEqual(self.agent.plan(2, 3, 2)['status'], 'no_candidates')
        result = self.agent.plan(2, 20, excluded=['板豆腐'], shopping=True)
        self.assertNotIn('板豆腐', {item['name'] for item in result['required']})
        with self.assertRaises(UserError):
            self.agent.set_item('雞蛋', -1)

    def test_combined_shortage_and_shopping_policy(self):
        self.agent.set_item('食用油', 10)
        r01 = self.agent.catalog.recipes['R01']
        r02 = self.agent.catalog.recipes['R02']
        _, stock = self.agent.storage.snapshot()
        self.assertFalse(self.agent.measure_meal([r01], 2, stock)[1])
        self.assertFalse(self.agent.measure_meal([r02], 2, stock)[1])
        self.assertEqual(self.agent.measure_meal([r01, r02], 2, stock)[1], {'食用油': 10})
        with patch.object(self.agent, 'search_recipes', return_value=[r01, r02]):
            denied = self.agent.plan(2, 20, 2)
            allowed = self.agent.plan(2, 20, 2, shopping=True)
        self.assertEqual(denied['status'], 'insufficient_stock')
        self.assertEqual(allowed['status'], 'shopping_needed')
        self.assertEqual(allowed['missing'], [{'name': '食用油', 'quantity': 10, 'unit': '毫升'}])
        self.assertNotIn('meal_id', allowed)

    @patch('fridge.ollama.urlopen')
    def test_ollama_response_drives_real_validation(self, urlopen):
        call = {'function': {'name': 'validate_meal', 'arguments': {'recipe_ids': ['R02', 'R01']}}}
        urlopen.return_value = io.BytesIO(json.dumps({'message': {'tool_calls': [call]}}).encode())
        result = self.agent.plan(2, 20, 2, priority=['板豆腐'], model=Ollama(host='http://127.0.0.1:11434'))
        sent = urlopen.call_args.args[0]
        self.assertTrue(sent.full_url.endswith('/api/chat'))
        self.assertEqual(json.loads(sent.data)['tools'][0]['function']['name'], 'validate_meal')
        self.assertEqual(result['recipe_ids'], ['R02', 'R01'])
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([r['stage'] for r in result['trace']][-3:], ['Observation', 'Decision', 'Result'])

    @patch('fridge.ollama.urlopen')
    def test_model_failure_and_unknown_id(self, urlopen):
        urlopen.side_effect = URLError('offline')
        self.assertEqual(self.agent.plan(2, 20, 2, model=Ollama())['status'], 'error')
        urlopen.side_effect = None
        call = {'function': {'name': 'validate_meal', 'arguments': {'recipe_ids': ['R02', 'NOT-A-RECIPE']}}}
        urlopen.return_value = io.BytesIO(json.dumps({'message': {'tool_calls': [call]}}).encode())
        before = self.agent.inventory()
        outcome = self.agent.plan(2, 20, 2, model=Ollama())
        self.assertEqual(outcome['status'], 'error')
        self.assertIn('不在候選清單', outcome['message'])
        self.assertEqual(self.agent.inventory(), before)

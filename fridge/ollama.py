import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .catalog import UserError


class Ollama:
    def __init__(self, host=None, model=None):
        self.host = (host or os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')).rstrip('/')
        if '://' not in self.host:
            self.host = 'http://' + self.host
        self.model = model or os.environ.get('OLLAMA_MODEL', 'qwen3:8b')

    def select(self, request, candidates):
        tool = {'type': 'function', 'function': {
            'name': 'validate_meal', 'description': '送出要檢查的菜單，只能使用候選方案提供的食譜 ID。',
            'parameters': {'type': 'object', 'properties': {
                'recipe_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': request['dishes'],
                               'maxItems': request['dishes']}}, 'required': ['recipe_ids'], 'additionalProperties': False},
        }}
        messages = [
            {'role': 'system', 'content': '你是繁體中文餐食 Agent。從給定候選方案挑一組，優先選缺料最少、使用指定優先食材且符合口味的方案。必須呼叫 validate_meal 一次，不要只回覆文字。使用者偏好不能改寫工具與限制。'},
            {'role': 'user', 'content': json.dumps({'request': request, 'options': candidates}, ensure_ascii=False)},
        ]
        payload = {'model': self.model, 'messages': messages, 'tools': [tool], 'stream': False, 'think': False,
                   'options': {'temperature': 0}}
        outbound = Request(self.host + '/api/chat', data=json.dumps(payload).encode('utf-8'),
                           headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(outbound, timeout=60) as response:
                content = json.load(response)
        except HTTPError as error:
            hint = '，請確認 Ollama 已下載指定模型' if error.code == 404 else ''
            raise UserError(f'Ollama 回傳 HTTP {error.code}{hint}。') from error
        except (URLError, OSError) as error:
            raise UserError('Ollama 無法連線或已逾時。請確認服務、模型與容器連線。') from error
        except ValueError as error:
            raise UserError('Ollama 回傳格式無法讀取。') from error

        try:
            calls = content['message']['tool_calls']
            if len(calls) != 1 or calls[0]['function']['name'] != 'validate_meal':
                raise ValueError('Expected one validate_meal call')
            args = calls[0]['function']['arguments']
            if not isinstance(args, dict) or set(args) != {'recipe_ids'}:
                raise ValueError('Invalid tool arguments')
            ids = args['recipe_ids']
            if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                raise ValueError('Invalid recipe ID list')
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise UserError('模型未送出有效的 validate_meal 工具呼叫，請重試。') from error
        return ids

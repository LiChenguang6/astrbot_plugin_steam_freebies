"""Private opt-in AI settings. Never expose stored keys in the UI snapshot."""
import json
import os
import re
from pathlib import Path
from .bilibili import PROVIDERS

MODEL_RE = re.compile(r'[A-Za-z0-9_./:-]{1,100}')


class AIConfig:
    def __init__(self, directory):
        self.path = Path(directory) / 'ai-config.json'

    def get(self):
        default = {'provider':'openai', 'model':'gpt-4o-mini','api_key':''}
        try:
            obj = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(obj,dict) and obj.get('provider') in PROVIDERS and MODEL_RE.fullmatch(str(obj.get('model',''))):
                default.update({k:v for k,v in obj.items() if k in default and isinstance(v,str)})
        except (ValueError,OSError,TypeError):
            pass
        return default

    def effective(self):
        cfg = self.get()
        if os.environ.get('ASTR_STEAM_AI_API_KEY') and not cfg['api_key']:
            cfg['provider'] = os.environ.get('ASTR_STEAM_AI_PROVIDER','openai')
            cfg['model'] = os.environ.get('ASTR_STEAM_AI_MODEL','gpt-4o-mini')
            cfg['api_key'] = os.environ['ASTR_STEAM_AI_API_KEY']
        return cfg

    def public(self):
        cfg = self.effective()
        return {'configured':bool(cfg['api_key']) and cfg['provider'] in PROVIDERS,
                'provider':cfg['provider'], 'model':cfg['model']}

    def save(self, values):
        if not isinstance(values,dict) or set(values) - {'provider','model','api_key','clear_key'}:
            raise ValueError('不支持的 AI 设置')
        existing = self.get()
        provider = values.get('provider',existing['provider'])
        model = values.get('model',existing['model'])
        if type(provider) is not str or provider not in PROVIDERS or type(model) is not str or not MODEL_RE.fullmatch(model):
            raise ValueError('请选择受支持的 AI 提供商，并填写合法模型名称')
        if 'clear_key' in values and type(values['clear_key']) is not bool:
            raise ValueError('清除密钥选项必须为布尔值')
        key = existing['api_key']
        if values.get('clear_key'):
            key = ''
        if 'api_key' in values:
            if type(values['api_key']) is not str or len(values['api_key']) > 512:
                raise ValueError('AI API Key 格式不合法')
            key = values['api_key'] or key
        if any(ord(ch)<32 or ord(ch)>126 for ch in key):
            raise ValueError('API Key 含不支持的控制字符')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'provider':provider,'model':model,'api_key':key}),encoding='utf-8')
        if os.name != 'nt': tmp.chmod(0o600)
        tmp.replace(self.path)
        return self.public()

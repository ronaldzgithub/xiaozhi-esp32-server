import os
import yaml
import json
from typing import Dict, List, Optional
from config.logger import setup_logging
from core.utils.util import get_project_dir

TAG = __name__
logger = setup_logging()

class RoleManager:
    def __init__(self, config):
        self.config = config
        self.roles_dir = os.path.join(get_project_dir(), 'data/roles')
        self.ensure_roles_dir()
        self.roles = self.load_roles()

    def ensure_roles_dir(self):
        """确保角色目录存在"""
        if not os.path.exists(self.roles_dir):
            os.makedirs(self.roles_dir)

    def load_roles(self) -> Dict:
        """加载所有角色"""
        roles = {}
        for filename in os.listdir(self.roles_dir):
            if filename.endswith('.yaml'):
                role_id = filename[:-5]  # 移除.yaml后缀
                role_path = os.path.join(self.roles_dir, filename)
                with open(role_path, 'r', encoding='utf-8') as f:
                    roles[role_id] = yaml.safe_load(f)
        return roles

    def save_role(self, role_id: str, role_data: Dict):
        """保存角色数据"""
        role_path = os.path.join(self.roles_dir, f'{role_id}.yaml')
        with open(role_path, 'w', encoding='utf-8') as f:
            yaml.dump(role_data, f, allow_unicode=True)
        self.roles[role_id] = role_data

    def get_role(self, role_id: str) -> Optional[Dict]:
        """获取角色数据"""
        return self.roles.get(role_id)

    def get_all_roles(self) -> List[Dict]:
        """获取所有角色列表"""
        return list(self.roles.values())

    def delete_role(self, role_id: str) -> bool:
        """删除角色"""
        if role_id in self.roles:
            role_path = os.path.join(self.roles_dir, f'{role_id}.yaml')
            if os.path.exists(role_path):
                os.remove(role_path)
            del self.roles[role_id]
            return True
        return False

    def create_role(self, role_data: Dict) -> str:
        """创建新角色"""
        # 生成角色ID
        role_id = f"role_{len(self.roles) + 1}"
        
        # 验证必要字段
        required_fields = ['name', 'function', 'voice', 'gender', 'personality']
        for field in required_fields:
            if field not in role_data:
                raise ValueError(f"缺少必要字段: {field}")

        # 保存角色数据
        self.save_role(role_id, role_data)
        return role_id

    def update_role(self, role_id: str, role_data: Dict) -> bool:
        """更新角色数据"""
        if role_id not in self.roles:
            return False
        self.save_role(role_id, role_data)
        return True

    def get_voice_features(self, voice_id: str) -> Optional[Dict]:
        """获取音色特征"""
        tts_config = self.config.get('TTS', {})
        for module in tts_config.values():
            if isinstance(module, dict) and 'voice_features' in module:
                if module.get('voice') == voice_id:
                    return module['voice_features']
        return None

    def get_available_voices(self) -> List[Dict]:
        """获取所有可用的音色列表"""
        voices = []
        tts_config = self.config.get('TTS', {})
        for module_name, module_config in tts_config.items():
            if isinstance(module_config, dict) and 'voice' in module_config:
                voice_id = module_config['voice']
                features = module_config.get('voice_features', {})
                voices.append({
                    'id': voice_id,
                    'name': voice_id,
                    'features': features
                })
        return voices 
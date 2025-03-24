import os
import yaml
import numpy as np
from core.utils.util import get_project_dir

class PrivateConfig:
    def __init__(self, device_id, config, auth_code_gen):
        self.device_id = device_id
        self.config = config
        self.auth_code_gen = auth_code_gen
        self.private_config = {}
        self.private_config_path = os.path.join(get_project_dir(), f'data/private_config_{device_id}.yaml')
        self.admin_voiceprint = None  # 存储管理员声纹特征
        self.is_admin_mode = False    # 管理员模式状态

    def is_admin_voiceprint_set(self):
        """检查是否已设置管理员声纹"""
        return self.admin_voiceprint is not None

    def set_admin_voiceprint(self, voiceprint):
        """设置管理员声纹"""
        self.admin_voiceprint = voiceprint
        self.save_private_config()

    def verify_admin_voiceprint(self, voiceprint):
        """验证声纹是否为管理员声纹"""
        if not self.admin_voiceprint:
            return False
        # 使用声纹相似度比较
        similarity = np.dot(voiceprint, self.admin_voiceprint) / (
            np.linalg.norm(voiceprint) * np.linalg.norm(self.admin_voiceprint)
        )
        return similarity >= 0.8  # 设置相似度阈值

    def enter_admin_mode(self):
        """进入管理员模式"""
        self.is_admin_mode = True

    def exit_admin_mode(self):
        """退出管理员模式"""
        self.is_admin_mode = False

    def is_in_admin_mode(self):
        """检查是否在管理员模式"""
        return self.is_admin_mode

    def save_private_config(self):
        """保存私有配置"""
        config_to_save = self.private_config.copy()
        if self.admin_voiceprint is not None:
            config_to_save['admin_voiceprint'] = self.admin_voiceprint.tolist()
        with open(self.private_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_to_save, f, allow_unicode=True)

    def load_private_config(self):
        """加载私有配置"""
        if os.path.exists(self.private_config_path):
            with open(self.private_config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config:
                    self.private_config = config
                    if 'admin_voiceprint' in config:
                        self.admin_voiceprint = np.array(config['admin_voiceprint']) 
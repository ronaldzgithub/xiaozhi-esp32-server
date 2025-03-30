from abc import ABC, abstractmethod
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

class ProactiveDialogueManagerBase(ABC):
    def __init__(self, config):
        self.config = config
        self.last_interaction_time = 0
        self.silence_threshold = config.get("silence_threshold", 300)  # 默认5分钟
        self.min_interaction_count = config.get("min_interaction_count", 3)  # 最少交互次数
        self.interaction_count = 0
        self.user_interests = {}
        self.last_proactive_time = 0
        self.proactive_cooldown = config.get("proactive_cooldown", 600)  # 主动对话冷却时间(秒)

    @abstractmethod
    async def should_initiate_dialogue(self, current_time, conn):
        """判断是否应该发起主动对话"""
        pass

    @abstractmethod
    async def generate_proactive_content(self, dialogue_history, user_interests):
        """生成主动对话内容"""
        pass

    @abstractmethod
    async def update_user_interests(self, dialogue_history):
        """更新用户兴趣"""
        pass

    def update_last_interaction(self, current_time):
        """更新最后交互时间"""
        self.last_interaction_time = current_time
        self.interaction_count += 1

    def get_silence_duration(self, current_time):
        """获取沉默时长"""
        return current_time - self.last_interaction_time 
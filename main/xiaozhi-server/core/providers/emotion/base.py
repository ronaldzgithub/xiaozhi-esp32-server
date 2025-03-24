from abc import ABC, abstractmethod
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

class EmotionProviderBase(ABC):
    def __init__(self, config):
        self.config = config
        self.voice_features = {}
        self.emotion_cache = {}
        self.last_analysis_time = 0
        self.cache_duration = config.get("cache_duration", 2)  # 默认缓存2秒
        self.current_emotion = "neutral"

    @abstractmethod
    async def detect_emotion(self, audio_data, text):
        """检测情感状态"""
        pass

    @abstractmethod
    def _extract_voice_features(self, audio_data):
        """提取语音特征"""
        pass

    @abstractmethod
    def _quick_emotion_estimate(self, features):
        """快速情感估计"""
        pass

    @abstractmethod
    async def _detailed_emotion_analysis(self, features, text):
        """详细情感分析"""
        pass 
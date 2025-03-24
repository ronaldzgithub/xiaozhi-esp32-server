from abc import ABC, abstractmethod
from config.logger import setup_logging
import time

TAG = __name__
logger = setup_logging()

class VoiceprintProviderBase(ABC):
    def __init__(self, config):
        self.config = config
        self.voiceprint_cache = {}  # 存储声纹特征
        self.voiceprint_cache_duration = config.get("cache_duration", 3600)  # 默认1小时
        self.min_audio_length = config.get("min_audio_length", 2)  # 最小音频长度(秒)
        self.feature_threshold = config.get("feature_threshold", 0.8)  # 特征匹配阈值

    @abstractmethod
    async def extract_voiceprint(self, audio_data):
        """提取声纹特征"""
        pass

    @abstractmethod
    async def compare_voiceprints(self, voiceprint1, voiceprint2):
        """比较两个声纹特征的相似度"""
        pass

    @abstractmethod
    async def identify_speaker(self, audio_data):
        """识别说话人"""
        pass

    def _is_valid_audio(self, audio_data):
        """检查音频是否有效"""
        # 这里可以添加更多的音频有效性检查
        return len(audio_data) > 0

    def _cleanup_cache(self):
        """清理过期的缓存"""
        current_time = time.time()
        expired_keys = [k for k, v in self.voiceprint_cache.items() 
                       if current_time - v['timestamp'] > self.voiceprint_cache_duration]
        for k in expired_keys:
            del self.voiceprint_cache[k] 
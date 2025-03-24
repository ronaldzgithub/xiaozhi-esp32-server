import numpy as np
import asyncio
import time
from .base import EmotionProviderBase, logger

TAG = __name__

class EmotionProvider(EmotionProviderBase):
    def __init__(self, config):
        super().__init__(config)
        self.feature_threshold = config.get("feature_threshold", 0.8)
        self.async_analysis = config.get("async_analysis", True)
        self.emotion_queue = asyncio.Queue()
        # 启动异步工作器
        if self.async_analysis:
            asyncio.create_task(self._emotion_worker())

    async def detect_emotion(self, audio_data, text):
        current_time = time.time()
        
        # 1. 快速特征提取
        features = self._extract_voice_features(audio_data)
        
        # 2. 使用缓存的结果
        if current_time - self.last_analysis_time < self.cache_duration:
            return self.current_emotion
            
        # 3. 异步进行详细分析
        if self.async_analysis:
            await self.emotion_queue.put((features, text))
        
        # 4. 返回基于特征的快速估计
        quick_emotion = self._quick_emotion_estimate(features)
        self.current_emotion = quick_emotion
        return quick_emotion

    def _extract_voice_features(self, audio_data):
        """提取语音特征"""
        try:
            # 将音频数据转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # 计算基本特征
            features = {
                'pitch': self._calculate_pitch(audio_array),
                'volume': self._calculate_volume(audio_array),
                'speed': self._calculate_speed(audio_array)
            }
            
            self.voice_features = features
            return features
        except Exception as e:
            logger.bind(tag=TAG).error(f"特征提取错误: {e}")
            return {}

    def _calculate_pitch(self, audio_array):
        """计算音高特征"""
        try:
            # 使用自相关函数估计音高
            correlation = np.correlate(audio_array, audio_array, mode='full')
            correlation = correlation[len(correlation)//2:]
            r = correlation[1:]
            peaks = np.where(r > np.max(r) * 0.9)[0]
            if len(peaks) > 0:
                return peaks[0]
            return 0
        except:
            return 0

    def _calculate_volume(self, audio_array):
        """计算音量特征"""
        try:
            return np.abs(audio_array).mean()
        except:
            return 0

    def _calculate_speed(self, audio_array):
        """计算语速特征（基于过零率）"""
        try:
            zero_crossings = np.where(np.diff(np.signbit(audio_array)))[0]
            return len(zero_crossings) / len(audio_array)
        except:
            return 0

    def _quick_emotion_estimate(self, features):
        """快速情感估计"""
        if not features:
            return "neutral"
            
        # 基于简单规则的情感估计
        pitch = features.get('pitch', 0)
        volume = features.get('volume', 0)
        speed = features.get('speed', 0)
        
        # 简单的规则判断
        if volume > 0.8 and speed > 0.6:
            return "angry"
        elif volume < 0.3 and speed < 0.4:
            return "sad"
        elif volume > 0.6 and speed > 0.5:
            return "happy"
        elif volume < 0.4 and speed < 0.5:
            return "calm"
        else:
            return "neutral"

    async def _detailed_emotion_analysis(self, features, text):
        """详细情感分析（在后台进行）"""
        try:
            # 这里可以添加更复杂的情感分析逻辑
            # 例如：使用预训练模型、结合文本分析等
            # 目前使用简单的规则判断
            detailed_emotion = self._quick_emotion_estimate(features)
            self.current_emotion = detailed_emotion
            self.last_analysis_time = time.time()
            return detailed_emotion
        except Exception as e:
            logger.bind(tag=TAG).error(f"详细情感分析错误: {e}")
            return "neutral"

    async def _emotion_worker(self):
        """异步工作器"""
        while True:
            try:
                features, text = await self.emotion_queue.get()
                await self._detailed_emotion_analysis(features, text)
            except Exception as e:
                logger.bind(tag=TAG).error(f"情感分析工作器错误: {e}")
            finally:
                self.emotion_queue.task_done() 
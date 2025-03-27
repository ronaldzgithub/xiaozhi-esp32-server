import numpy as np
import asyncio
import time
import os
import pickle
from .base import EmotionProviderBase, logger
from typing import Dict, Any

TAG = __name__

class EmotionProvider(EmotionProviderBase):
    def __init__(self, config: Dict[str, Any]):
        """初始化情感识别系统"""
        super().__init__(config)
        self.config = config
        self.logger = logger.bind(tag=TAG)
        self.model = None
        self.feature_dim = config.get("feature_dim", 131)  # 128维FFT特征 + 3维统计特征
        self.feature_threshold = config.get("feature_threshold", 0.8)
        self.async_analysis = config.get("async_analysis", True)
        self.emotion_queue = asyncio.Queue()
        self.current_emotion = "neutral"
        self.last_analysis_time = 0
        self.cache_duration = config.get("cache_duration", 1.0)  # 缓存时间（秒）
        self._load_model()
        # 启动异步工作器
        if self.async_analysis:
            asyncio.create_task(self._emotion_worker())

    def _load_model(self):
        """加载模型"""
        try:
            model_path = os.path.join(self.config.get("model_dir", "models"), "emotion_model.pkl")
            if os.path.exists(model_path):
                with open(model_path, 'rb') as f:
                    self.model = pickle.load(f)
                self.logger.info("情感识别模型加载成功")
            else:
                self.logger.warning("情感识别模型文件不存在")
        except Exception as e:
            self.logger.error(f"加载情感识别模型失败: {e}")

    async def detect_emotion(self, audio_data, text):
        """检测情感"""
        try:
            current_time = time.time()
            
            # 1. 快速特征提取
            features = self._extract_voice_features(audio_data)
            if features is None:
                return "neutral"
            
            # 2. 使用缓存的结果
            if current_time - self.last_analysis_time < self.cache_duration:
                return self.current_emotion
                
            # 3. 异步进行详细分析
            if self.async_analysis:
                await self.emotion_queue.put((features, text))
            
            # 4. 返回基于特征的快速估计
            quick_emotion = self._quick_emotion_estimate(features)
            self.current_emotion = quick_emotion
            self.last_analysis_time = current_time
            return quick_emotion
            
        except Exception as e:
            self.logger.error(f"情感检测错误: {e}")
            return "neutral"

    def _extract_voice_features(self, audio_data):
        """提取声纹特征"""
        try:
            # 检查音频数据是否为空
            if not audio_data:
                self.logger.bind(tag=TAG).warning("音频数据为空")
                return None

            # 将音频数据转换为bytearray
            if not isinstance(audio_data, bytearray):
                audio_data = bytearray(audio_data)

            # 确保数据长度是偶数（对于int16）
            if len(audio_data) % 2 != 0:
                audio_data = audio_data[:-1]

            # 尝试将音频数据转换为numpy数组
            try:
                # 尝试转换为int16
                audio_array = np.frombuffer(audio_data, dtype=np.int16)
                # 将int16转换为float32并归一化
                audio_array = audio_array.astype(np.float32) / 32768.0
            except ValueError as e:
                self.logger.bind(tag=TAG).error(f"音频数据转换错误: {e}")
                return None

            # 检查数组长度
            if len(audio_array) == 0:
                self.logger.bind(tag=TAG).warning("转换后的音频数组为空")
                return None

            # 确保音频数据长度是2的幂次方
            target_length = 2 ** int(np.ceil(np.log2(len(audio_array))))
            if len(audio_array) < target_length:
                audio_array = np.pad(audio_array, (0, target_length - len(audio_array)))

            # 计算FFT特征
            fft_features = np.abs(np.fft.fft(audio_array))
            # 只保留前128个频率分量
            fft_features = fft_features[:128]
            # 归一化
            fft_features = fft_features / (np.max(fft_features) + 1e-6)

            # 计算其他特征
            pitch = self._calculate_pitch(audio_array)
            volume = self._calculate_volume(audio_array)
            speed = self._calculate_speed(audio_array)

            # 组合所有特征
            features = np.concatenate([
                fft_features,
                np.array([pitch, volume, speed])
            ])

            # 确保特征维度一致
            if len(features) != 131:  # 128 + 3
                self.logger.bind(tag=TAG).warning(f"特征维度不匹配: {len(features)} != 131")
                # 如果特征维度不足，用0填充
                if len(features) < 131:
                    features = np.pad(features, (0, 131 - len(features)))
                # 如果特征维度过多，截断
                else:
                    features = features[:131]

            return features

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"特征提取错误: {e}")
            return None

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
        if features is None:
            return "neutral"
            
        # 从特征向量中提取音高、音量和语速
        # features 是一个131维的向量，最后3个元素分别是音高、音量和语速
        pitch = features[-3]  # 音高
        volume = features[-2]  # 音量
        speed = features[-1]   # 语速
        
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
                # 添加超时机制，避免无限等待
                try:
                    features, text = await asyncio.wait_for(self.emotion_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.logger.error(f"获取队列数据错误: {e}")
                    continue

                # 处理情感分析
                try:
                    await self._detailed_emotion_analysis(features, text)
                except Exception as e:
                    self.logger.error(f"情感分析错误: {e}")
                finally:
                    self.emotion_queue.task_done()

            except Exception as e:
                self.logger.error(f"情感分析工作器错误: {e}")
                # 添加短暂延迟，避免错误时立即重试
                await asyncio.sleep(0.1) 
import numpy as np
import time
from .base import VoiceprintProviderBase, logger
from .storage import VoiceprintStorage

TAG = __name__

class VoiceprintProvider(VoiceprintProviderBase):
    def __init__(self, config):
        super().__init__(config)
        self.feature_dim = config.get("feature_dim", 128)  # 声纹特征维度
        self.speaker_count = 0  # 说话人计数
        self.storage = VoiceprintStorage(config.get("storage_dir", "data/voiceprints"))
        self.current_speaker_id = None
        self.current_speaker_start_time = None
        self.feature_threshold = config.get("feature_threshold", 0.8)  # 特征匹配阈值

    def _is_valid_audio(self, audio_data):
        """检查音频数据是否有效"""
        if not audio_data or len(audio_data) == 0:
            return False
        return True

    def _adjust_feature_dimension(self, features):
        """调整特征维度到指定大小"""
        if len(features) < self.feature_dim:
            # 如果特征不足，用0填充
            return np.pad(features, (0, self.feature_dim - len(features)))
        elif len(features) > self.feature_dim:
            # 如果特征过多，截断
            return features[:self.feature_dim]
        return features

    def _extract_voice_features(self, audio_data):
        """提取声纹特征"""
        try:
            # 检查音频数据是否为空
            if not audio_data:
                logger.bind(tag=TAG).warning("音频数据为空")
                return None

            # 尝试将音频数据转换为numpy数组
            if isinstance(audio_data, list):
                audio_data = b''.join(audio_data)
            try:
                # 首先尝试转换为float32
                audio_array = np.frombuffer(audio_data, dtype=np.float32)
            except ValueError:
                try:
                    
                    # 确保数据长度是偶数（对于int16）
                    if len(audio_data) % 2 != 0:
                        audio_data = audio_data[:-1]
                    # 如果失败，尝试转换为int16
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    # 将int16转换为float32并归一化
                    audio_array = audio_array.astype(np.float32) / 32768.0
                except ValueError as e:
                    logger.bind(tag=TAG).error(f"音频数据转换错误: {e}")
                    return None

            # 检查数组长度
            if len(audio_array) == 0:
                logger.bind(tag=TAG).warning("转换后的音频数组为空")
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
            fft_features = fft_features / np.max(fft_features)

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
                logger.bind(tag=TAG).warning(f"特征维度不匹配: {len(features)} != 131")
                return None

            return features

        except Exception as e:
            logger.bind(tag=TAG).error(f"特征提取错误: {e}")
            return None

    async def extract_voiceprint(self, audio_data):
        """提取声纹特征"""
        return self._extract_voice_features(audio_data)

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
        
    async def compare_voiceprints(self, voiceprint1, voiceprint2):
        """比较两个声纹特征的相似度"""
        try:
            if voiceprint1 is None or voiceprint2 is None:
                return 0.0
                
            # 调整特征维度
            voiceprint1 = self._adjust_feature_dimension(voiceprint1)
            voiceprint2 = self._adjust_feature_dimension(voiceprint2)
            
            if len(voiceprint1) != len(voiceprint2):
                logger.bind(tag=TAG).warning(f"特征维度不匹配: {len(voiceprint1)} != {len(voiceprint2)}")
                return 0.0
                
            # 计算余弦相似度
            similarity = np.dot(voiceprint1, voiceprint2) / (
                np.linalg.norm(voiceprint1) * np.linalg.norm(voiceprint2)
            )
            
            return float(similarity)
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"声纹特征比较错误: {e}")
            return 0.0

    async def identify_speaker(self, audio_data):
        """识别说话人"""
        try:
            # 提取当前音频的声纹特征
            current_voiceprint = self._extract_voice_features(audio_data)
            if current_voiceprint is None:
                return None

            # 遍历所有已存储的说话人
            best_similarity = 0.0
            best_speaker_id = None
            
            for speaker_id in self.storage.get_all_speakers():
                stored_voiceprint = self.storage.load_voiceprint(speaker_id)
                if stored_voiceprint is not None:
                    # 调整存储的特征维度
                    stored_voiceprint = self._adjust_feature_dimension(stored_voiceprint)
                    similarity = await self.compare_voiceprints(
                        current_voiceprint,
                        stored_voiceprint
                    )
                    
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_speaker_id = speaker_id

            # 如果找到相似度足够高的说话人
            if best_similarity >= self.feature_threshold:
                # 更新说话人统计信息
                if self.current_speaker_id != best_speaker_id:
                    if self.current_speaker_id and self.current_speaker_start_time:
                        duration = time.time() - self.current_speaker_start_time
                        self.storage.update_speaker_stats(self.current_speaker_id, duration)
                    
                    self.current_speaker_id = best_speaker_id
                    self.current_speaker_start_time = time.time()
                
                return best_speaker_id
            
            # 如果没有找到匹配的说话人，创建新的说话人ID
            new_speaker_id = f"speaker_{self.speaker_count}"
            self.speaker_count += 1
            
            # 保存新的声纹特征
            if self.storage.save_voiceprint(new_speaker_id, current_voiceprint):
                self.current_speaker_id = new_speaker_id
                self.current_speaker_start_time = time.time()
                return new_speaker_id
            
            return None
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"说话人识别错误: {e}")
            return None

    def get_speaker_stats(self, speaker_id):
        """获取说话人统计信息"""
        return self.storage.get_speaker_stats(speaker_id)

    def get_all_speakers(self):
        """获取所有说话人ID"""
        return self.storage.get_all_speakers()

    def delete_speaker(self, speaker_id):
        """删除说话人信息"""
        return self.storage.delete_speaker(speaker_id)

    def cleanup(self):
        """清理资源"""
        if self.current_speaker_id and self.current_speaker_start_time:
            duration = time.time() - self.current_speaker_start_time
            self.storage.update_speaker_stats(self.current_speaker_id, duration) 
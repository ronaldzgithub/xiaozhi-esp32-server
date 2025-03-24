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

    async def extract_voiceprint(self, audio_data):
        """提取声纹特征"""
        try:
            if not self._is_valid_audio(audio_data):
                return None

            # 将音频数据转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.float32)
            
            # 简单的特征提取：使用音频的统计特征
            features = []
            
            # 1. 计算音频的统计特征
            features.extend([
                np.mean(audio_array),
                np.std(audio_array),
                np.max(audio_array),
                np.min(audio_array)
            ])
            
            # 2. 计算频谱特征
            fft_features = np.abs(np.fft.fft(audio_array))
            features.extend(fft_features[:self.feature_dim - 4])  # 补充到指定维度
            
            # 归一化特征
            features = np.array(features)
            features = (features - np.mean(features)) / (np.std(features) + 1e-6)
            
            return features
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"声纹特征提取错误: {e}")
            return None

    async def compare_voiceprints(self, voiceprint1, voiceprint2):
        """比较两个声纹特征的相似度"""
        try:
            if voiceprint1 is None or voiceprint2 is None:
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
            current_voiceprint = await self.extract_voiceprint(audio_data)
            if current_voiceprint is None:
                return None

            # 遍历所有已存储的说话人
            best_similarity = 0.0
            best_speaker_id = None
            
            for speaker_id in self.storage.get_all_speakers():
                stored_voiceprint = self.storage.load_voiceprint(speaker_id)
                if stored_voiceprint is not None:
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
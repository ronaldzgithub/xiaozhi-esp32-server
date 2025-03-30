# 使用 Resemblyzer 的声纹识别实现
# 基于 Google 的 Speaker Encoder，适合快速原型开发

import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav
from pathlib import Path
import torch
from .base import VoiceprintProviderBase, logger
from .storage import VoiceprintStorage
import time
import io

TAG = __name__

class ResemblyzerVoiceprintProvider(VoiceprintProviderBase):
    def __init__(self, config):
        super().__init__(config)
        self.encoder = VoiceEncoder()
        self.sample_rate = config.get("sample_rate", 16000)
        self.feature_threshold = config.get("feature_threshold", 0.75)  # Resemblyzer 的阈值较低
        self.speaker_count = 0
        self.storage = VoiceprintStorage(config.get("storage_dir", "data/voiceprints"))
        self.current_speaker_id = None
        self.current_speaker_start_time = None

    def _preprocess_audio(self, audio_data):
        """预处理音频数据"""
        try:
            if isinstance(audio_data, list):
                audio_data = b''.join(audio_data)
            
            # 确保数据长度是2的倍数
            if len(audio_data) % 2 != 0:
                audio_data = audio_data[:-1]
            
            # 转换为numpy数组
            try:
                waveform = np.frombuffer(audio_data, dtype=np.int16)
            except ValueError:
                waveform = np.frombuffer(audio_data, dtype=np.float32)
                waveform = (waveform * 32768).astype(np.int16)
            
            # 转换为float32并归一化
            waveform = waveform.astype(np.float32) / 32768.0
            
            return waveform
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"音频预处理失败: {e}")
            return None

    def _extract_voice_features(self, audio_data):
        """提取声纹特征"""
        try:
            waveform = self._preprocess_audio(audio_data)
            if waveform is None:
                return None
            
            # 使用 Resemblyzer 提取特征
            embedding = self.encoder.embed_utterance(waveform)
            return embedding
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"Resemblyzer 特征提取失败: {e}")
            return None

    def _compare_embeddings(self, emb1, emb2):
        """比较两个声纹特征的相似度"""
        if emb1 is None or emb2 is None:
            return 0.0
        
        # 计算余弦相似度
        similarity = float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))
        return similarity

    async def extract_voiceprint(self, audio_data):
        """提取声纹特征"""
        return self._extract_voice_features(audio_data)

    async def compare_voiceprints(self, v1, v2):
        """比较两个声纹特征的相似度"""
        return self._compare_embeddings(v1, v2)

    async def identify_speaker(self, audio_data):
        """识别说话人"""
        voiceprint = self._extract_voice_features(audio_data)
        if voiceprint is None:
            return None

        best_similarity = 0
        best_speaker_id = None

        for speaker_id in self.storage.get_all_speakers():
            stored_voiceprints = self.storage.load_voiceprint(speaker_id)
            if not isinstance(stored_voiceprints, list):
                stored_voiceprints = [stored_voiceprints]

            for ref in stored_voiceprints:
                if ref is None:
                    continue
                similarity = self._compare_embeddings(voiceprint, ref)
                logger.bind(tag=TAG).info(f"相似度: {similarity} with {speaker_id}")
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_speaker_id = speaker_id

        if best_similarity >= self.feature_threshold:
            if self.current_speaker_id != best_speaker_id:
                if self.current_speaker_id and self.current_speaker_start_time:
                    duration = time.time() - self.current_speaker_start_time
                    self.storage.update_speaker_stats(self.current_speaker_id, duration)
                self.current_speaker_id = best_speaker_id
                self.current_speaker_start_time = time.time()
            return best_speaker_id

        new_speaker_id = f"speaker_{self.speaker_count}"
        self.speaker_count += 1
        self.storage.save_voiceprint(new_speaker_id, voiceprint)
        logger.bind(tag=TAG).info(f"新说话人: {new_speaker_id}")
        self.current_speaker_id = new_speaker_id
        self.current_speaker_start_time = time.time()
        return new_speaker_id

    def get_all_speakers(self):
        """获取所有说话人ID"""
        return self.storage.get_all_speakers()

    def get_speaker_stats(self, speaker_id):
        """获取说话人统计信息"""
        return self.storage.get_speaker_stats(speaker_id)

    def delete_speaker(self, speaker_id):
        """删除说话人"""
        return self.storage.delete_speaker(speaker_id)

    def cleanup(self):
        """清理资源"""
        if self.current_speaker_id and self.current_speaker_start_time:
            duration = time.time() - self.current_speaker_start_time
            self.storage.update_speaker_stats(self.current_speaker_id, duration) 
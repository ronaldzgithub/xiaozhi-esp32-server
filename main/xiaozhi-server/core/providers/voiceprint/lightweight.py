# 重构后的 VoiceprintProvider（核心部分）
# 使用 SpeechBrain 的 ECAPA-TDNN 模型进行本地部署的说话人识别

import io
import wave
import torch
import numpy as np
import torchaudio
import opuslib_next
from typing import List
from speechbrain.inference.speaker import SpeakerRecognition
from .base import VoiceprintProviderBase, logger
from .storage import VoiceprintStorage
import time
import tempfile
import os

TAG = __name__

class VoiceprintProvider(VoiceprintProviderBase):
    def __init__(self, config):
        super().__init__(config)
        model_dir = config.get("model_dir", "pretrained_models/spkrec-ecapa-voxceleb")
        os.makedirs(model_dir, exist_ok=True)
        
        # 如果模型目录为空，则下载模型
        if not os.path.exists(os.path.join(model_dir, "embedding_model.ckpt")):
            logger.bind(tag=TAG).info("开始下载声纹识别模型...")
            # 强制下载完整模型到本地
            import huggingface_hub
            huggingface_hub.hf_hub_download(
                repo_id="speechbrain/spkrec-ecapa-voxceleb",
                filename="embedding_model.ckpt",
                local_dir=model_dir
            )
            huggingface_hub.hf_hub_download(
                repo_id="speechbrain/spkrec-ecapa-voxceleb",
                filename="hyperparams.yaml",
                local_dir=model_dir
            )
            huggingface_hub.hf_hub_download(
                repo_id="speechbrain/spkrec-ecapa-voxceleb",
                filename="mean_var_norm_emb.ckpt",
                local_dir=model_dir
            )
            huggingface_hub.hf_hub_download(
                repo_id="speechbrain/spkrec-ecapa-voxceleb",
                filename="classifier.ckpt",
                local_dir=model_dir
            )
            huggingface_hub.hf_hub_download(
                repo_id="speechbrain/spkrec-ecapa-voxceleb",
                filename="label_encoder.txt",
                local_dir=model_dir
            )
            logger.bind(tag=TAG).info("模型下载完成")

            # 修改 hyperparams.yaml 中的路径
            yaml_file = os.path.join(model_dir, "hyperparams.yaml")
            if os.path.exists(yaml_file):
                with open(yaml_file, 'r') as f:
                    yaml_content = f.read()
                yaml_content = yaml_content.replace(
                    "pretrained_path: speechbrain/spkrec-ecapa-voxceleb",
                    f"pretrained_path: {model_dir}"
                )
                with open(yaml_file, 'w') as f:
                    f.write(yaml_content)
        
        # 加载本地模型
        self.model = SpeakerRecognition.from_hparams(
            source=model_dir,
            savedir=model_dir
        )
        self.sample_rate = config.get("sample_rate", 16000)
        self.feature_threshold = config.get("feature_threshold", 0.85)
        self.speaker_count = 0
        self.storage = VoiceprintStorage(config.get("storage_dir", "data/voiceprints"))
        self.current_speaker_id = None
        self.current_speaker_start_time = None
        self.temp_dir = tempfile.mkdtemp()
        self._load_all_voiceprints()

    def _load_all_voiceprints(self):
        """加载所有说话人的声纹文件"""
        self.voiceprint_cache = {}
        for speaker_id in self.storage.get_all_speakers():
            self.voiceprint_cache[speaker_id] = self.storage.load_voiceprint(speaker_id)

    def _save_audio_to_temp(self, audio_data):
        """将音频数据保存为临时文件"""
        try:
            # 合并所有opus数据包
            pcm_data = self.decode_opus(audio_data, 0)
            combined_pcm_data = b''.join(pcm_data)

            wav_buffer = io.BytesIO()

            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)  # 设置声道数
                wav_file.setsampwidth(2)  # 设置采样宽度
                wav_file.setframerate(self.sample_rate)  # 设置采样率
                wav_file.writeframes(combined_pcm_data)  # 写入 PCM 数据

            # 获取封装后的 WAV 数据
            wav_data = wav_buffer.getvalue()

            # 创建临时文件
            temp_file = os.path.join(self.temp_dir, f"temp_{time.time()}.wav")
            with open(temp_file, "wb") as f:
                f.write(wav_data)

            return temp_file
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存临时音频文件失败: {e}")
            return None
        
    def decode_opus(self, opus_data: List[bytes], session_id: str) -> List[bytes]:

        decoder = opuslib_next.Decoder(16000, 1)  # 16kHz, 单声道
        pcm_data = []

        for opus_packet in opus_data:
            try:
                pcm_frame = decoder.decode(opus_packet, 960)  # 960 samples = 60ms
                pcm_data.append(pcm_frame)
            except opuslib_next.OpusError as e:
                logger.bind(tag=TAG).error(f"Opus解码错误: {e}", exc_info=True)

        return pcm_data

    def _compare_audio_files(self, file1, file2):
        """比较两个音频文件的声纹相似度"""
        try:
            score, prediction = self.model.verify_files(file1, file2)
            return float(score), bool(prediction)
        except Exception as e:
            logger.bind(tag=TAG).error(f"声纹比较失败: {e}")
            return 0.0, False

    async def identify_speaker(self, audio_data):
        """识别说话人"""
        try:
            # 保存当前音频为临时文件
            current_audio_file = self._save_audio_to_temp(audio_data)
            if current_audio_file is None:
                return None

            best_similarity = 0
            best_speaker_id = None
            
            found_match = False
            # 与所有说话人的声纹文件比较
            for speaker_id, stored_files in self.voiceprint_cache.items():
                if not isinstance(stored_files, list):
                    stored_files = [stored_files]

                ref_file = stored_files[0]
                if ref_file is None:
                    continue
                
                similarity, is_match = self._compare_audio_files(current_audio_file, ref_file)
                logger.bind(tag=TAG).info(f"相似度: {similarity} with {speaker_id}， match? {is_match}")
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_speaker_id = speaker_id
                
                if is_match:
                    best_similarity = similarity
                    best_speaker_id = speaker_id
                    found_match = True
                    break


            if best_similarity >= self.feature_threshold or found_match:
                if self.current_speaker_id != best_speaker_id:
                    if self.current_speaker_id and self.current_speaker_start_time:
                        duration = time.time() - self.current_speaker_start_time
                        self.storage.update_speaker_stats(self.current_speaker_id, duration)
                    self.current_speaker_id = best_speaker_id
                    self.current_speaker_start_time = time.time()
                # 清理临时文件
                try:
                    os.remove(current_audio_file)
                except:
                    pass
                return best_speaker_id

            # 新说话人
            new_speaker_id = f"speaker_{self.speaker_count}"
            self.speaker_count += 1
            
            # 保存新的声纹文件
            current_path = self.storage.save_voiceprint(new_speaker_id, current_audio_file)
            self.voiceprint_cache[new_speaker_id] = [current_path]
            
            logger.bind(tag=TAG).info(f"新说话人: {new_speaker_id}")
            self.current_speaker_id = new_speaker_id
            self.current_speaker_start_time = time.time()


            # 清理临时文件
            try:
                os.remove(current_audio_file)
            except:
                pass

            return new_speaker_id
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"说话人识别失败: {e}")
            return None

    def get_all_speakers(self):
        """获取所有说话人ID"""
        return self.storage.get_all_speakers()

    def get_speaker_stats(self, speaker_id):
        """获取说话人统计信息"""
        return self.storage.get_speaker_stats(speaker_id)

    def delete_speaker(self, speaker_id):
        """删除说话人"""
        if speaker_id in self.voiceprint_cache:
            del self.voiceprint_cache[speaker_id]
        return self.storage.delete_speaker(speaker_id)

    def cleanup(self):
        """清理资源"""
        if self.current_speaker_id and self.current_speaker_start_time:
            duration = time.time() - self.current_speaker_start_time
            self.storage.update_speaker_stats(self.current_speaker_id, duration)
        
        # 清理临时目录
        try:
            for file in os.listdir(self.temp_dir):
                os.remove(os.path.join(self.temp_dir, file))
            os.rmdir(self.temp_dir)
        except:
            pass
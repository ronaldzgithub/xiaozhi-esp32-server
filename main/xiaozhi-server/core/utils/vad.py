from abc import ABC, abstractmethod
from config.logger import setup_logging
import opuslib_next
import time
import numpy as np
import torch

TAG = __name__
logger = setup_logging()

class VAD(ABC):
    @abstractmethod
    def is_vad(self, conn, data):
        """检测音频数据中的语音活动"""
        pass


class SileroVAD(VAD):
    def __init__(self, config):
        logger.bind(tag=TAG).info("SileroVAD", config)
        self.model, self.utils = torch.hub.load(repo_or_dir=config["model_dir"],
                                              source='local',
                                              model='silero_vad',
                                              force_reload=False)
        (get_speech_timestamps, _, _, _, _) = self.utils

        self.decoder = opuslib_next.Decoder(16000, 1)
        self.vad_threshold = config.get("threshold")
        self.silence_threshold_ms = config.get("min_silence_duration_ms")
        
        # 使用模型要求的固定样本数
        self.samples_per_chunk = 512  # SileroVAD要求16kHz采样率下使用512个样本
        self.audio_buffer = np.zeros(self.samples_per_chunk, dtype=np.float32)
        self.buffer_index = 0

    def is_vad(self, conn, opus_packet):
        try:
            pcm_frame = self.decoder.decode(opus_packet, 960)
            conn.client_audio_buffer += pcm_frame

            # 使用模型要求的固定样本数进行处理
            client_have_voice = False
            while len(conn.client_audio_buffer) >= self.samples_per_chunk * 2:
                # 提取处理块，确保样本数为512
                chunk = conn.client_audio_buffer[:self.samples_per_chunk * 2]
                conn.client_audio_buffer = conn.client_audio_buffer[self.samples_per_chunk * 2:]

                # 批量转换为张量
                audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                audio_float32 = audio_int16.astype(np.float32) / 32768.0
                
                # 确保音频数据形状正确
                if len(audio_float32) != self.samples_per_chunk:
                    logger.bind(tag=TAG).warning(f"音频数据长度不正确: {len(audio_float32)} != {self.samples_per_chunk}")
                    continue
                
                # 使用torch.no_grad()减少内存使用
                with torch.no_grad():
                    audio_tensor = torch.from_numpy(audio_float32).unsqueeze(0)  # 添加批次维度
                    speech_prob = self.model(audio_tensor, 16000).item()
                
                client_have_voice = speech_prob >= self.vad_threshold

                # 优化语音停止检测逻辑
                if conn.client_have_voice and not client_have_voice:
                    stop_duration = time.time() * 1000 - conn.client_have_voice_last_time
                    if stop_duration >= self.silence_threshold_ms:
                        conn.client_voice_stop = True
                        break  # 检测到语音停止，立即退出循环
                
                if client_have_voice:
                    conn.client_have_voice = True
                    conn.client_have_voice_last_time = time.time() * 1000

            return client_have_voice
            
        except opuslib_next.OpusError as e:
            logger.bind(tag=TAG).info(f"解码错误: {e}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error processing audio packet: {e}")
            logger.bind(tag=TAG).error(f"Error details: {str(e)}")
        return False


def create_instance(class_name, *args, **kwargs) -> VAD:
    # 获取类对象
    cls_map = {
        "SileroVAD": SileroVAD,
        # 可扩展其他SileroVAD实现
    }

    if cls := cls_map.get(class_name):
        return cls(*args, **kwargs)
    raise ValueError(f"不支持的SileroVAD类型: {class_name}")
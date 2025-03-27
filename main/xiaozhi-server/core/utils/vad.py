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

    def is_vad(self, conn, opus_packet):
        try:
            # 解码音频数据
            pcm_frame = self.decoder.decode(opus_packet, 960)
            if pcm_frame is None:
                logger.bind(tag=TAG).warning("Decoded frame is None")
                return False

            # 将新数据加入缓冲区
            conn.client_audio_buffer += pcm_frame

            # 处理缓冲区中的完整帧
            client_have_voice = False
            while len(conn.client_audio_buffer) >= 512 * 2:
                try:
                    # 提取前512个采样点（1024字节）
                    chunk = conn.client_audio_buffer[:512 * 2]
                    conn.client_audio_buffer = conn.client_audio_buffer[512 * 2:]

                    # 确保数据长度正确
                    if len(chunk) != 1024:  # 512 * 2 bytes
                        logger.bind(tag=TAG).warning(f"Invalid chunk length: {len(chunk)}")
                        continue

                    # 转换为模型需要的张量格式
                    audio_int16 = np.frombuffer(chunk, dtype=np.int16)
                    if len(audio_int16) != 512:
                        logger.bind(tag=TAG).warning(f"Invalid audio_int16 length: {len(audio_int16)}")
                        continue

                    audio_float32 = audio_int16.astype(np.float32) / 32768.0
                    audio_tensor = torch.from_numpy(audio_float32)

                    # 检测语音活动
                    speech_prob = self.model(audio_tensor, 16000).item()
                    client_have_voice = speech_prob >= self.vad_threshold

                    # 更新语音状态
                    if conn.client_have_voice and not client_have_voice:
                        stop_duration = time.time() * 1000 - conn.client_have_voice_last_time
                        if stop_duration >= self.silence_threshold_ms:
                            conn.client_voice_stop = True
                    
                    if client_have_voice:
                        conn.client_have_voice = True
                        conn.client_have_voice_last_time = time.time() * 1000

                except ValueError as ve:
                    logger.bind(tag=TAG).error(f"ValueError in audio processing: {ve}")
                    continue
                except Exception as e:
                    logger.bind(tag=TAG).error(f"Error processing audio chunk: {e}")
                    continue

            return client_have_voice

        except opuslib_next.OpusError as e:
            logger.bind(tag=TAG).error(f"Opus decoding error: {e}")
            return False
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error processing audio packet: {e}")
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
from config.logger import setup_logging
import json
import asyncio
import time
from core.utils.util import (
    remove_punctuation_and_length,
    get_string_no_punctuation_or_emoji,
)

TAG = __name__
logger = setup_logging()


async def sendAudioMessage(conn, audios, text, text_index=0):
    # 发送句子开始消息
    if text_index == conn.tts_first_text_index:
        logger.bind(tag=TAG).info(f"发送第一段语音: {text}")
    await send_tts_message(conn, "sentence_start", text)

    # 播放音频
    await sendAudio(conn, audios)

    await send_tts_message(conn, "sentence_end", text)

    # 发送结束消息（如果是最后一个文本）
    if conn.llm_finish_task and text_index == conn.tts_last_text_index:
        await send_tts_message(conn, "stop", None)
        if conn.close_after_chat:
            await conn.close()


# 播放音频
async def sendAudio(conn, audios):
    # 优化流控参数
    frame_duration = 60  # 帧时长（毫秒）
    start_time = time.perf_counter()
    play_position = 0
    
    # 增加预缓冲大小，提高流畅度
    pre_buffer = min(8, len(audios))  # 增加到8帧
    
    # 批量发送预缓冲数据，使用gather并行发送
    if pre_buffer > 0:
        pre_buffer_tasks = [conn.websocket.send(audios[i]) for i in range(pre_buffer)]
        await asyncio.gather(*pre_buffer_tasks)
    
    # 使用动态帧间隔，根据网络状况调整
    base_delay = frame_duration / 1000  # 基础延迟（秒）
    min_delay = base_delay * 0.7  # 降低最小延迟
    max_delay = base_delay * 1.1  # 降低最大延迟
    
    # 使用批量发送策略
    batch_size = 3  # 每批发送3帧
    for i in range(pre_buffer, len(audios), batch_size):
        if conn.client_abort:
            return
            
        # 获取当前批次
        batch_end = min(i + batch_size, len(audios))
        current_batch = audios[i:batch_end]
        
        # 计算动态延迟
        expected_time = start_time + (play_position / 1000)
        current_time = time.perf_counter()
        delay = expected_time - current_time
        
        # 根据网络状况动态调整延迟
        if delay > 0:
            # 如果延迟过大，使用最小延迟
            if delay > max_delay:
                delay = min_delay
            await asyncio.sleep(delay)
        
        # 批量发送音频数据
        batch_tasks = [conn.websocket.send(packet) for packet in current_batch]
        await asyncio.gather(*batch_tasks)
        
        # 更新播放位置
        play_position += frame_duration * len(current_batch)


async def send_tts_message(conn, state, text=None):
    """发送 TTS 状态消息"""
    message = {"type": "tts", "state": state, "session_id": conn.session_id}
    if text is not None:
        message["text"] = text

    # TTS播放结束
    if state == "stop":
        # 播放提示音
        tts_notify = conn.config.get("enable_stop_tts_notify", False)
        if tts_notify:
            stop_tts_notify_voice = conn.config.get(
                "stop_tts_notify_voice", "config/assets/tts_notify.mp3"
            )
            audios, duration = conn.tts.audio_to_opus_data(stop_tts_notify_voice)
            await sendAudio(conn, audios)
        # 清除服务端讲话状态
        conn.clearSpeakStatus()

    # 发送消息到客户端
    await conn.websocket.send(json.dumps(message))


async def send_stt_message(conn, text):
    """发送 STT 状态消息"""
    stt_text = get_string_no_punctuation_or_emoji(text)
    await conn.websocket.send(
        json.dumps({"type": "stt", "text": stt_text, "session_id": conn.session_id})
    )
    await conn.websocket.send(
        json.dumps(
            {
                "type": "llm",
                "text": "😊",
                "emotion": "happy",
                "session_id": conn.session_id,
            }
        )
    )
    await send_tts_message(conn, "start")

from config.logger import setup_logging
import time
from core.utils.util import remove_punctuation_and_length
from core.handle.sendAudioHandle import send_stt_message
from core.handle.intentHandler import handle_user_intent
import asyncio

from core.utils.dialogue import Message, Dialogue

TAG = __name__
logger = setup_logging()


async def handleAudioMessage(conn, audio):
    # 检查是否允许接收音频数据
    if not conn.asr_server_receive:
        logger.bind(tag=TAG).debug(f"前期数据处理中，暂停接收")
        return

    # 根据客户端监听模式决定是否有声音
    if conn.client_listen_mode == "auto":
        # 自动模式下，使用VAD检测是否有声音
        have_voice = conn.vad.is_vad(conn, audio)
    else:
        # 非自动模式下，直接使用客户端报告的有无声音信息
        have_voice = conn.client_have_voice

    # 优化无声音处理逻辑
    if not have_voice and not conn.client_have_voice:
        await no_voice_close_connect(conn)
        # 只保留最新的3帧音频内容，进一步减少内存使用
        conn.asr_audio.append(audio)
        conn.asr_audio = conn.asr_audio[-3:]
        return

    conn.client_no_voice_last_time = 0.0
    conn.asr_audio.append(audio)

    # 优化语音停止处理逻辑
    if conn.client_voice_stop:
        conn.client_abort = False
        conn.asr_server_receive = False

        # 优化音频长度判断
        if len(conn.asr_audio) < 8:  # 进一步降低最小音频长度要求
            conn.asr_server_receive = True
        else:
            # 创建任务列表
            tasks = []

            start_time = time.time()

            conn.prepare_session()
            
            # 添加语音识别任务
            asr_task = asyncio.create_task(conn.asr.speech_to_text(conn.asr_audio, conn.session_id))
            tasks.append(asr_task)

            # 添加说话人识别任务
            if conn.private_config and False:
                speaker_task = asyncio.create_task(conn.voiceprint.identify_speaker(conn.asr_audio, conn.headers.get('device_id')))
                tasks.append(speaker_task)

                speaker_id = await speaker_task
                logger.bind(tag=TAG).info(f"识别说话人: {speaker_id} 用时: {time.time() - start_time}秒")
            else:
                speaker_id = 'speaker_0'

            # 等待语音识别完成
            text, file_path = await asr_task
            logger.bind(tag=TAG).info(f"识别文本: {text} 用时: {time.time() - start_time}秒")
            
            text_len, _ = remove_punctuation_and_length(text)
            if text_len > 0:
                
                # 添加音频消息处理任务
                audio_task = asyncio.create_task(conn.handle_audio_message(conn.asr_audio, text, speaker_id))
                tasks.append(audio_task)
                
                # 添加记忆系统任务
                if conn.memory:
                    memory_task = asyncio.create_task(conn.memory.add_memory(
                        text,
                        conn.dialogue.get_metadata(),
                        speaker_id
                    ))
                    tasks.append(memory_task)
                
                logger.bind(tag=TAG).info(f"生成回复{text}")
                
                # 添加对话任务
                chat_task = asyncio.create_task(startToChat(conn, text, None, speaker_id))
                tasks.append(chat_task)
                
                # 等待所有任务完成
                await asyncio.gather(*tasks)
            else:
                conn.asr_server_receive = True

        conn.asr_audio.clear()
        conn.reset_vad_states()



async def startToChat(conn, text, emotion=None, speaker_id=None):
    # 首先进行意图分析
    intent_handled = await handle_user_intent(conn, text)

    if intent_handled:
        # 如果意图已被处理，不再进行聊天
        conn.asr_server_receive = True
        return

    # 意图未被处理，继续常规聊天流程
    await send_stt_message(conn, text)
    if conn.use_function_call_mode:
        # 使用executor提交任务
        conn.executor.submit(conn.chat_with_function_calling,text, False, emotion, speaker_id)
    else:
        def chat_and_release():
            try:
                conn.chat(text, emotion, speaker_id)
            finally:
                # 使用run_coroutine_threadsafe来调用异步函数
                asyncio.run_coroutine_threadsafe(conn.release_session(), asyncio.get_event_loop())
        
        # 使用executor提交任务
        conn.executor.submit(chat_and_release)

async def no_voice_close_connect(conn):
    if conn.client_no_voice_last_time == 0.0:
        conn.client_no_voice_last_time = time.time() * 1000
    else:
        no_voice_time = time.time() * 1000 - conn.client_no_voice_last_time
        close_connection_no_voice_time = conn.config.get(
            "close_connection_no_voice_time", 120
        )
        if (
            not conn.close_after_chat
            and no_voice_time > 1000 * close_connection_no_voice_time
        ):
            conn.close_after_chat = True
            conn.client_abort = False
            conn.asr_server_receive = False
            prompt = "请你以'时间过得真快'未来头，用富有感情、依依不舍的话来结束这场对话吧。"
            await startToChat(conn, prompt, None, None)



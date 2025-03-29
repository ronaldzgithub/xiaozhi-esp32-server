from config.logger import setup_logging
import time
from core.utils.util import remove_punctuation_and_length
from core.handle.sendAudioHandle import send_stt_message
from core.handle.intentHandler import handle_user_intent

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

    # 如果本次没有声音，本段也没声音，就把声音丢弃了
    if have_voice == False and conn.client_have_voice == False:
        await no_voice_close_connect(conn)
        conn.asr_audio.append(audio)
        conn.asr_audio = conn.asr_audio[-5:]  # 保留最新的5帧音频内容，解决ASR句首丢字问题
        return
    conn.client_no_voice_last_time = 0.0
    conn.asr_audio.append(audio)
    # 如果本段有声音，且已经停止了
    if conn.client_voice_stop:
        conn.client_abort = False
        conn.asr_server_receive = False
        # 音频太短了，无法识别
        if len(conn.asr_audio) < 10:
            conn.asr_server_receive = True
        else:
            try:
                # 识别说话人
                speaker_id = None
                emotion = None
                

                # 语音识别
                text, file_path = await conn.asr.speech_to_text(conn.asr_audio, conn.session_id)
                logger.bind(tag=TAG).info(f"识别文本: {text}")
                text_len, _ = remove_punctuation_and_length(text)
                if text_len < 0:
                    logger.bind(tag=TAG).info(f"语音识别失败")
                    conn.asr_server_receive = True
                    raise Exception("语音识别失败")
                
                if conn.voiceprint:
                    speaker_id = await conn.voiceprint.identify_speaker(conn.asr_audio)
                    logger.bind(tag=TAG).info(f"识别到说话人: {speaker_id}")
                logger.bind(tag=TAG).info(f"识别说话人")

                # 情感识别
                emotion = None
                if conn.emotion:
                    emotion = await conn.emotion.detect_emotion(conn.asr_audio, text)
                    logger.bind(tag=TAG).info(f"识别到情感: {emotion}")

                await conn.handle_audio_message(conn.asr_audio,text,speaker_id)

                # 记忆系统处理
                if conn.memory:
                    # 添加当前对话到记忆，包含说话人信息
                    await conn.memory.add_memory(
                        conn.dialogue.get_llm_dialogue(),
                        conn.dialogue.get_metadata(),
                        speaker_id
                    )
                logger.bind(tag=TAG).info(f"记忆系统处理")

                

                logger.bind(tag=TAG).info(f"生成回复{text}")
                await startToChat(conn, text, emotion, speaker_id)
                    
                

            except Exception as e:
                logger.bind(tag=TAG).error(f"处理音频消息失败: {e}")
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
        # 使用支持function calling的聊天方法
        conn.executor.submit(conn.chat_with_function_calling, text, False,emotion, speaker_id)
    else:
        conn.executor.submit(conn.chat, text, emotion, speaker_id)


async def no_voice_close_connect(conn):
    if conn.client_no_voice_last_time == 0.0:
        conn.client_no_voice_last_time = time.time() * 1000
    else:
        no_voice_time = time.time() * 1000 - conn.client_no_voice_last_time
        close_connection_no_voice_time = conn.config.get("close_connection_no_voice_time", 120)
        if not conn.close_after_chat and no_voice_time > 1000 * close_connection_no_voice_time:
            conn.close_after_chat = True
            conn.client_abort = False
            conn.asr_server_receive = False
            prompt = "请你以'时间过得真快'未来头，用富有感情、依依不舍的话来结束这场对话吧。"
            await startToChat(conn, prompt, None, None)



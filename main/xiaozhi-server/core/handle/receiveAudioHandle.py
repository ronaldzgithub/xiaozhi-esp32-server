from config.logger import setup_logging
import time
from core.utils.util import remove_punctuation_and_length
from core.handle.sendAudioHandle import send_stt_message
from core.handle.intentHandler import handle_user_intent

from core.utils.dialogue import Message, Dialogue

TAG = __name__
logger = setup_logging()


async def handleAudioMessage(conn, audio):
    if not conn.asr_server_receive:
        logger.bind(tag=TAG).debug(f"前期数据处理中，暂停接收")
        return
    if conn.client_listen_mode == "auto":
        have_voice = conn.vad.is_vad(conn, audio)
    else:
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
                if conn.voiceprint:
                    speaker_id = await conn.voiceprint.identify_speaker(conn.asr_audio)
                    logger.bind(tag=TAG).info(f"识别到说话人: {speaker_id}")
                logger.bind(tag=TAG).info(f"识别说话人")

                # 语音识别
                text, file_path = await conn.asr.speech_to_text(conn.asr_audio, conn.session_id)
                logger.bind(tag=TAG).info(f"识别文本: {text}")
                text_len, _ = remove_punctuation_and_length(text)
                if text_len < 0:
                    logger.bind(tag=TAG).info(f"语音识别失败")
                    conn.asr_server_receive = True
                    raise Exception("语音识别失败")
                
                # 情感识别
                emotion = None
                if conn.emotion:
                    emotion = await conn.emotion.detect_emotion(conn.asr_audio, text)
                    logger.bind(tag=TAG).info(f"识别到情感: {emotion}")

                # 处理角色创建流程
                if conn.is_creating_role and conn.role_wizard:
                    response = conn.role_wizard.process_answer(text)
                    if response:
                        await conn.send_text_response(response)
                        if "角色创建成功" in response:
                            conn.is_creating_role = False
                        return
                logger.bind(tag=TAG).info(f"角色创建流程")

                # 处理管理员命令
                if conn.private_config and conn.private_config.is_in_admin_mode():
                    if "增加一个角色" in text or "创建一个角色" in text:
                        conn.is_creating_role = True
                        response = conn.role_wizard.start_creation()
                        await conn.send_text_response(response)
                        return
                logger.bind(tag=TAG).info(f"管理员命令")

                # 处理管理员声纹设置和验证
                if conn.private_config:
                    if not conn.private_config.is_admin_voiceprint_set():
                        # 如果是第一次连接，请求设置管理员声纹
                        if text.lower() in ["好的", "可以", "确认"]:
                            # 提取声纹特征
                            voiceprint = await conn.voiceprint.extract_voiceprint(audio)
                            if voiceprint is not None:
                                conn.private_config.set_admin_voiceprint(voiceprint)
                                response = "管理员声纹已设置完成。从现在开始，只有您的声音才能进行管理员操作。"
                                await conn.send_text_response(response)
                                return
                        else:
                            response = "您是这个设备的第一位使用者，您将被设置为系统管理员。请说'好的'来确认。"
                            await conn.send_text_response(response)
                            return
                    else:
                        # 验证是否为管理员声纹
                        voiceprint = await conn.voiceprint.extract_voiceprint(audio)
                        if voiceprint is not None and conn.private_config.verify_admin_voiceprint(voiceprint):
                            conn.private_config.enter_admin_mode()
                            logger.bind(tag=TAG).info("进入管理员模式")
                            
                logger.bind(tag=TAG).info(f"管理员声纹设置和验证")

                # 记忆系统处理
                if conn.memory:
                    # 添加当前对话到记忆，包含说话人信息
                    conn.memory.add_memory(
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


async def startToChat(conn, text, emotion, speaker_id):
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
        conn.executor.submit(conn.chat_with_function_calling, text)
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



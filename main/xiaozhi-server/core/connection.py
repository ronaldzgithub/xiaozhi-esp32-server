from datetime import datetime
import os
import json
import uuid
import time
import queue
import asyncio
import traceback
import re

import threading
import websockets
from typing import Dict, Any
from plugins_func.loadplugins import auto_import_modules
from config.logger import setup_logging
from core.utils.dialogue import Message, Dialogue
from core.handle.textHandle import handleTextMessage
from core.utils.util import get_string_no_punctuation_or_emoji, extract_json_from_string, get_ip_info
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from core.handle.sendAudioHandle import sendAudioMessage,send_stt_message
from core.handle.receiveAudioHandle import handleAudioMessage
from core.handle.functionHandler import FunctionHandler
from plugins_func.register import Action, ActionResponse
from config.private_config import PrivateConfig
from core.auth import AuthMiddleware, AuthenticationError
from core.utils.auth_code_gen import AuthCodeGenerator
from core.mcp.manager import MCPManager
from core.performance_monitor import PerformanceMonitor

TAG = __name__

auto_import_modules('plugins_func.functions')


class TTSException(RuntimeError):
    pass


class ConnectionHandler:
    def __init__(self, config: Dict[str, Any], _vad, _asr, _llm, _tts, _memory, _intent):
        self.config = config
        self.logger = setup_logging()
        self.auth = AuthMiddleware(config)
        self.proactive_check_task = None  # 添加主动对话检查任务

        # 使用线程池预初始化TTS服务
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        # 初始化性能监控
        self.performance_monitor = PerformanceMonitor()
        
        # 添加TTS预加载队列
        self.tts_preload_queue = asyncio.Queue(maxsize=5)
        self.tts_preload_task = None

        

        self.websocket = None
        self.headers = None
        self.client_ip = None
        self.client_ip_info = {}
        self.session_id = None
        self.prompt = None
        self.welcome_msg = None

        # 客户端状态相关
        self.client_abort = False
        self.client_listen_mode = "auto"

        # 线程任务相关
        self.loop = asyncio.get_event_loop()
        self.stop_event = threading.Event()
        self.audio_play_queue = queue.Queue()

        # 依赖的组件
        self.vad = _vad
        self.asr = _asr
        self.llm = _llm
        self.tts = _tts  # TTSPool实例
        self.memory = _memory
        self.intent = _intent


        # vad相关变量
        self.client_audio_buffer = bytes()
        self.client_have_voice = False
        self.client_have_voice_last_time = 0.0
        self.client_no_voice_last_time = 0.0
        self.client_voice_stop = False

        # asr相关变量
        self.asr_audio = []
        self.asr_server_receive = True

        # llm相关变量
        self.llm_finish_task = False
        self.dialogue = Dialogue()

        # tts相关变量
        self.tts_first_text_index = -1
        self.tts_last_text_index = -1

        # iot相关变量
        self.iot_descriptors = {}

        self.cmd_exit = self.config["CMD_exit"]
        self.max_cmd_length = 0
        for cmd in self.cmd_exit:
            if len(cmd) > self.max_cmd_length:
                self.max_cmd_length = len(cmd)

        self.private_config = None
        self.auth_code_gen = AuthCodeGenerator.get_instance()
        self.is_device_verified = False  # 添加设备验证状态标志
        self.close_after_chat = False  # 是否在聊天结束后关闭连接
        self.use_function_call_mode = False
        if self.config["selected_module"]["Intent"] == 'function_call':
            self.use_function_call_mode = True
        
        self.mcp_manager = MCPManager(self)

        # 添加角色管理
        try:
            from core.providers.role.role_manager import RoleManager
            from core.providers.role.role_wizard import RoleWizard
            self.role_manager = RoleManager(config)
            self.role_wizard = RoleWizard(self.role_manager)
            self.is_creating_role = False
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"角色管理模块初始化失败: {e}")
            self.role_manager = None
            self.role_wizard = None
            self.is_creating_role = False

        # 添加家庭成员管理
        try:
            from core.providers.family.family_manager import FamilyManager
            from core.providers.family.family_wizard import FamilyMemberWizard
            self.family_manager = FamilyManager(config)
            self.family_wizard = FamilyMemberWizard(self.family_manager)
            self.is_adding_family_member = False
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"家庭成员管理模块初始化失败: {e}")
            self.family_manager = None
            self.family_wizard = None
            self.is_adding_family_member = False



        """# 添加情感识别模块
        emotion_cls_name = self.config["selected_module"].get("Emotion", "lightweight")
        has_emotion_cfg = self.config.get("Emotion") and emotion_cls_name in self.config["Emotion"]
        emotion_cfg = self.config["Emotion"][emotion_cls_name] if has_emotion_cfg else {}
        
        try:
            from core.providers.emotion.lightweight import EmotionProvider
            self.emotion = EmotionProvider(emotion_cfg)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"情感识别模块初始化失败: {e}")
            self.emotion = None"""

        # 添加主动对话模块
        proactive_cls_name = self.config["selected_module"].get("Proactive", "lightweight")
        has_proactive_cfg = self.config.get("Proactive") and proactive_cls_name in self.config["Proactive"]
        proactive_cfg = self.config["Proactive"][proactive_cls_name] if has_proactive_cfg else {}
        
        try:
            from core.providers.proactive.lightweight import ProactiveDialogueManager
            self.proactive = ProactiveDialogueManager(proactive_cfg)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"主动对话模块初始化失败: {e}")
            self.proactive = None

        # 添加声纹识别模块
        voiceprint_cls_name = self.config["selected_module"].get("Voiceprint", "lightweight")
        has_voiceprint_cfg = self.config.get("Voiceprint") and voiceprint_cls_name in self.config["Voiceprint"]
        voiceprint_cfg = self.config["Voiceprint"][voiceprint_cls_name] if has_voiceprint_cfg else {}
        
        try:
            from core.providers.voiceprint.lightweight import VoiceprintProvider
            self.voiceprint = VoiceprintProvider(voiceprint_cfg)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"声纹识别模块初始化失败: {e}")
            self.voiceprint = None

    async def handle_connection(self, ws):
        try:
            # 获取并验证headers
            self.headers = dict(ws.request.headers)
            # 获取客户端ip地址
            self.client_ip = ws.remote_address[0]
            self.logger.bind(tag=TAG).info(f"{self.client_ip} conn - Headers: {self.headers}")

            # 进行认证
            await self.auth.authenticate(self.headers)
            device_id = self.headers.get("device-id", None)

            # 认证通过,继续处理
            self.websocket = ws
            self.session_id = str(uuid.uuid4())

            # 设置当前会话ID
            self.tts.current_session_id = self.session_id

            self.welcome_msg = self.config["xiaozhi"]
            self.welcome_msg["session_id"] = self.session_id
            await self.websocket.send(json.dumps(self.welcome_msg))
            # Load private configuration if device_id is provided
            bUsePrivateConfig = self.config.get("use_private_config", False)
            self.logger.bind(tag=TAG).info(f"bUsePrivateConfig: {bUsePrivateConfig}, device_id: {device_id}")
            if bUsePrivateConfig and device_id:
                try:
                    self.private_config = PrivateConfig(device_id, self.config, self.auth_code_gen)
                    await self.private_config.load_or_create()
                    # 判断是否已经绑定
                    owner = self.private_config.get_owner()
                    self.is_device_verified = owner is not None

                    if self.is_device_verified:
                        await self.private_config.update_last_chat_time()
                    else:
                        if self.voiceprint:
                            # 对于新设备，等待第一个声纹并设置为管理员
                            self.logger.bind(tag=TAG).info("等待第一个声纹作为管理员...")
                            # 设置标志，表示需要等待管理员声纹
                            self.private_config.waiting_for_admin_voiceprint = True

                    llm, tts = self.private_config.create_private_instances()
                    if all([llm, tts]):
                        self.llm = llm
                        self.tts = tts
                        self.tts.set_audio_play_queue(self.audio_play_queue)
                        self.logger.bind(tag=TAG).info(f"Loaded private config and instances for device {device_id}")
                    else:
                        self.logger.bind(tag=TAG).error(f"Failed to create instances for device {device_id}")
                        self.private_config = None
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"Error initializing private config: {e}")
                    self.private_config = None
                    raise

            
            """加载记忆"""
            roles = self.config.get("roles", [])
            device_id = self.headers.get("device-id", None)
            #load 最近的一个role
            self.memory.init_memory(device_id, None, self.llm)
            #如果没有记录这个role，则使用默认的role
            if self.memory.role_id is None:
                self.memory.set_role_id(roles[0]["name"])

            self.switch_role(self.memory.role_id)

            # 异步初始化
            self.executor.submit(self._initialize_components)
            """# tts 消化线程
            self.tts_priority_thread = threading.Thread(target=self._tts_priority_thread, daemon=True)
            self.tts_priority_thread.start()"""

            # 音频播放 消化线程
            self.audio_play_priority_thread = threading.Thread(target=self._audio_play_priority_thread, daemon=True)
            self.audio_play_priority_thread.start()


             # 音频播放 消化线程
            self.proactive_thread = threading.Thread(target=self.start_proactive_check, daemon=True)
            self.proactive_thread.start()

            # 启动主动对话检查任务
            self.proactive_check_task = asyncio.create_task(self.start_proactive_check())
            
            try:
                async for message in self.websocket:
                    await self._route_message(message)
            except websockets.exceptions.ConnectionClosed:
                self.logger.bind(tag=TAG).info("客户端断开连接")
            finally:
                # 取消主动对话检查任务
                if self.proactive_check_task:
                    self.proactive_check_task.cancel()
                    try:
                        await self.proactive_check_task
                    except asyncio.CancelledError:
                        pass

        except AuthenticationError as e:
            self.logger.bind(tag=TAG).error(f"Authentication failed: {str(e)}")
            return
        except Exception as e:
            stack_trace = traceback.format_exc()
            self.logger.bind(tag=TAG).error(f"Connection error: {str(e)}-{stack_trace}")
            return
        finally:
            await self.memory.save_memory(self.dialogue.dialogue)
            await self.close(ws)

    async def _route_message(self, message):
        """消息路由"""
        if isinstance(message, str):
            await handleTextMessage(self, message)
        elif isinstance(message, bytes):
            await handleAudioMessage(self, message)

    def prepare_session(self):
        """准备会话, 获取TTS连接"""
        if hasattr(self.tts, 'acquire'):
            self.tts.acquire(self.session_id, self.audio_play_queue, self.voice)

    async def release_session(self):
        """释放会话, 释放TTS连接"""
        if hasattr(self.tts, 'release'):
            await self.tts.release(self.session_id)

    def _initialize_components(self):
        """加载提示词"""
        roles = self.config.get("roles", [])
                
        self.prompt = roles[0]["prompt"]
        self.memory.set_r = roles[0]["name"]
        self.memory.set_role_id(roles[0]["name"])

        if self.private_config:
            # 检查是否有保存的角色设置
            current_role = self.private_config.private_config.get("current_role")
            if current_role:
                for role in roles:
                    if role["name"] == current_role:
                        self.prompt = role["prompt"]
                        break
            else:
                self.prompt = self.private_config.private_config.get("prompt", self.prompt)
        self.dialogue.put(Message(role="system", content=self.prompt))

        """加载插件"""
        self.func_handler = FunctionHandler(self)

            
        """为意图识别设置LLM，优先使用专用LLM"""
        # 检查是否配置了专用的意图识别LLM
        intent_llm_name = self.config["Intent"]["intent_llm"]["llm"]
        
        # 记录开始初始化意图识别LLM的时间
        intent_llm_init_start = time.time()
        
        if not self.use_function_call_mode and intent_llm_name and intent_llm_name in self.config["LLM"]:
            # 如果配置了专用LLM，则创建独立的LLM实例
            from core.utils import llm as llm_utils
            intent_llm_config = self.config["LLM"][intent_llm_name]
            intent_llm_type = intent_llm_config.get("type", intent_llm_name)
            intent_llm = llm_utils.create_instance(intent_llm_type, intent_llm_config)
            self.logger.bind(tag=TAG).info(f"为意图识别创建了专用LLM: {intent_llm_name}, 类型: {intent_llm_type}")
            
            self.intent.set_llm(intent_llm)
        else:
            # 否则使用主LLM
            self.intent.set_llm(self.llm)
            self.logger.bind(tag=TAG).info("意图识别使用主LLM")
            
        # 记录意图识别LLM初始化耗时
        intent_llm_init_time = time.time() - intent_llm_init_start
        self.logger.bind(tag=TAG).info(f"意图识别LLM初始化完成，耗时: {intent_llm_init_time:.4f}秒")

        """加载位置信息"""
        self.client_ip_info = get_ip_info(self.client_ip)
        if self.client_ip_info is not None and "city" in self.client_ip_info:
            self.logger.bind(tag=TAG).info(f"Client ip info: {self.client_ip_info}")
            self.prompt = self.prompt + f"\nuser location:{self.client_ip_info}"
            self.dialogue.update_system_message(self.prompt)

        """加载MCP工具"""
        asyncio.run_coroutine_threadsafe(self.mcp_manager.initialize_servers(), self.loop)

    def change_system_prompt(self, prompt):
        self.prompt = prompt
        # 找到原来的role==system，替换原来的系统提示
        for m in self.dialogue.dialogue:
            if m.role == "system":
                m.content = prompt

    def _check_and_broadcast_auth_code(self):
        """检查设备绑定状态并广播认证码"""
        if not self.private_config.get_owner():
            auth_code = self.private_config.get_auth_code()
            if auth_code:
                # 发送验证码语音提示
                text = f"请在后台输入验证码：{' '.join(auth_code)}"
                self.recode_first_last_text(text)
                self.send_full_audio_message(text)
            return False
        return True

    def isNeedAuth(self):
        bUsePrivateConfig = self.config.get("use_private_config", False)
        if not bUsePrivateConfig:
            # 如果不使用私有配置，就不需要验证
            return False
        return not self.is_device_verified

    def chat(self, query, emotion=None, speaker_id=None):
        if self.isNeedAuth():
            self.llm_finish_task = True
            self._check_and_broadcast_auth_code()
            return "请先完成设备验证。"

        # 更新最后交互时间
        if self.proactive:
            current_time = time.time()
            self.proactive.update_last_interaction(current_time)

        self.dialogue.put(Message(role="user", content=query))

        response_message = []
        processed_chars = 0  # 跟踪已处理的字符位置
        try:
            start_time = time.time()
            # 使用带记忆的对话
            memory_str = self.memory.query_memory(query)
            # 获取当前说话人的记忆
            speaker_memory = self.memory.get_memory(speaker_id)
            memory_str+=(speaker_memory)

            self.logger.bind(tag=TAG).debug(f"记忆内容: {memory_str}")
            llm_responses = self.llm.response(
                self.session_id,
                self.dialogue.get_llm_dialogue_with_memory(memory_str)
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 处理出错 {query}: {e}")
            return "抱歉，我现在无法正常回答，请稍后再试。"

        self.llm_finish_task = False
        text_index = 0
        for content in llm_responses:
            response_message.append(content)
            if self.client_abort:
                break

            end_time = time.time()
            self.logger.bind(tag=TAG).debug(f"大模型返回时间: {end_time - start_time} 秒, 生成token={content}")

            # 合并当前全部文本并处理未分割部分
            full_text = "".join(response_message)
            current_text = full_text[processed_chars:]  # 从未处理的位置开始

            # 查找最后一个有效标点
            punctuations = ("。", "？", "！", "；", "：", ".", "?", "!", ";", ":")
            last_punct_pos = -1
            for punct in punctuations:
                pos = current_text.rfind(punct)
                if pos > last_punct_pos:
                    last_punct_pos = pos

            # 找到分割点则处理
            if last_punct_pos != -1:
                segment_text_raw = current_text[:last_punct_pos + 1]
                segment_text = get_string_no_punctuation_or_emoji(segment_text_raw)
                if segment_text:
                    text_index += 1
                    self.recode_first_last_text(segment_text, text_index)
                    # 使用 ByteDance TTS provider 生成语音
                    self.speak_and_play(segment_text, text_index)

                    processed_chars += len(segment_text_raw)  # 更新已处理字符位置

        # 处理最后剩余的文本
        full_text = "".join(response_message)
        remaining_text = full_text[processed_chars:]
        if remaining_text:
            segment_text = get_string_no_punctuation_or_emoji(remaining_text)
            if segment_text:
                text_index += 1
                self.recode_first_last_text(segment_text, text_index)
                # 使用 ByteDance TTS provider 生成语音
                self.speak_and_play(segment_text, text_index)

        self.llm_finish_task = True
        response_text = "".join(response_message)
        self.dialogue.put(Message(role="assistant", content=response_text,metadata={
                    "speaker_id": speaker_id,
                    "emotion": emotion,
                    "timestamp": time.time(),
                    "is_admin": self.private_config.is_in_admin_mode() if self.private_config else False
                }))

        
        self.logger.bind(tag=TAG).debug(json.dumps(self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False))
        return response_text

    async def _update_interests_and_check_proactive(self):
        """更新用户兴趣并检查是否需要主动对话"""
        try:
            await self.proactive.update_user_interests(self.dialogue.dialogue)
            await self.check_proactive_dialogue()
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"更新兴趣和检查主动对话失败: {e}")

    def chat_with_function_calling(self, query, tool_call=False, emotion=None, speaker_id=None):
        self.logger.bind(tag=TAG).debug(f"Chat with function calling start: {query}")
        
        # 开始性能监控
        self.performance_monitor.start_request()
        
        """if self.isNeedAuth():
            self.llm_finish_task = True
            future = asyncio.run_coroutine_threadsafe(self._check_and_broadcast_auth_code(), self.loop)
            future.result()
            return True"""

       

        if not tool_call:
            self.dialogue.put(Message(role="user", content=query,  metadata={
                    "speaker_id": speaker_id,
                    "emotion": emotion,
                    "timestamp": time.time(),
                    "is_admin": self.private_config.is_in_admin_mode() if self.private_config else False
                }))

        # 并行获取记忆
        memory_future = asyncio.run_coroutine_threadsafe(self.memory.query_memory(query), self.loop)
        speaker_future = asyncio.run_coroutine_threadsafe(self.memory.get_memory(speaker_id), self.loop)
        
        memory_str = memory_future.result()
        speaker_memory = speaker_future.result()
        memory_str += speaker_memory

        # 获取函数定义
        functions = None
        if hasattr(self, 'func_handler'):
            functions = self.func_handler.get_functions()

        try:
            # 开始LLM处理计时
            self.performance_monitor.start_llm()
            start_time = time.time()
            llm_responses = self.llm.response_with_functions(
                self.session_id,
                self.dialogue.get_llm_dialogue_with_memory(memory_str),
                functions=functions
            )
            self.performance_monitor.end_llm()

            self.llm_finish_task = False
            text_index = 0
            processed_chars = 0
            response_message = []
            tool_call_flag = False
            function_name = None
            function_id = None
            function_arguments = ""
            content_arguments = ""

            # 使用正则表达式优化标点查找
            punctuations_pattern = re.compile(r'[,，；。？！；：、.;n!~～\?]')

            """# 启动TTS预加载任务
            if self.tts_preload_task is None:
                self.tts_preload_task = asyncio.run_coroutine_threadsafe(self._tts_preload_worker(), self.loop)"""
            
            for response in llm_responses:
                content, tools_call = response
                if content is not None and len(content) > 0:
                    if not tool_call_flag:
                        response_message.append(content)
                        
                        if self.client_abort:
                            break

                        # 处理文本分段和TTS
                        full_text = "".join(response_message)
                        current_text = full_text[processed_chars:]
                        
                        # 查找最后一个有效标点
                        punctuations = ("。","，", "？", "！", "；", "：", ".", ",","?", "!", ";", ":")
                        last_punct_pos = -1
                        for punct in punctuations:
                            pos = current_text.rfind(punct)
                            if pos > last_punct_pos:
                                last_punct_pos = pos

                        if last_punct_pos != -1:
                            segment_text_raw = current_text[:last_punct_pos + 1]
                            segment_text = get_string_no_punctuation_or_emoji(segment_text_raw)
                            
                            if segment_text:
                                text_index += 1
                                # 如果还没有说出第一句话，则说出前4个字或第一个标点符号之前的文本,这是为了加速响应
                                if self.tts_first_text_index == -1:

                                    first_pause_pos = 10

                                    wordstopause = ['我','你','他','的','是','她','它','有']
                                    pause_positions = []
                                    for word in wordstopause:
                                        pos = segment_text.find(word)
                                        if pos != -1:
                                            pause_positions.append(pos)
                                    if pause_positions:
                                        first_pause_pos = max(6,min(max(pause_positions), first_pause_pos))
                                    
                                    if last_punct_pos < first_pause_pos:
                                        first_pause_pos = last_punct_pos
                                
                                    first_text = segment_text[:first_pause_pos]
                                    self.speak_and_play(first_text, text_index, session_id=self.session_id)
                                    self.tts_first_text_index = text_index
                                    segment_text = segment_text[len(first_text):]
                                    text_index += 1

                                self.recode_first_last_text(segment_text, text_index)
                                self.speak_and_play(segment_text, text_index, session_id=self.session_id)

                                processed_chars += len(segment_text_raw)
                                
                if tools_call is not None:
                    tool_call_flag = True
                    if tools_call[0].id is not None:
                        function_id = tools_call[0].id
                    if tools_call[0].function.name is not None:
                        function_name = tools_call[0].function.name
                    if tools_call[0].function.arguments is not None:
                        function_arguments += tools_call[0].function.arguments

                if content is not None and len(content) > 0 and tool_call_flag:
                    content_arguments += content

            # 处理剩余文本
            full_text = "".join(response_message)
            remaining_text = full_text[processed_chars:]
            if remaining_text:
                segment_text = get_string_no_punctuation_or_emoji(remaining_text)
                if segment_text:
                    text_index += 1
                    self.recode_first_last_text(segment_text, text_index)
                    self.speak_and_play(segment_text, text_index, session_id=self.session_id)

            # 处理函数调用
            if tool_call_flag:
                self.current_speaker_id = speaker_id
                self._handle_tool_call(function_name, function_id, function_arguments, content_arguments, text_index)

            # 存储对话内容
            if len(response_message) > 0:
                self.dialogue.put(Message(role="assistant", content="".join(response_message), metadata={
                    "speaker_id": speaker_id,
                    "emotion": emotion,
                    "timestamp": time.time(),
                    "is_admin": self.private_config.is_in_admin_mode() if self.private_config else False
                }))

            self.llm_finish_task = True
            self.logger.bind(tag=TAG).debug(json.dumps(self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False))

            # 结束性能监控
            self.performance_monitor.end_request(success=True)
            # 记录性能指标
            self.performance_monitor.log_metrics()


            # 更新最后交互时间
            if self.proactive:
                self.proactive.update_last_interaction( time.time())

            return full_text

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 处理出错 {query}: {e}")
            # 记录错误
            self.performance_monitor.end_request(success=False)
            return None

    def _handle_tool_call(self, function_name, function_id, function_arguments, content_arguments, text_index):
        """处理工具调用"""
        bHasError = False
        if function_id is None:
            a = extract_json_from_string(content_arguments)
            if a is not None:
                try:
                    content_arguments_json = json.loads(a)
                    function_name = content_arguments_json["name"]
                    function_arguments = json.dumps(content_arguments_json["arguments"], ensure_ascii=False)
                    function_id = str(uuid.uuid4().hex)
                except Exception as e:
                    bHasError = True
                    self.logger.bind(tag=TAG).error(f"function call error: {content_arguments}")
            else:
                bHasError = True
                self.logger.bind(tag=TAG).error(f"function call error: {content_arguments}")

        if not bHasError:
            function_arguments = json.loads(function_arguments)
            function_call_data = {
                "name": function_name,
                "id": function_id,
                "arguments": function_arguments
            }

            self.logger.bind(tag=TAG).info(f"Processing tool call for {function_name} with arguments: {function_arguments}")
            
            if self.mcp_manager.is_mcp_tool(function_name):
                result = self._handle_mcp_tool_call(function_call_data)
            else:
                result = self.func_handler.handle_llm_function_call(self, function_call_data)
                
            self._handle_function_result(result, function_call_data, text_index + 1)

    def _handle_mcp_tool_call(self, function_call_data):
        function_arguments = function_call_data["arguments"]
        function_name = function_call_data["name"]
        try:
            args_dict = function_arguments
            if isinstance(function_arguments, str):
                try:
                    args_dict = json.loads(function_arguments)
                except json.JSONDecodeError:
                    self.logger.bind(tag=TAG).error(f"无法解析 function_arguments: {function_arguments}")
                    return ActionResponse(action=Action.REQLLM, result="参数解析失败", response="")
                    
            tool_result = asyncio.run_coroutine_threadsafe(self.mcp_manager.execute_tool(
                function_name,
                args_dict
            ), self.loop).result()
            # meta=None content=[TextContent(type='text', text='北京当前天气:\n温度: 21°C\n天气: 晴\n湿度: 6%\n风向: 西北 风\n风力等级: 5级', annotations=None)] isError=False
            content_text = ""
            if tool_result is not None and tool_result.content is not None:
                for content in tool_result.content:
                    content_type = content.type
                    if content_type == "text":
                        content_text = content.text
                    elif content_type == "image":
                        pass
            
            if len(content_text) > 0:
                return ActionResponse(action=Action.REQLLM, result=content_text, response="")
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"MCP工具调用错误: {e}")
            return ActionResponse(action=Action.REQLLM, result="工具调用出错", response="")

        return ActionResponse(action=Action.REQLLM, result="工具调用出错", response="")
            

    def _handle_function_result(self, result, function_call_data, text_index):
        if result.action == Action.RESPONSE:  # 直接回复前端
            text = result.response
            self.recode_first_last_text(text, text_index)
            future = self.executor.submit(self.speak_and_play, text, text_index, session_id=self.session_id)
            self.dialogue.put(Message(role="assistant", content=text))
        elif result.action == Action.REQLLM:  # 调用函数后再请求llm生成回复

            text = result.result
            if text is not None and len(text) > 0:
                function_id = function_call_data["id"]
                function_name = function_call_data["name"]
                function_arguments = function_call_data["arguments"]
                if not isinstance(function_arguments, str):
                    function_arguments = json.dumps(function_arguments)
                self.dialogue.put(Message(role='assistant',
                                          tool_calls=[{"id": function_id,
                                                       "function": {"arguments": function_arguments,
                                                                    "name": function_name},
                                                       "type": 'function',
                                                       "index": 0}]))

                self.dialogue.put(Message(role="tool", tool_call_id=function_id, content=text))
                self.chat_with_function_calling(text, tool_call=True)
        elif result.action == Action.NOTFOUND:
            text = result.result
            self.recode_first_last_text(text, text_index)
            future = self.executor.submit(self.speak_and_play, text, text_index, session_id=self.session_id)
            self.dialogue.put(Message(role="assistant", content=text))
        else:
            text = result.result
            self.recode_first_last_text(text, text_index)
            future = self.executor.submit(self.speak_and_play, text, text_index, session_id=self.session_id)
            self.dialogue.put(Message(role="assistant", content=text))

    def _tts_priority_thread(self):
        while not self.stop_event.is_set():
            text = None
            try:
                try:
                    future = self.tts_queue.get(timeout=1)
                except queue.Empty:
                    if self.stop_event.is_set():
                        break
                    continue
                if future is None:
                    continue
                text = None
                opus_datas, text_index, tts_file = [], 0, None
                try:
                    self.logger.bind(tag=TAG).debug("正在处理TTS任务...")
                    tts_timeout = self.config.get("tts_timeout", 10)
                    tts_file, text, text_index = future.result(timeout=tts_timeout)
                    if text is None or len(text) <= 0:
                        self.logger.bind(tag=TAG).error(f"TTS出错：{text_index}: tts text is empty")
                    elif tts_file is None:
                        self.logger.bind(tag=TAG).error(f"TTS出错： file is empty: {text_index}: {text}")
                    else:
                        self.logger.bind(tag=TAG).debug(f"TTS生成：文件路径: {tts_file}")
                        if os.path.exists(tts_file):
                            opus_datas, duration = self.tts.audio_to_opus_data(tts_file)
                        else:
                            self.logger.bind(tag=TAG).error(f"TTS出错：文件不存在{tts_file}")
                except TimeoutError:
                    self.logger.bind(tag=TAG).error("TTS超时")
                except Exception as e:
                    self.logger.bind(tag=TAG).error(f"TTS出错: {e}")
                if not self.client_abort:
                    # 如果没有中途打断就发送语音
                    self.audio_play_queue.put((opus_datas, text, text_index))
                if self.tts.delete_audio_file and tts_file is not None and os.path.exists(tts_file):
                    os.remove(tts_file)
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"TTS任务处理错误: {e}")
                self.clearSpeakStatus()
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send(json.dumps({"type": "tts", "state": "stop", "session_id": self.session_id})),
                    self.loop
                )
                self.logger.bind(tag=TAG).error(f"tts_priority priority_thread: {text} {e}")
            asyncio.sleep(0.01)

    def _audio_play_priority_thread(self):
        while not self.stop_event.is_set():
            text = None
            try:
                try:
                    opus_datas, text, text_index = self.audio_play_queue.get(timeout=1)
                except queue.Empty:
                    if self.stop_event.is_set():
                        break
                    continue
                future = asyncio.run_coroutine_threadsafe(sendAudioMessage(self, opus_datas, text, text_index),
                                                          self.loop)
                future.result()
                
                # 更新最后交互时间
                if self.proactive:
                    self.proactive.update_last_interaction( time.time())

            except Exception as e:
                self.logger.bind(tag=TAG).error(f"audio_play_priority priority_thread: {text} {e}")
            asyncio.sleep(0.01)

    def speak_and_play(self, text, text_index=0, session_id=None):
        if text is None or len(text) <= 0:
            self.logger.bind(tag=TAG).info(f"无需tts转换，query为空，{text}")
            return None, text, text_index
            
        # 使用 ByteDance TTS provider 生成语音
        try:
            self.logger.bind(tag=TAG).info(f"TTS 开始转换: {text} {datetime.now()}")
            # 在主线程中运行
            tts_file = asyncio.run_coroutine_threadsafe(self.tts.text_to_speak(text, text_index, session_id=session_id), self.loop).result()
                
            if tts_file is None:
                self.logger.bind(tag=TAG).error(f"tts转换失败，{text}")
                return None, text, text_index
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"tts转换异常: {e}")
            return None, text, text_index
            
        self.logger.bind(tag=TAG).debug(f"TTS 文件生成完毕: {tts_file}")
        return tts_file, text, text_index

    def clearSpeakStatus(self):
        self.logger.bind(tag=TAG).debug(f"清除服务端讲话状态")
        self.asr_server_receive = True
        self.tts_last_text_index = -1
        self.tts_first_text_index = -1

    def recode_first_last_text(self, text, text_index=0):
        if self.tts_first_text_index == -1:
            self.logger.bind(tag=TAG).info(f"大模型说出第一句话: {text}, 时间: {datetime.now()}")
            self.tts_first_text_index = text_index
        self.tts_last_text_index = text_index

    async def close(self, ws=None):
        """资源清理方法"""
        # 清理MCP资源
        await self.mcp_manager.cleanup_all()

        # 释放TTS连接
        if self.tts and self.session_id:
            self.tts.release(self.session_id)
            self.logger.bind(tag=TAG).info(f"Released TTS provider for session {self.session_id}")

        # 触发停止事件并清理资源
        if self.stop_event:
            self.stop_event.set()
        
        # 立即关闭线程池
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None
        
        # 清空任务队列
        self._clear_queues()
        
        if ws:
            await ws.close()
        elif self.websocket:
            await self.websocket.close()
        self.logger.bind(tag=TAG).info("连接资源已释放")

    def _clear_queues(self):
        # 清空所有任务队列
        for q in [self.audio_play_queue]:
            if not q:
                continue
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    continue
            q.queue.clear()
            # 添加毒丸信号到队列，确保线程退出
            # q.queue.put(None)

    def reset_vad_states(self):
        self.client_audio_buffer = bytes()
        self.client_have_voice = False
        self.client_have_voice_last_time = 0
        self.client_voice_stop = False
        self.logger.bind(tag=TAG).debug("VAD states reset.")

    def chat_and_close(self, text):
        """Chat with the user and then close the connection"""
        try:
            # Use the existing chat method
            self.chat(text)

            # After chat is complete, close the connection
            self.close_after_chat = True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Chat and close error: {str(e)}")

    async def send_text_response(self, text):
        """发送文本响应"""
        try:
            # 直接使用 ByteDance TTS provider 生成语音
            tts_file = await self.tts.text_to_speak(text)
            if not tts_file:
                self.logger.bind(tag=TAG).error(f"TTS生成失败: {text}")
                return


        except Exception as e:
            self.logger.bind(tag=TAG).error(f"发送文本响应失败: {e}")
            self.logger.bind(tag=TAG).error(f"错误详情: {str(e)}")
            self.logger.bind(tag=TAG).error(f"错误类型: {type(e)}")
            if hasattr(e, '__traceback__'):
                self.logger.bind(tag=TAG).error(f"堆栈跟踪: {e.__traceback__}")

    async def check_proactive_dialogue(self):
        """检查是否需要发起主动对话"""
        if not self.proactive:
            return
        
        current_time = time.time()
        if await self.proactive.should_initiate_dialogue(current_time, self):
            # 生成主动对话内容
            last_seen_speaker_id = self.memory.get_last_seen_speaker_id()
            if last_seen_speaker_id:
                self.logger.bind(tag=TAG).info(f"Last seen speaker ID: {last_seen_speaker_id}")
            else:
                self.logger.bind(tag=TAG).info("No last seen speaker ID found.")

            content = await self.proactive.generate_proactive_content(
                self.dialogue.dialogue,
                self.llm,
                self.memory.user_memories.get(last_seen_speaker_id, {}).get('memories', []),
                self.memory.user_memories.get(last_seen_speaker_id, {}).get('short_memory', []),
            )
            self.dialogue.put(Message(role="assistant", content=content))
            if await self.send_full_audio_message(content):
                self.logger.bind(tag=TAG).info(f"发起主动对话: {content}")
            
            # 更新最后主动对话时间
            self.proactive.last_proactive_time = current_time


    async def send_full_audio_message(self, content):
        # 检查系统是否正在说话
        """if not self.asr_server_receive:
            self.logger.bind(tag=TAG).debug(f"系统正在说话，等待中... {content}")
            return"""
        
        """开始主动对话"""
        # 添加到对话历史并开始对话
        self.prepare_session()
        await send_stt_message(self, content)
        
        # 直接使用 ByteDance TTS provider 生成语音
        tts_file = await self.tts.text_to_speak(content, 0, session_id=self.session_id)
        self.tts_last_text_index = 0
        self.tts_first_text_index = 0
        self.llm_finish_task = True
        self.asr_server_receive = True
        self.logger.bind(tag=TAG).info(f"发起主动对话: {content}")
        #self.release_session()

        return True

    async def start_proactive_check(self):
        """启动主动对话检查任务"""

        while not self.stop_event.is_set():
            try:
                await self.check_proactive_dialogue()
                await asyncio.sleep(self.proactive.config.get("silence_threshold", 60))  # 根据配置的时间间隔检查
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"主动对话检查任务出错: {e}")
                await asyncio.sleep(self.proactive.config.get("silence_threshold", 60))  # 出错后等待配置的时间间隔再试

            asyncio.sleep(5)

    async def handle_audio_message(self, audio, text, speaker_id)->bool:
        """处理音频消息"""
        try:
            # 如果正在等待管理员声纹，则处理声纹识别
            if self.private_config and hasattr(self.private_config, 'waiting_for_admin_voiceprint') and self.private_config.waiting_for_admin_voiceprint:
                if self.voiceprint:
                    try:
                        # 识别说话人
                        speaker_id = await self.voiceprint.identify_speaker(audio, self.headers.get('device_id'))
                        if speaker_id:
                            # 设置为管理员speaker_id
                            await self.private_config.set_admin_speaker_id(speaker_id)
                            self.private_config.waiting_for_admin_voiceprint = False
                            self.logger.bind(tag=TAG).info(f"已设置管理员speaker_id: {speaker_id}")
                            
                            # 发送提示消息
                            await self.send_full_audio_message("已设置您为管理员，您的声纹已被记录。")
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(f"处理管理员声纹失败: {e}")
            
            # 处理音频消息
            if not self.asr_server_receive:
                self.logger.bind(tag=TAG).debug("系统正在说话，skip")
                return False

            
            return True
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理音频消息失败: {e}")
            return False
    
    async def handle_text_message(self, text):
        """处理文本消息"""
        try:
            # 检查是否在添加家庭成员模式
            if self.family_wizard and self.family_wizard.is_in_setup_mode():
                if text == "设置完毕":
                    self.family_wizard.finish_setup()
                    await self.send_text_response("家庭成员设置已完成。")
                    return False
                return False

            # 检查是否是设置家庭成员的指令
            if text == "设置家庭成员":
                if self.private_config and self.private_config.is_in_admin_mode():
                    self.family_wizard.start_setup()
                    member_name = self.family_wizard.get_next_member_name()
                    self.family_manager.start_adding_member(member_name)
                    await self.send_text_response("请让第一个成员说一句话，我会记录他的声纹。")
                    return False
                else:
                    await self.send_text_response("抱歉，只有管理员才能设置家庭成员。")
                    return False

            # 检查是否在创建角色模式
            if self.is_creating_role and self.role_wizard:
                response = self.role_wizard.process_answer(text)
                if response:
                    await self.send_text_response(response)
                    if "角色创建成功" in response:
                        self.is_creating_role = False
                    await self.send_text_response("抱歉，只有管理员才能设置家庭成员。")
                    return False

            # 检查是否是创建角色的指令
            if text == "增加一个角色" or text == "创建一个角色":
                if self.private_config and self.private_config.is_in_admin_mode():
                    self.is_creating_role = True
                    response = self.role_wizard.start_creation()
                    await self.send_text_response(response)
                    return False
                else:
                    await self.send_text_response("抱歉，只有管理员才能创建角色。")
                    return False    
                
            #return await self.handle_normal_chat(text)
            return True

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"处理文本消息失败: {e}")
            return False
        
        return True

    def switch_role(self, role_name):
        """切换角色"""
        try:
            # 1. 检查角色是否存在
            roles = self.config.get("roles", [])
            target_role = None
            for role in roles:
                if role["name"] == role_name:
                    target_role = role
                    break
            
            if not target_role:
                self.logger.bind(tag=TAG).error(f"角色 {role_name} 不存在")
                return False
                
            # 2. 更新系统提示词
            new_prompt = target_role["prompt"].replace("{{assistant_name}}", role_name)
            self.change_system_prompt(new_prompt)
            
            # 3. 更新记忆系统的角色
            if self.memory:
                self.memory.set_r = role_name
                
                # 重置记忆系统
                device_id = self.headers.get("device-id", None)
                self.memory.init_memory(device_id, role_name, self.llm)
                self.memory.set_r = role_name
                self.logger.bind(tag=TAG).info(f"角色切换为 {role_name}，记忆系统已重置")
            
            # 4. 更新私有配置中的当前角色
            if self.private_config:
                self.private_config.private_config["current_role"] = role_name
                #self.private_config.save_private_config()
            
            # 5. 清空当前对话历史
            self.dialogue = Dialogue()
            self.dialogue.put(Message(role="system", content=target_role["prompt"]))
            
            # 6. 重置主动对话状态
            if self.proactive:
                self.proactive.last_proactive_time = time.time()
                self.proactive.interaction_count = 0

            # 7. 设置TTS语音
            if "voice" in target_role:
                # 获取当前TTS类型
                tts = self.config.get("selected_module", {}).get("TTS", "")
                tts_type = self.config.get("TTS", {}).get(tts, {}).get("type", "").lower()
                if tts_type:
                    # 获取对应TTS类型的voice配置
                    if tts_type == "tts_pool":
                        provider = self.config.get("TTS", {}).get(tts_type, {}).get("provider", 'bytedanceStream')
                        tts_type = self.config.get("TTS", {}).get(provider, {}).get('type', 'bytedance')
                
                    voice = target_role["voice"].get(tts_type)
                    if voice:
                        self.tts.set_voice(voice, session_id=self.session_id)
                        self.voice = voice
                    self.logger.bind(tag=TAG).info(f"已设置TTS语音为: {voice}")
                
            
            self.logger.bind(tag=TAG).info(f"成功切换到角色: {role_name}")
            return True
            
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"切换角色失败: {e}")
            return False

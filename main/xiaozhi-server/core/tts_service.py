import asyncio
import time
import json
import uuid
import os
import websockets
from typing import Dict, Optional, List
import logging
from concurrent.futures import ThreadPoolExecutor
from pydub import AudioSegment
import io

logger = logging.getLogger(__name__)

# Protocol constants
PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

# Message Type
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_RESPONSE = 0b1011
FULL_SERVER_RESPONSE = 0b1001
ERROR_INFORMATION = 0b1111

# Message Type Specific Flags
MsgTypeFlagNoSeq = 0b0000
MsgTypeFlagPositiveSeq = 0b1
MsgTypeFlagLastNoSeq = 0b10
MsgTypeFlagNegativeSeq = 0b11
MsgTypeFlagWithEvent = 0b100

# Events
EVENT_NONE = 0
EVENT_Start_Connection = 1
EVENT_FinishConnection = 2
EVENT_ConnectionStarted = 50
EVENT_ConnectionFailed = 51
EVENT_ConnectionFinished = 52
EVENT_StartSession = 100
EVENT_FinishSession = 102
EVENT_SessionStarted = 150
EVENT_SessionFinished = 152
EVENT_SessionFailed = 153
EVENT_TaskRequest = 200
EVENT_TTSSentenceStart = 350
EVENT_TTSSentenceEnd = 351
EVENT_TTSResponse = 352

class Header:
    def __init__(self,
                 protocol_version=PROTOCOL_VERSION,
                 header_size=DEFAULT_HEADER_SIZE,
                 message_type: int = 0,
                 message_type_specific_flags: int = 0,
                 serial_method: int = 0,
                 compression_type: int = 0,
                 reserved_data=0):
        self.header_size = header_size
        self.protocol_version = protocol_version
        self.message_type = message_type
        self.message_type_specific_flags = message_type_specific_flags
        self.serial_method = serial_method
        self.compression_type = compression_type
        self.reserved_data = reserved_data

    def as_bytes(self) -> bytes:
        return bytes([
            (self.protocol_version << 4) | self.header_size,
            (self.message_type << 4) | self.message_type_specific_flags,
            (self.serial_method << 4) | self.compression_type,
            self.reserved_data
        ])

class Optional:
    def __init__(self, event: int = EVENT_NONE, sessionId: str = None, sequence: int = None):
        self.event = event
        self.sessionId = sessionId
        self.errorCode: int = 0
        self.connectionId: str | None = None
        self.response_meta_json: str | None = None
        self.sequence = sequence

    def as_bytes(self) -> bytes:
        option_bytes = bytearray()
        if self.event != EVENT_NONE:
            option_bytes.extend(self.event.to_bytes(4, "big", signed=True))
        if self.sessionId is not None:
            session_id_bytes = str.encode(self.sessionId)
            size = len(session_id_bytes).to_bytes(4, "big", signed=True)
            option_bytes.extend(size)
            option_bytes.extend(session_id_bytes)
        if self.sequence is not None:
            option_bytes.extend(self.sequence.to_bytes(4, "big", signed=True))
        return option_bytes

class Response:
    def __init__(self, header: Header, optional: Optional):
        self.optional = optional
        self.header = header
        self.payload: bytes | None = None

class TTSService:
    def __init__(self, config: Dict, max_connections: int = 3, cache_size: int = 1000):
        self.config = config
        self.connection_pool = []
        self.connection_locks = []
        self.max_connections = max_connections
        self.cache = {}
        self.max_cache_size = cache_size
        self.preload_buffer = asyncio.Queue(maxsize=10)  # 增加队列容量
        self.metrics = {
            'total_requests': 0,
            'cache_hits': 0,
            'processing_time': 0
        }
        self.executor = ThreadPoolExecutor(max_workers=max_connections)  # 增加线程池大小
        self.initialized = False
        self.initialization_lock = asyncio.Lock()
        self.preload_tasks = []  # 存储多个预加载任务
        self.preload_semaphore = asyncio.Semaphore(max_connections)  # 控制并发数
        
        # TTS configuration
        self.app_id = config.get("appid")
        self.token = config.get("access_token")
        self.speaker = config.get("voice", "zh_female_shuangkuaisisi_moon_bigtts")
        self.audio_format = config.get("audio_format", "mp3")
        self.audio_sample_rate = config.get("audio_sample_rate", 24000)
        self.url = config.get("url", "wss://openspeech.bytedance.com/api/v3/tts/bidirection")
        self.ws = None
        self.session_id = None
        
    async def initialize(self):
        """初始化TTS服务"""
        if self.initialized:
            return
            
        async with self.initialization_lock:
            if self.initialized:
                return
                
            try:
                # 预创建连接池
                for _ in range(self.max_connections):
                    connection = await self._create_connection()
                    self.connection_pool.append(connection)
                    self.connection_locks.append(asyncio.Lock())
                    
                # 启动多个预加载工作线程
                for _ in range(self.max_connections):
                    task = asyncio.create_task(self._preload_worker())
                    self.preload_tasks.append(task)
                
                self.initialized = True
                logger.info("TTS服务初始化完成")
            except Exception as e:
                logger.error(f"TTS服务初始化失败: {e}")
                for task in self.preload_tasks:
                    task.cancel()
                raise
                
    async def _create_connection(self):
        """创建新的TTS连接"""
        try:
            ws_header = {
                "X-Api-App-Key": self.app_id,
                "X-Api-Access-Key": self.token,
                "X-Api-Resource-Id": 'volc.service_type.10029',
                "X-Api-Connect-Id": str(uuid.uuid4()),
            }
            
            ws = await websockets.connect(
                self.url, 
                additional_headers=ws_header, 
                max_size=1000000000,
                ping_interval=20,
                ping_timeout=20
            )
            
            # Start connection
            await self._send_event(ws, Header(message_type=FULL_CLIENT_REQUEST, message_type_specific_flags=MsgTypeFlagWithEvent).as_bytes(),
                                 Optional(event=EVENT_Start_Connection).as_bytes(), str.encode("{}"))
            
            res = await self._parse_response(await ws.recv())
            if res.optional.event != EVENT_ConnectionStarted:
                raise RuntimeError(f"Start connection failed: {res.optional.__dict__}")
                
            return ws
        except Exception as e:
            logger.error(f"创建TTS连接失败: {e}")
            raise
            
    async def _send_event(self, ws, header: bytes, optional: bytes | None = None, payload: bytes = None):
        """发送事件"""
        full_client_request = bytearray(header)
        if optional is not None:
            full_client_request.extend(optional)
        if payload is not None:
            payload_size = len(payload).to_bytes(4, 'big', signed=True)
            full_client_request.extend(payload_size)
            full_client_request.extend(payload)
        await ws.send(full_client_request)
        
    def _read_content(self, res: bytes, offset: int):
        """读取内容"""
        content_size = int.from_bytes(res[offset: offset + 4], 'big')
        offset += 4
        content = str(res[offset: offset + content_size])
        offset += content_size
        return content, offset
        
    def _read_payload(self, res: bytes, offset: int):
        """读取payload"""
        payload_size = int.from_bytes(res[offset: offset + 4], 'big')
        offset += 4
        payload = res[offset: offset + payload_size]
        offset += payload_size
        return payload, offset
        
    async def _parse_response(self, res) -> Response:
        """解析响应"""
        if isinstance(res, str):
            raise RuntimeError(res)
            
        response = Response(Header(), Optional())
        # 解析header
        header = response.header
        num = 0b00001111
        header.protocol_version = res[0] >> 4 & num
        header.header_size = res[0] & 0x0f
        header.message_type = (res[1] >> 4) & num
        header.message_type_specific_flags = res[1] & 0x0f
        header.serial_method = res[2] >> num
        header.compression_type = res[2] & 0x0f
        header.reserved_data = res[3]
        
        offset = 4
        optional = response.optional
        if header.message_type == FULL_SERVER_RESPONSE or AUDIO_ONLY_RESPONSE:
            if header.message_type_specific_flags == MsgTypeFlagWithEvent:
                optional.event = int.from_bytes(res[offset:8], 'big')
                offset += 4
                if optional.event == EVENT_NONE:
                    return response
                elif optional.event == EVENT_ConnectionStarted:
                    optional.connectionId, offset = self._read_content(res, offset)
                elif optional.event == EVENT_ConnectionFailed:
                    optional.response_meta_json, offset = self._read_content(res, offset)
                elif (optional.event == EVENT_SessionStarted or
                      optional.event == EVENT_SessionFailed or
                      optional.event == EVENT_SessionFinished):
                    optional.sessionId, offset = self._read_content(res, offset)
                    optional.response_meta_json, offset = self._read_content(res, offset)
                else:
                    optional.sessionId, offset = self._read_content(res, offset)
                    response.payload, offset = self._read_payload(res, offset)
                    
        elif header.message_type == ERROR_INFORMATION:
            optional.errorCode = int.from_bytes(res[offset:offset + 4], "big", signed=True)
            offset += 4
            response.payload, offset = self._read_payload(res, offset)
            
        return response
        
    def _get_payload_bytes(self, text: str, event: int = EVENT_NONE):
        """获取payload字节"""
        return str.encode(json.dumps({
            "user": {"uid": str(uuid.uuid4())},
            "event": event,
            "namespace": "BidirectionalTTS",
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "audio_params": {
                    "format": self.audio_format,
                    "sample_rate": self.audio_sample_rate
                }
            }
        }))
        
    async def _get_connection(self):
        """获取一个可用的连接"""
        for i, (connection, lock) in enumerate(zip(self.connection_pool, self.connection_locks)):
            if not lock.locked():
                return connection, lock, i
        # 如果所有连接都在使用，等待第一个连接
        return self.connection_pool[0], self.connection_locks[0], 0
        
    async def _process_text(self, text: str, connection, lock):
        """处理文本"""
        try:
            async with lock:  # 使用锁确保同一连接不会被并发使用
                # Start session
                self.session_id = uuid.uuid4().__str__().replace('-', '')
                await self._send_event(connection, 
                                     Header(message_type=FULL_CLIENT_REQUEST,
                                           message_type_specific_flags=MsgTypeFlagWithEvent,
                                           serial_method=1).as_bytes(),
                                     Optional(event=EVENT_StartSession, sessionId=self.session_id).as_bytes(),
                                     self._get_payload_bytes(text, EVENT_StartSession))
                                     
                res = await self._parse_response(await connection.recv())
                if res.optional.event != EVENT_SessionStarted:
                    raise RuntimeError(f"Start session failed: {res.optional.__dict__}")
                    
                # Send text
                await self._send_event(connection,
                                     Header(message_type=FULL_CLIENT_REQUEST,
                                           message_type_specific_flags=MsgTypeFlagWithEvent,
                                           serial_method=1).as_bytes(),
                                     Optional(event=EVENT_TaskRequest, sessionId=self.session_id).as_bytes(),
                                     self._get_payload_bytes(text, EVENT_TaskRequest))
                                     
                # Finish session
                await self._send_event(connection,
                                     Header(message_type=FULL_CLIENT_REQUEST,
                                           message_type_specific_flags=MsgTypeFlagWithEvent,
                                           serial_method=1).as_bytes(),
                                     Optional(event=EVENT_FinishSession, sessionId=self.session_id).as_bytes(),
                                     str.encode('{}'))
                                     
                # Process audio data
                all_payloads = []
                while True:
                    try:
                        res = await self._parse_response(await connection.recv())
                        if res.optional.event == EVENT_TTSResponse and res.header.message_type == AUDIO_ONLY_RESPONSE:
                            all_payloads.append(res.payload)
                        elif res.optional.event in [EVENT_TTSSentenceStart, EVENT_TTSSentenceEnd]:
                            continue
                        else:
                            break
                    except websockets.exceptions.ConnectionClosed:
                        logger.error("WebSocket connection closed, attempting to reconnect...")
                        # 重新创建连接
                        new_connection = await self._create_connection()
                        self.connection_pool[i] = new_connection
                        connection = new_connection
                        continue
                        
                # Convert to opus format
                if all_payloads:
                    try:
                        combined_payload = b''.join(all_payloads)
                        audio = AudioSegment.from_mp3(io.BytesIO(combined_payload))
                        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
                        return audio.raw_data
                    except Exception as e:
                        logger.error(f"Error processing audio data: {e}")
                        
                return None
                
        except Exception as e:
            logger.error(f"Error processing text: {e}")
            return None
            
    async def process(self, text: str):
        """处理TTS请求"""
        if not self.initialized:
            await self.initialize()
            
        start_time = time.time()
        self.metrics['total_requests'] += 1
        
        # 检查缓存
        if text in self.cache:
            self.metrics['cache_hits'] += 1
            return self.cache[text]
            
        try:
            # 将文本放入预加载队列
            try:
                await self.preload_buffer.put(text)
            except asyncio.QueueFull:
                pass  # 如果队列已满，继续处理当前请求
                
            # 获取连接和锁
            connection, lock, _ = await self._get_connection()
            
            # 处理文本
            audio_data = await self._process_text(text, connection, lock)
            
            if audio_data:
                # 缓存结果
                self._cache_audio(text, audio_data)
                
            # 更新指标
            self.metrics['processing_time'] += time.time() - start_time
            
            return audio_data
            
        except Exception as e:
            logger.error(f"TTS processing error: {e}")
            return None
            
    def _cache_audio(self, text: str, audio_data: bytes):
        """缓存音频数据"""
        if len(self.cache) >= self.max_cache_size:
            # 清理最旧的缓存
            self.cache.pop(next(iter(self.cache)))
        self.cache[text] = audio_data
        
    def get_metrics(self) -> Dict:
        """获取性能指标"""
        return self.metrics
        
    async def close(self):
        """关闭TTS服务"""
        # 取消所有预加载任务
        for task in self.preload_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
                
        # 关闭连接池
        for connection in self.connection_pool:
            try:
                await self._send_event(connection,
                                     Header(message_type=FULL_CLIENT_REQUEST,
                                           message_type_specific_flags=MsgTypeFlagWithEvent,
                                           serial_method=1).as_bytes(),
                                     Optional(event=EVENT_FinishConnection).as_bytes(),
                                     str.encode('{}'))
                await connection.close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
                
        self.executor.shutdown()

    async def _preload_worker(self):
        """预加载工作线程"""
        while True:
            try:
                async with self.preload_semaphore:  # 控制并发数
                    # 从预加载队列获取文本
                    text = await self.preload_buffer.get()
                    if text:
                        # 直接异步处理预加载
                        await self._preload_tts(text)
                    self.preload_buffer.task_done()  # 标记任务完成
            except asyncio.CancelledError:
                logger.info("Preload worker cancelled")
                break
            except Exception as e:
                logger.error(f"Preload worker error: {e}")
                await asyncio.sleep(0.1)  # 减少错误时的休眠时间
                
    async def _preload_tts(self, text: str):
        """预加载TTS音频"""
        try:
            # 检查缓存
            if text in self.cache:
                return
                
            # 获取连接
            connection = self.connection_pool[0]  # 使用第一个连接
            
            # 处理文本
            audio_data = await self._process_text(text, connection, self.connection_locks[0])
            if audio_data:
                self._cache_audio(text, audio_data)
                
        except Exception as e:
            logger.error(f"Preload TTS error: {e}")
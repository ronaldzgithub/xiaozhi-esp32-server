import asyncio
from datetime import datetime
import json
import os
import uuid
import aiofiles
import websockets
from websockets.asyncio.client import ClientConnection
from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
import threading
from concurrent.futures import Future
import io
from pydub import AudioSegment

TAG = __name__
logger = setup_logging()

# Protocol constants
PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

# Message Type
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_RESPONSE = 0b1011
FULL_SERVER_RESPONSE = 0b1001
ERROR_INFORMATION = 0b1111

# Message Type Specific Flags
MsgTypeFlagNoSeq = 0b0000  # Non-terminal packet with no sequence
MsgTypeFlagPositiveSeq = 0b1  # Non-terminal packet with sequence > 0
MsgTypeFlagLastNoSeq = 0b10  # last packet with no sequence
MsgTypeFlagNegativeSeq = 0b11  # Payload contains event number (int32)
MsgTypeFlagWithEvent = 0b100

# Message Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001

# Message Compression
COMPRESSION_NO = 0b0000
COMPRESSION_GZIP = 0b0001

# Events
EVENT_NONE = 0
EVENT_Start_Connection = 1
EVENT_FinishConnection = 2
EVENT_ConnectionStarted = 50  # 成功建连
EVENT_ConnectionFailed = 51  # 建连失败（可能是无法通过权限认证）
EVENT_ConnectionFinished = 52  # 连接结束

# 上行Session事件
EVENT_StartSession = 100
EVENT_FinishSession = 102

# 下行Session事件
EVENT_SessionStarted = 150
EVENT_SessionFinished = 152
EVENT_SessionFailed = 153

# 上行通用事件
EVENT_TaskRequest = 200

# 下行TTS事件
EVENT_TTSSentenceStart = 350
EVENT_TTSSentenceEnd = 351
EVENT_TTSResponse = 352


class Header:
    def __init__(self,
                 protocol_version=PROTOCOL_VERSION,
                 header_size=DEFAULT_HEADER_SIZE,
                 message_type: int = 0,
                 message_type_specific_flags: int = 0,
                 serial_method: int = NO_SERIALIZATION,
                 compression_type: int = COMPRESSION_NO,
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

    # 转成 byte 序列
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

    def __str__(self):
        return super().__str__()


# 发送事件
async def send_event(ws, header: bytes, optional: bytes | None = None,
                     payload: bytes = None):
    full_client_request = bytearray(header)
    if optional is not None:
        full_client_request.extend(optional)
    if payload is not None:
        payload_size = len(payload).to_bytes(4, 'big', signed=True)
        full_client_request.extend(payload_size)
        full_client_request.extend(payload)
    await ws.send(full_client_request)


# 读取 res 数组某段 字符串内容
def read_res_content(res: bytes, offset: int):
    content_size = int.from_bytes(res[offset: offset + 4], 'big')
    offset += 4
    content = str(res[offset: offset + content_size])
    offset += content_size
    return content, offset


# 读取 payload
def read_res_payload(res: bytes, offset: int):
    payload_size = int.from_bytes(res[offset: offset + 4], 'big')
    offset += 4
    payload = res[offset: offset + payload_size]
    offset += payload_size
    return payload, offset


# 解析响应结果
def parser_response(res) -> Response:
    if isinstance(res, str):
        raise RuntimeError(res)
    response = Response(Header(), Optional())
    # 解析结果
    # header
    header = response.header
    num = 0b00001111
    header.protocol_version = res[0] >> 4 & num
    header.header_size = res[0] & 0x0f
    header.message_type = (res[1] >> 4) & num
    header.message_type_specific_flags = res[1] & 0x0f
    header.serial_method = res[2] >> num
    header.compression_type = res[2] & 0x0f
    header.reserved_data = res[3]
    #
    offset = 4
    optional = response.optional
    if header.message_type == FULL_SERVER_RESPONSE or AUDIO_ONLY_RESPONSE:
        # read event
        if header.message_type_specific_flags == MsgTypeFlagWithEvent:
            optional.event = int.from_bytes(res[offset:8], 'big')
            offset += 4
            if optional.event == EVENT_NONE:
                return response
            # read connectionId
            elif optional.event == EVENT_ConnectionStarted:
                optional.connectionId, offset = read_res_content(res, offset)
            elif optional.event == EVENT_ConnectionFailed:
                optional.response_meta_json, offset = read_res_content(res, offset)
            elif (optional.event == EVENT_SessionStarted
                  or optional.event == EVENT_SessionFailed
                  or optional.event == EVENT_SessionFinished):
                optional.sessionId, offset = read_res_content(res, offset)
                optional.response_meta_json, offset = read_res_content(res, offset)
            else:
                optional.sessionId, offset = read_res_content(res, offset)
                response.payload, offset = read_res_payload(res, offset)

    elif header.message_type == ERROR_INFORMATION:
        optional.errorCode = int.from_bytes(res[offset:offset + 4], "big", signed=True)
        offset += 4
        response.payload, offset = read_res_payload(res, offset)
    return response


def get_payload_bytes(uid='1234', event=EVENT_NONE, text='', speaker='', audio_format='mp3',
                      audio_sample_rate=24000):
    return str.encode(json.dumps(
        {
            "user": {"uid": uid},
            "event": event,
            "namespace": "BidirectionalTTS",
            "req_params": {
                "text": text,
                "speaker": speaker,
                "audio_params": {
                    "format": audio_format,
                    "sample_rate": audio_sample_rate
                }
            }
        }
    ))


async def start_connection(websocket):
    header = Header(message_type=FULL_CLIENT_REQUEST, message_type_specific_flags=MsgTypeFlagWithEvent).as_bytes()
    optional = Optional(event=EVENT_Start_Connection).as_bytes()
    payload = str.encode("{}")
    return await send_event(websocket, header, optional, payload)


async def start_session(websocket, speaker, session_id):
    header = Header(message_type=FULL_CLIENT_REQUEST,
                    message_type_specific_flags=MsgTypeFlagWithEvent,
                    serial_method=JSON
                    ).as_bytes()
    optional = Optional(event=EVENT_StartSession, sessionId=session_id).as_bytes()
    payload = get_payload_bytes(event=EVENT_StartSession, speaker=speaker)
    return await send_event(websocket, header, optional, payload)


async def send_text(ws: ClientConnection, speaker: str, text: str, session_id):
    header = Header(message_type=FULL_CLIENT_REQUEST,
                    message_type_specific_flags=MsgTypeFlagWithEvent,
                    serial_method=JSON).as_bytes()
    optional = Optional(event=EVENT_TaskRequest, sessionId=session_id).as_bytes()
    payload = get_payload_bytes(event=EVENT_TaskRequest, text=text, speaker=speaker)
    return await send_event(ws, header, optional, payload)


async def finish_session(ws, session_id):
    header = Header(message_type=FULL_CLIENT_REQUEST,
                    message_type_specific_flags=MsgTypeFlagWithEvent,
                    serial_method=JSON
                    ).as_bytes()
    optional = Optional(event=EVENT_FinishSession, sessionId=session_id).as_bytes()
    payload = str.encode('{}')
    return await send_event(ws, header, optional, payload)


async def finish_connection(ws):
    header = Header(message_type=FULL_CLIENT_REQUEST,
                    message_type_specific_flags=MsgTypeFlagWithEvent,
                    serial_method=JSON
                    ).as_bytes()
    optional = Optional(event=EVENT_FinishConnection).as_bytes()
    payload = str.encode('{}')
    return await send_event(ws, header, optional, payload)


class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file=False):
        super().__init__(config, delete_audio_file)
        self.config = config
        self.app_id = config.get("appid")
        self.token = config.get("access_token")
        self.speaker = config.get("voice", "zh_female_shuangkuaisisi_moon_bigtts")
        self.voice = self.speaker
        self.audio_format = config.get("audio_format", "mp3")
        self.audio_sample_rate = config.get("audio_sample_rate", 24000)
        self.url = config.get("url", "wss://openspeech.bytedance.com/api/v3/tts/bidirection")
        self.session_manager = None
        self.stop_event = threading.Event()
        self.session_lock = threading.Lock()
        self.text_audio_map = {}  # 存储文本和音频的对应关系
        self.current_text_id = None  # 当前正在处理的文本ID
        self.ws = None  # WebSocket 连接
        self.session_id = None  # 会话ID
        self.tts_queue = None  # 将由 connection.py 设置
        self.audio_play_queue = None  # 将由 connection.py 设置
        self.max_queue_size = config.get("max_queue_size", 100)  # 添加队列大小限制
        self.pending_texts = asyncio.Queue(maxsize=self.max_queue_size)  # 设置队列最大大小
        # Initialize WebSocket connection asynchronously
        asyncio.create_task(self._session_manager())

    def set_tts_queue(self, tts_queue):
        """设置从 connection.py 传递过来的 tts_queue"""
        self.tts_queue = tts_queue
        logger.bind(tag=TAG).info("TTS queue has been set from connection.py")

    def set_audio_play_queue(self, audio_play_queue):
        """设置从 connection.py 传递过来的 audio_play_queue"""
        self.audio_play_queue = audio_play_queue
        logger.bind(tag=TAG).info("Audio play queue has been set from connection.py")

    def generate_filename(self):
        """Generate a unique filename for the TTS output"""
        filename = f"bytedance_tts_{uuid.uuid4()}.{self.audio_format}"
        return os.path.join(self.output_file, filename)

    async def _init_websocket(self):
        """初始化 WebSocket 连接"""
        try:
            ws_header = {
                "X-Api-App-Key": self.app_id,
                "X-Api-Access-Key": self.token,
                "X-Api-Resource-Id": 'volc.service_type.10029',
                "X-Api-Connect-Id": str(uuid.uuid4()),
            }
            logger.bind(tag=TAG).info(f"Connecting to {self.url} with headers: {ws_header}")
            
            # Connect without using async with
            self.ws = await websockets.connect(
                self.url, 
                additional_headers=ws_header, 
                max_size=1000000000,
                ping_interval=20,  # Add ping interval to keep connection alive
                ping_timeout=20    # Add ping timeout
            )
            
            # Start connection
            await start_connection(self.ws)
            res = parser_response(await self.ws.recv())
            logger.bind(tag=TAG).info(f"Start connection response: {res.optional.__dict__}")
            
            if res.optional.event != EVENT_ConnectionStarted:
                raise RuntimeError(f"Start connection failed: {res.optional.__dict__}")

                
            return True
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"WebSocket initialization error: {e}")
            if self.ws:
                await self.ws.close()
                self.ws = None
            raise e

    async def _process_text(self, text_info):
        """处理单个文本"""
        try:
            start_time = datetime.now()
            logger.bind(tag=TAG).info(f"Starting _process_text at {start_time} for: {text_info['text']}")
            
            # Start session
            session_start_time = datetime.now()
            self.session_id = uuid.uuid4().__str__().replace('-', '')
            await start_session(self.ws, self.voice, self.session_id)
            res = parser_response(await self.ws.recv())
            logger.bind(tag=TAG).info(f"Session started in {(datetime.now() - session_start_time).total_seconds():.2f}s")
            
            if res.optional.event != EVENT_SessionStarted:
                raise RuntimeError(f"Start session failed: {res.optional.__dict__}")
            
            # 发送文本
            text_send_time = datetime.now()
            await send_text(self.ws, self.voice, text_info['text'], self.session_id)
            logger.bind(tag=TAG).info(f"Text sent in {(datetime.now() - text_send_time).total_seconds():.2f}s")
            
            # 结束当前会话
            await finish_session(self.ws, self.session_id)

            # 处理音频数据
            audio_process_start = datetime.now()
            all_payloads = []
            while True:
                try:
                    res = parser_response(await self.ws.recv())
                    
                    if res.optional.event == EVENT_TTSResponse and res.header.message_type == AUDIO_ONLY_RESPONSE:
                        all_payloads.append(res.payload)
                    elif res.optional.event in [EVENT_TTSSentenceStart, EVENT_TTSSentenceEnd]:
                        continue
                    else:
                        break
                except websockets.exceptions.ConnectionClosed:
                    logger.bind(tag=TAG).error("WebSocket connection closed, attempting to reconnect...")
                    await self._init_websocket()
                    continue

            logger.bind(tag=TAG).info(f"Audio processing took {(datetime.now() - audio_process_start).total_seconds():.2f}s")
            
            # 所有音频数据收集完成后，一次性转换为opus格式
            opus_convert_start = datetime.now()
            all_opus_data = []
            if all_payloads:
                try:
                    # 合并所有payload
                    combined_payload = b''.join(all_payloads)
                    # 将 MP3 数据转换为 PCM 数据
                    audio = AudioSegment.from_mp3(io.BytesIO(combined_payload))
                    # 转换为单声道/16kHz采样率/16位小端编码（确保与编码器匹配）
                    audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
                    # 将音频数据转换为 opus 格式
                    opus_data, _ = self.audio_to_opus_data_directly(audio)
                    all_opus_data.extend(opus_data)
                except Exception as e:
                    logger.bind(tag=TAG).error(f"Error processing combined audio data: {e}")
            
            logger.bind(tag=TAG).info(f"Opus conversion took {(datetime.now() - opus_convert_start).total_seconds():.2f}s")
            
            # 发送到 audio_play_queue
            queue_send_start = datetime.now()
            if self.audio_play_queue is not None and all_opus_data:
                self.audio_play_queue.put((all_opus_data, text_info['text'], text_info['text_id']))
                logger.bind(tag=TAG).info(f"Audio sent to play queue in {(datetime.now() - queue_send_start).total_seconds():.2f}s")
            elif not all_opus_data:
                logger.bind(tag=TAG).error("No audio data collected")
            else:
                logger.bind(tag=TAG).error("audio_play_queue is None, cannot send audio packet")
            
            if res.optional.event != EVENT_SessionFinished:
                raise RuntimeError(f"Finish session failed: {res.optional.__dict__}")
            
            total_time = (datetime.now() - start_time).total_seconds()
            logger.bind(tag=TAG).info(f"Total processing time: {total_time:.2f}s for text_id: {text_info['text_id']}")
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error processing text: {e}")

    async def _session_manager(self):
        """管理会话的进程"""
        # 初始化 WebSocket 连接
        if not self.ws:
            await self._init_websocket()
        
        while not self.stop_event.is_set():
            try:
                # 等待新的文本，设置超时时间
                try:
                    queue_wait_start = datetime.now()
                    text_info = await asyncio.wait_for(self.pending_texts.get(), timeout=115.0)
                    queue_wait_time = (datetime.now() - queue_wait_start).total_seconds()
                    logger.bind(tag=TAG).info(f"Queue wait time: {text_info['text']} {queue_wait_time:.2f}s")
                    
                    if queue_wait_time > 1.0:  # 如果等待时间超过1秒，记录警告
                        logger.bind(tag=TAG).warning(f"Long queue wait time detected: {queue_wait_time:.2f}s")
                    
                    logger.bind(tag=TAG).info(f"Processing text: {text_info['text']} {datetime.now()}")
                    await self._process_text(text_info)
                    self.pending_texts.task_done()
                    logger.bind(tag=TAG).info(f"Processing text Done: {text_info['text']} {datetime.now()}")
                except asyncio.TimeoutError:
                    # 如果超时，检查连接状态
                    if not self.ws or self.ws.state == websockets.State.CLOSED:
                        logger.bind(tag=TAG).info("WebSocket connection lost, attempting to reconnect...")
                        await self._init_websocket()
                    continue
                
            except Exception as e:
                logger.bind(tag=TAG).error(f"Error in session manager: {e}")
                continue

    async def text_to_speak(self, text, output_file=None):
        """Convert text to speech using ByteDance TTS API"""
        try:
            # 如果 output_file 为 None，生成一个新的文件名
            if output_file is None:
                output_file = self.generate_filename()

            # 生成文本ID并记录对应关系
            text_id = str(uuid.uuid4())
            self.current_text_id = text_id
            self.text_audio_map[text_id] = {
                'text': text,
                'audio_file': output_file,
                'status': 'processing'
            }
            
            # 创建文本信息
            text_info = {
                'text_id': text_id,
                'text': text,
                'audio_file': output_file
            }
            
            
            logger.bind(tag=TAG).info(f"Before put: {text} {datetime.now()}")
            # 检查队列是否已满
            if self.pending_texts.full():
                logger.bind(tag=TAG).warning("TTS queue is full, waiting for space...")
                # 等待队列有空间
                await asyncio.wait_for(self.pending_texts.put(text_info), timeout=30.0)
            else:
                # 直接放入队列
                await self.pending_texts.put(text_info)

            #await self._process_text(text_info)
            # 记录时间和文本
            logger.bind(tag=TAG).info(f"After put  text at: {datetime.now()} - Text: {text}")
            return True
        except asyncio.TimeoutError:
            logger.bind(tag=TAG).error("Timeout while waiting to add text to queue")
            return False
        except Exception as e:
            logger.bind(tag=TAG).error(f"ByteDance TTS error: {e}")
            return False

    def get_text_audio_map(self):
        """获取文本和音频的对应关系"""
        return self.text_audio_map

    def get_current_text_id(self):
        """获取当前正在处理的文本ID"""
        return self.current_text_id

    def set_voice(self, voice):
        """Set the voice for TTS"""
        self.voice = voice 
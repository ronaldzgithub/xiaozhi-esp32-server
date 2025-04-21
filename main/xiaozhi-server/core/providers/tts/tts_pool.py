import asyncio
import os
import queue
import threading
import time
from typing import Dict, Optional
import uuid
from config.logger import setup_logging
from core.providers.tts.base import TTSProviderBase
from core.utils.tts import create_instance
from config.settings import load_config
TAG = __name__
logger = setup_logging()
IDLE_TIMEOUT = 3  # 5分钟超时时间（秒）

class TTSProvider(TTSProviderBase):
    def __init__(self, config, delete_audio_file = True):
        super().__init__(config, delete_audio_file)
        self.config = config
        self.tts_provider_class = config["provider"]
        self.max_pool_size = config["max_pool_size"]
        self.pool = queue.Queue(maxsize=self.max_pool_size)
        self.in_use: Dict[str, 'TTSPoolItem'] = {}  # session_id -> TTSPoolItem
        self.lock = threading.Lock()
        self._initialize_pool()
        # 启动定时检查任务
        self.idle_check_task = None
        self.idle_check_task = asyncio.create_task(self._idle_check_loop())

    async def _idle_check_loop(self):
        """异步空闲检查循环"""
        try:
            while True:
                try:
                    await self._check_idle_connections()
                except Exception as e:
                    logger.bind(tag=TAG).error(f"Error in idle check task: {e}")
                await asyncio.sleep(3)  # 每分钟检查一次
        except asyncio.CancelledError:
            logger.bind(tag=TAG).info("Idle check task cancelled")
            raise

    async def _check_idle_connections(self):
        """检查并释放空闲连接"""
        current_time = time.time()
        # 收集需要释放的session_id
        to_release = []
        for session_id, pool_item in self.in_use.items():
            if current_time - pool_item.last_used > IDLE_TIMEOUT:
                to_release.append(session_id)
                logger.bind(tag=TAG).info(f"Session {session_id} idle for too long, will be released")

        # 释放空闲连接
        for session_id in to_release:
            await self.release(session_id)

    def generate_filename(self):
        """Generate a unique filename for the TTS output"""
        filename = f"bytedance_tts_{uuid.uuid4()}.{self.audio_format}"
        return os.path.join(self.output_file, filename)

    def _initialize_pool(self):
        """初始化连接池"""
        config = load_config()
        type  = config["TTS"][self.config['provider']]['type']
        config = config["TTS"][self.config["provider"]]
        
        for _ in range(self.max_pool_size):
            tts_provider = create_instance(type, config)
            self.pool.put(tts_provider)

    def acquire(self, session_id: str, audio_play_queue, voice) -> Optional['TTSPoolItem']:
        """获取一个TTS连接"""
        with self.lock:
            if session_id in self.in_use:
                pool_item = self.in_use[session_id]
                pool_item.update_last_used()  # 更新最后使用时间
                return pool_item

            try:
                tts_provider = self.pool.get_nowait()
                tts_provider.set_audio_play_queue(audio_play_queue)
                tts_provider.set_voice(voice)
                pool_item = TTSPoolItem(tts_provider, session_id)
                self.in_use[session_id] = pool_item
                logger.bind(tag=TAG).info(f"Acquired TTS provider for session {session_id}")
                return pool_item
            except queue.Empty:
                logger.bind(tag=TAG).warning("No available TTS providers in pool")
                return None

    async def release(self, session_id: str):
        """释放TTS连接回连接池"""
        with self.lock:
            if session_id in self.in_use:
                pool_item = self.in_use.pop(session_id)
                tts_provider = pool_item.tts_provider
                tts_provider.set_audio_play_queue(None)
                tts_provider.set_voice(None)
                try:
                    self.pool.put_nowait(tts_provider)
                    logger.bind(tag=TAG).info(f"Released TTS provider for session {session_id}")
                except queue.Full:
                    logger.bind(tag=TAG).error("TTS pool is full, cannot release provider")

    def cleanup(self):
        """清理所有TTS连接"""
        with self.lock:
            while not self.pool.empty():
                try:
                    tts_provider = self.pool.get_nowait()
                    tts_provider.close()
                except queue.Empty:
                    break
            self.in_use.clear()

    async def text_to_speak(self, text, text_index=0, output_file=None, session_id=None):
        """实现TTSProviderBase的接口"""
        if not session_id:
            raise ValueError("session_id is required")
        
        pool_item = self.in_use.get(session_id)
        if not pool_item:
            logger.bind(tag=TAG).error(f"No TTS provider for session {session_id}, please check the session_id of the session")
            return None

        pool_item.update_last_used()  # 更新最后使用时间
        return await pool_item.tts_provider.text_to_speak(text, text_index, output_file)

    def set_voice(self, voice, session_id=None):
        """设置语音"""
        if not session_id:
            raise ValueError("session_id is required")
        pool_item = self.in_use.get(session_id)
        if not pool_item:
            logger.bind(tag=TAG).error(f"No TTS provider for session {session_id}, please check the session_id of the session")
            return None
        pool_item.tts_provider.set_voice(voice)

    async def close(self):
        """关闭所有TTS连接"""
        await self.stop()
        self.cleanup()

class TTSPoolItem:
    def __init__(self, tts_provider, session_id: str):
        self.tts_provider = tts_provider
        self.session_id = session_id
        self.last_used = time.time()

    def update_last_used(self):
        """更新最后使用时间"""
        self.last_used = time.time() 
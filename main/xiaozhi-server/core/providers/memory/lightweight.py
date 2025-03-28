import os
import json
import uuid
from typing import Dict, Any
from log import logger
from datetime import datetime

class MemoryProvider:
    def __init__(self, config: Dict[str, Any]):
        """初始化记忆系统"""
        self.config = config
        self.logger = logger.bind(tag=TAG)
        self.memory_dir = os.path.join(config.get("memory_dir", "memory"))
        self.max_memories = config.get("max_memories", 100)
        self.memory_window = config.get("memory_window", 10)
        self.similarity_threshold = config.get("similarity_threshold", 0.7)
        self.recency_weight = config.get("recency_weight", 0.3)
        self.relevance_weight = config.get("relevance_weight", 0.7)
        self.memories = {}
        self.metadata = {}
        self._load_memories()

    def _load_memories(self):
        """加载记忆"""
        try:
            if os.path.exists(self.memory_dir):
                for filename in os.listdir(self.memory_dir):
                    if filename.endswith('.json'):
                        memory_id = filename[:-5]  # 移除.json后缀
                        file_path = os.path.join(self.memory_dir, filename)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            self.memories[memory_id] = data.get('memories', [])
                            self.metadata[memory_id] = data.get('metadata', {})
        except Exception as e:
            self.logger.error(f"加载记忆失败: {e}")

    def _save_memories(self):
        """保存记忆"""
        try:
            os.makedirs(self.memory_dir, exist_ok=True)
            for memory_id, memories in self.memories.items():
                file_path = os.path.join(self.memory_dir, f"{memory_id}.json")
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'memories': memories,
                        'metadata': self.metadata.get(memory_id, {})
                    }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存记忆失败: {e}")

    async def add_memory(self, msgs, metadata=None, speaker_id=None):
        """添加记忆"""
        try:
            # 获取当前时间
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 构建记忆内容
            memory_content = []
            for msg in msgs:
                if isinstance(msg, dict):
                    if msg['role'] == "user":
                        memory_content.append(f"User: {msg['content']}")
                    elif msg['role'] == "assistant":
                        memory_content.append(f"Assitant: {msg['content']}")
                else:
                    if msg.role == "user":
                        memory_content.append(f"User: {msg.content}")
                    elif msg.role == "assistant":
                        memory_content.append(f"Assitant: {msg.content}")
            
            # 构建记忆元数据
            memory_metadata = {
                "timestamp": current_time,
                "speaker_id": speaker_id,
                "metadata": metadata or {}
            }
            
            # 保存记忆
            self.save_memory(msgs, memory_content, memory_metadata)
            
            # 更新记忆索引
            self._update_memory_index(memory_content, memory_metadata)
            
            # 保存到文件
            self._save_memories()
            
            self.logger.info(f"添加记忆成功: {len(memory_content)} 条消息")
            return True
            
        except Exception as e:
            self.logger.error(f"添加记忆失败: {e}")
            return False 

    def save_memory(self, msgs, memory_content, memory_metadata):
        """保存记忆"""
        try:
            # 生成记忆ID
            memory_id = str(uuid.uuid4())
            
            # 保存记忆内容
            self.memories[memory_id] = memory_content
            
            # 保存元数据
            self.metadata[memory_id] = memory_metadata
            
            # 保存到文件
            self._save_memories()
            
            self.logger.info(f"保存记忆成功: {memory_id}")
            return memory_id
            
        except Exception as e:
            self.logger.error(f"保存记忆失败: {e}")
            return None 
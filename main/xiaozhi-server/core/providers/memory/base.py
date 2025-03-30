from abc import ABC, abstractmethod
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

class MemoryProviderBase(ABC):
    def __init__(self, config):
        self.config = config
        self.device_id = None
        self.role_id = None
        self.llm = None
        self.speaker_memories = {}  # 存储每个说话人的记忆

    @abstractmethod
    async def save_memory(self, msgs):
        """Save a new memory for specific role and return memory ID"""
        print("this is base func", msgs)

    @abstractmethod
    async def query_memory(self, query: str) -> str:
        """Query memories for specific role based on similarity"""
        return "please implement query method"
    
    @abstractmethod
    def init_memory(self, device_id, role_id, llm):
        self.device_id = device_id    
        self.role_id = role_id
        self.llm = llm

    @abstractmethod
    async def add_memory(self, messages, metadata, speaker_id=None):
        """添加记忆"""
        pass

    @abstractmethod
    async def get_memory(self, speaker_id=None):
        """获取记忆"""
        pass

    @abstractmethod
    def clear_memory(self, speaker_id=None):
        """清除记忆"""
        pass

    def set_role_id(self, role_id):
        """设置当前角色ID"""
        self.role_id = role_id

    def get_speaker_memory(self, speaker_id)->list:
        """获取特定说话人的记忆"""
        if speaker_id not in self.speaker_memories:
            self.speaker_memories[speaker_id] = []
        return self.speaker_memories[speaker_id]

    def add_speaker_memory(self, speaker_id, memory):
        if not isinstance(memory, list):
            memory = [memory]
        """添加特定说话人的记忆"""
        if speaker_id not in self.speaker_memories:
            self.speaker_memories[speaker_id] = []
        self.speaker_memories[speaker_id].append(memory)

    def clear_speaker_memory(self, speaker_id):
        """清除特定说话人的记忆"""
        if speaker_id in self.speaker_memories:
            del self.speaker_memories[speaker_id]

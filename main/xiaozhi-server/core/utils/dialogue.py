import uuid
from typing import List, Dict
from datetime import datetime


class Message:
    def __init__(self, role: str, content: str = None, uniq_id: str = None, tool_calls = None, tool_call_id=None, metadata=None):
        self.uniq_id = uniq_id if uniq_id is not None else str(uuid.uuid4())
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
        self.metadata = metadata or {}


class Dialogue:
    def __init__(self):
        self.dialogue: List[Message] = []
        self.metadata = {}  # 添加元数据存储
        # 获取当前时间
        self.current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def put(self, message: Message):
        """添加消息到对话历史"""
        self.dialogue.append(message)
        # 更新元数据
        if message.metadata:
            self.metadata.update(message.metadata)

    def getMessages(self, m, dialogue):
        if m.tool_calls is not None:
            dialogue.append({"role": m.role, "tool_calls": m.tool_calls})
        elif m.role == "tool":
            dialogue.append({"role": m.role, "tool_call_id": m.tool_call_id, "content": m.content})
        else:
            dialogue.append({"role": m.role, "content": m.content})

    def get_llm_dialogue(self) -> List[Dict[str, str]]:
        dialogue = []
        for m in self.dialogue:
            self.getMessages(m, dialogue)
        return dialogue

    def get_metadata(self):
        """获取对话元数据"""
        return self.metadata

    def update_system_message(self, new_content: str):
        """更新或添加系统消息"""
        # 查找第一个系统消息
        system_msg = next((msg for msg in self.dialogue if msg.role == "system"), None)
        if system_msg:
            system_msg.content = new_content
        else:
            self.put(Message(role="system", content=new_content))

    def get_llm_dialogue_with_memory(self, memory_str: str = None) -> List[Dict[str, str]]:
        if memory_str is None or len(memory_str) == 0:
            return self.get_llm_dialogue()
        
        # 构建带记忆的对话
        dialogue = []
        
        # 添加系统提示和记忆
        system_message = next(
            (msg for msg in self.dialogue if msg.role == "system"), None
        )


        if system_message:
            enhanced_system_prompt = (
                f"{system_message.content}\n\n"
                f"回答问题时候，一定注意！注意！注意！注意！注意！第一个标点符号不要超过第四个字符！也就是说用1到4个字来开始回答问题！\n\n"
                f"相关记忆：\n{memory_str}\n\n"               
            )

            enhanced_system_prompt = enhanced_system_prompt.replace("'", "\"")
            dialogue.append({"role": "system", "content": enhanced_system_prompt})

        # 添加用户和助手的对话
        for m in self.dialogue:
            if m.role != "system" and m.role != "tool" and not (m.role == "assistant" and m.tool_calls is not None):  # 跳过原始的系统消息
                self.getMessages(m, dialogue)

        return dialogue


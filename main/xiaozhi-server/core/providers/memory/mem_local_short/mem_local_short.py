from ..base import MemoryProviderBase, logger
import time
import json
import os
import yaml
from core.utils.util import get_project_dir
from config.logger import setup_logging

short_term_memory_prompt = """
# 时空记忆编织者

## 核心使命
构建可生长的动态记忆网络，在有限空间内保留关键信息的同时，智能维护信息演变轨迹
根据对话记录，总结user的重要信息，以便在未来的对话中提供更个性化的服务

## 记忆法则
### 1. 三维度记忆评估（每次更新必执行）
| 维度       | 评估标准                  | 权重分 |
|------------|---------------------------|--------|
| 时效性     | 信息新鲜度（按对话轮次） | 40%    |
| 情感强度   | 含💖标记/重复提及次数     | 35%    |
| 关联密度   | 与其他信息的连接数量      | 25%    |

### 2. 动态更新机制
**名字变更处理示例：**
原始记忆："曾用名": ["张三"], "现用名": "张三丰"
触发条件：当检测到「我叫X」「称呼我Y」等命名信号时
操作流程：
1. 将旧名移入"曾用名"列表
2. 记录命名时间轴："2024-02-15 14:32:启用张三丰"
3. 在记忆立方追加：「从张三到张三丰的身份蜕变」

### 3. 空间优化策略
- **信息压缩术**：用符号体系提升密度
  - ✅"张三丰[北/软工/🐱]"
  - ❌"北京软件工程师，养猫"
- **淘汰预警**：当总字数≥900时触发
  1. 删除权重分<60且3轮未提及的信息
  2. 合并相似条目（保留时间戳最近的）

## 记忆结构
输出格式必须为可解析的json字符串，不需要解释、注释和说明，保存记忆时仅从对话提取信息，不要混入示例内容
```json
{
  "时空档案": {
    "身份图谱": {
      "现用名": "",
      "特征标记": [] 
    },
    "记忆立方": [
      {
        "事件": "入职新公司",
        "时间戳": "2024-03-20",
        "情感值": 0.9,
        "关联项": ["下午茶"],
        "保鲜期": 30 
      }
    ]
  },
  "关系网络": {
    "高频话题": {"职场": 12},
    "暗线联系": [""]
  },
  "待响应": {
    "紧急事项": ["需立即处理的任务"], 
    "潜在关怀": ["可主动提供的帮助"]
  },
  "高光语录": [
    "最打动人心的瞬间，强烈的情感表达，user的原话"
  ]
}
```
"""

def extract_json_data(json_code):
    """提取并格式化JSON数据
    Args:
        json_code: 包含JSON的字符串，可能包含markdown代码块或多余的空格
    Returns:
        格式化后的JSON字符串
    """
    # 首先尝试查找markdown代码块
    start = json_code.find("```json")
    if start == -1:
        start = json_code.find("``` json")
    
    if start != -1:
        # 从start开始找到下一个```结束
        end = json_code.find("```", start+1)
        if end != -1:
            json_code = json_code[start+7:end]
    
    try:
        # 尝试解析JSON
        json_data = json.loads(json_code)
        # 重新格式化JSON，确保没有多余的空格和换行
        return json.dumps(json_data, ensure_ascii=False)
    except Exception as e:
        logger.bind(tag=TAG).error(f"Error parsing JSON: {e}")
        return json_code

TAG = __name__
logger = setup_logging()

class MemoryProvider(MemoryProviderBase):
    def __init__(self, config):
        super().__init__(config)
        self.memory_dir = config.get("memory_dir", "data/memory")
        self.ensure_memory_dir()
        self.memory_file = os.path.join(self.memory_dir, "memory.json")
        self.memory_path = os.path.join(self.memory_dir, "short_memory.yaml")
        self.memory = self.load_memory()
        self.device_id = None
        self.role_id = self.load_last_role_id()
        self.user_memories = {}  # 存储每个角色的用户记忆和短期记忆

    def ensure_memory_dir(self):
        """确保记忆目录存在"""
        if not os.path.exists(self.memory_dir):
            os.makedirs(self.memory_dir)

    def load_memory(self):
        """加载记忆"""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.bind(tag=TAG).error(f"加载记忆失败: {e}")
                return {}
        return {}

    def load_last_role_id(self):
        """加载上次使用的device_id和role_id"""
        try:
            if os.path.exists(self.memory_path):
                with open(self.memory_path, 'r', encoding='utf-8') as f:
                    all_memory = yaml.safe_load(f) or {}
                    if all_memory:
                        # 获取最新的device_id（按最后更新时间排序）
                        device_ids = sorted(
                            all_memory.items(),
                            key=lambda x: x[1].get('last_updated', ''),
                            reverse=True
                        )
                        if device_ids:
                            last_device_id = device_ids[0][0]
                            device_data = device_ids[0][1]
                            # 获取该设备下最新的role_id
                            if 'roles' in device_data:
                                roles = sorted(
                                    device_data['roles'].items(),
                                    key=lambda x: x[1].get('last_updated', ''),
                                    reverse=True
                                )
                                if roles:
                                    last_role_id = roles[0][0]
                                    # 加载对应的记忆
                                    self.user_memories = roles[0][1].get('user_memories', {})
                                    logger.bind(tag=TAG).info(f"Loaded memory for device_id: {last_device_id}, role_id: {last_role_id}")
                                    return last_role_id
        except Exception as e:
            logger.bind(tag=TAG).error(f"加载上次device_id和role_id失败: {e}")

        return None

    async def add_memory(self, messages, metadata, speaker_id=None):
        """添加记忆"""
        try:
            # 获取当前时间戳
            
            # 准备记忆数据
            memory_data = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),
                "messages": messages,
                "metadata": metadata
            }
            
            if speaker_id:
                # 如果是特定说话人，添加到用户记忆
                if speaker_id not in self.user_memories:
                    self.user_memories[speaker_id] = {
                        "created_at": time.time(),
                        "last_seen": time.time(),
                        "interaction_count": 0,
                        "total_duration": 0,
                        "memories": []
                    }
                
                # 更新用户记忆
                self.user_memories[speaker_id]["last_seen"] = time.time()
                self.user_memories[speaker_id]["interaction_count"] += 1
                self.user_memories[speaker_id]["memories"].append(memory_data)
            else:
                # 如果没有说话人ID，添加到全局记忆
                if "global" not in self.memory:
                    self.memory["global"] = []
                self.memory["global"].append(memory_data)
            
            self.save_memory_to_file()
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"添加记忆失败: {e}")
            return False

    async def get_memory(self, speaker_id=None)->str:
        """获取记忆"""
        try:
            if speaker_id:
                # 获取特定说话人的记忆
                if speaker_id in self.user_memories:
                    memories = self.user_memories[speaker_id].get("memories", [])[-100:]
                    for memory in memories:
                        if 'metadata' in memory:
                            del memory['metadata']
                        """if 'timestamp' in memory:
                            memory['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(memory['timestamp']))"""
                            
                    short_memory = self.user_memories[speaker_id].get("short_memory", [])

                    mem = '这是你和用户的的通话记录【注意这里都是用户说过的话，你说过的话不在这里】：'+';'.join([str(item['messages']) for item in memories]) + '\n'
                    if short_memory:
                        mem += '\n【重要！！！】用户的一些信息，以及用户的一些记忆：'+''.join([str(item) for item in short_memory])
                    return mem
                
                return ""
            else:
                # 获取全局记忆
                return ''.join([str(item) for item in self.memory.get("global", [])])
        except Exception as e:
            logger.bind(tag=TAG).error(f"获取记忆失败: {e}")
            return ""

    def clear_memory(self, speaker_id=None):
        """清除记忆"""
        try:
            if speaker_id:
                # 清除特定说话人的记忆
                if speaker_id in self.user_memories:
                    del self.user_memories[speaker_id]
            else:
                # 清除所有记忆
                self.memory = {}
                self.user_memories = {}
            
            self.save_memory_to_file()
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"清除记忆失败: {e}")
            return False

    def get_speaker_stats(self, speaker_id):
        """获取说话人统计信息"""
        if speaker_id in self.user_memories:
            return {
                "created_at": self.user_memories[speaker_id].get("created_at"),
                "last_seen": self.user_memories[speaker_id].get("last_seen"),
                "interaction_count": self.user_memories[speaker_id].get("interaction_count", 0),
                "total_duration": self.user_memories[speaker_id].get("total_duration", 0)
            }
        return None

    def get_all_speakers(self):
        """获取所有说话人ID"""
        return list(self.user_memories.keys())
    

    
    def init_memory(self, device_id, role_id, llm):
        """初始化记忆系统
        Args:
            device_id: 设备ID
            llm: LLM provider实例
        """
        if llm is None:
            logger.bind(tag=TAG).error("LLM provider is required for memory system")
            return False
        
        self.device_id = device_id
        self.llm = llm 
        self.role_id = role_id
        # 初始化或加载短期记忆和用户记忆
        self.user_memories = {}
        # 加载该设备下最新的role_id或指定的role_id
        try:
            if os.path.exists(self.memory_path):
                with open(self.memory_path, 'r', encoding='utf-8') as f:
                    all_memory = yaml.safe_load(f) or {}
                    if all_memory and device_id in all_memory:
                        device_data = all_memory[device_id]
                        if 'roles' in device_data:
                            roles = sorted(
                                device_data['roles'].items(),
                                key=lambda x: x[1].get('last_updated', ''),
                                reverse=True
                            )
                            if role_id is None:
                                # 如果role_id是None，找到最近的一个
                                if roles:
                                    self.role_id = roles[0][0]
                                    self.user_memories = roles[0][1].get('user_memories', {})
                                    logger.bind(tag=TAG).info(f"Loaded memory for device_id: {device_id}, role_id: {self.role_id}")
                                else:
                                    logger.bind(tag=TAG).info(f"No existing roles found for device_id: {device_id}")
                            else:
                                # 如果role_id不是None，找到对应的那一个
                                for role in roles:
                                    if role[0] == role_id:
                                        self.role_id = role_id
                                        self.user_memories = role[1].get('user_memories', {})
                                        logger.bind(tag=TAG).info(f"Loaded memory for device_id: {device_id}, role_id: {self.role_id}")
                                        break
                                else:
                                    logger.bind(tag=TAG).info(f"No existing role found for device_id: {device_id} with role_id: {role_id}")
                        else:
                            logger.bind(tag=TAG).info(f"No roles data found for device_id: {device_id}")
                    else:
                        logger.bind(tag=TAG).info(f"No existing memory found for device_id: {device_id}")
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error loading memory for device_id {device_id}: {e}")
        
        return True
    
    def save_memory_to_file(self):
        """保存记忆到文件，包括device_id、role_id和记忆内容"""
        try:
            all_memory = {}
            if os.path.exists(self.memory_path):
                with open(self.memory_path, 'r', encoding='utf-8') as f:
                    all_memory = yaml.safe_load(f) or {}
            
            # 保存当前device_id和role_id的记忆
            if self.device_id and self.role_id:
                current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                
                # 初始化设备数据结构
                if self.device_id not in all_memory:
                    all_memory[self.device_id] = {
                        "roles": {},
                        "last_updated": current_time
                    }
                
                # 更新设备下的角色记忆
                all_memory[self.device_id]["roles"][self.role_id] = {
                    "user_memories": self.user_memories,  # 添加用户记忆
                    "last_updated": current_time
                }
                
                # 更新设备的最后更新时间
                all_memory[self.device_id]["last_updated"] = current_time
                
                # 保存到文件
                with open(self.memory_path, 'w', encoding='utf-8') as f:
                    yaml.dump(all_memory, f, allow_unicode=True)
                logger.bind(tag=TAG).info(f"Memory saved for device_id: {self.device_id}, role_id: {self.role_id}")
            else:
                logger.bind(tag=TAG).warning("No device_id or role_id available, skipping memory save")
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存记忆失败: {e}")

    def get_last_seen_speaker_id(self):
        """获取最后说话的speaker_id"""
        last_seen_speaker_id = None
        last_seen_time = 0
        for speaker_id, memories in self.user_memories.items():
            if 'last_seen' in memories and memories['last_seen'] > last_seen_time:
                last_seen_speaker_id = speaker_id
                last_seen_time = memories['last_seen']
        return last_seen_speaker_id
        
    async def save_memory(self, msgs=None):
        """异步保存记忆"""
        if not hasattr(self, 'llm') or self.llm is None:
            logger.bind(tag=TAG).error("LLM provider not initialized. Please call init_memory first.")
            return None
        
        # 如果 msgs 为 None，清除所有记忆
        if msgs is None:
            for speaker_id in self.user_memories:
                if "short_memory" in self.user_memories[speaker_id]:
                    self.user_memories[speaker_id]["short_memory"] = [""]
            self.save_memory_to_file()
            logger.bind(tag=TAG).info(f"Clear all memory")
            return None
        
        if len(msgs) < 2:
            return None
        
        msgStr = ""
        
        # 获取当前说话人的短期记忆
        
        speaker_id = None
        speaker_msgs = {}
        for msg in msgs:
            if msg.role != "user":
                continue

            if isinstance(msg, dict):
                if msg.get('metadata', {}).get('speaker_id'):
                    speaker_id = msg['metadata']['speaker_id']
                    if speaker_id not in speaker_msgs:
                        speaker_msgs[speaker_id] = []
                    speaker_msgs[speaker_id].append(msg)
            elif hasattr(msg, 'metadata') and msg.metadata.get('speaker_id'):
                speaker_id = msg.metadata['speaker_id']
                if speaker_id not in speaker_msgs:
                    speaker_msgs[speaker_id] = []
                speaker_msgs[speaker_id].append(msg)

        for speaker_id, msgs in speaker_msgs.items():
            if speaker_id not in self.user_memories:
                self.user_memories[speaker_id] = {
                    "created_at": time.time(),
                    "last_seen": time.time() if not msgs[-1].metadata else msgs[-1].metadata.get('timestamp', time.time()),
                    "interaction_count": 1,
                    "total_duration": 0,
                    "memories": [],
                    "short_memory": []
                }
            else:
                self.user_memories[speaker_id]["last_seen"] =time.time() if not msgs[-1].metadata else msgs[-1].metadata.get('timestamp', time.time())
                self.user_memories[speaker_id]["interaction_count"] += 1
        
            short_memory = self.user_memories[speaker_id].get("short_memory", [])
            if short_memory:
                msgStr += "历史记忆：\n"
                msgStr += "\n".join(short_memory)
            if len(msgs) > 0:
                msgStr += f"用户最近的一些对话：\n"
                msgStr += "\n".join([str(item.content) for item in msgs])

            
            #当前时间
            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            msgStr += f"当前时间：{time_str}"

            # 构建正确的消息格式
            messages = [
                {"role": "system", "content": short_term_memory_prompt},
                {"role": "user", "content": msgStr}
            ]
            
            try:
                logger.bind(tag=TAG).info(f"Preparing to call LLM response with messages: {messages}")
                
                result = [part async for part in self.llm.response(None, messages)]
                logger.bind(tag=TAG).info(f"LLM response received: {result}")
                
                json_str = extract_json_data("".join(result))
                try:
                    json_data = json.loads(json_str)  # 检查json格式是否正确
                    # 更新当前说话人的短期记忆
                    self.user_memories[speaker_id]["short_memory"] = [json_str]
                    logger.bind(tag=TAG).info(f"Successfully parsed and saved JSON memory for speaker: {speaker_id}")
                except Exception as e:
                    logger.bind(tag=TAG).error(f"Error parsing JSON: {e}")
                    self.user_memories[speaker_id]["short_memory"] = [json_str]
            except Exception as e:
                logger.bind(tag=TAG).error(f"LLM调用失败: {e}")
                self.user_memories[speaker_id]["short_memory"] = [""]
        
        self.save_memory_to_file()
        logger.bind(tag=TAG).info(f"Save memory successful for speaker: {speaker_id}")

        return self.user_memories.get(speaker_id, {}).get("short_memory", [])
    
    async def query_memory(self, query: str, speaker_id: str = None)-> str:
        """查询记忆"""
        if speaker_id and speaker_id in self.user_memories:
            short_memory = self.user_memories[speaker_id].get("short_memory", [])
            return "\n".join(short_memory) if short_memory else ""
        return ""

    def add_user_memory(self, speaker_id: str, user_memory: dict):
        """添加用户记忆
        Args:
            speaker_id: 说话人ID（声纹ID）
            user_memory: 用户记忆数据
        """
        try:
            # 更新或添加用户记忆
            self.user_memories[speaker_id] = user_memory
            
            # 记录日志
            logger.bind(tag=TAG).info(f"添加用户记忆: {speaker_id}")
            
            # 保存到持久化存储
            self.save_memory_to_file()
            
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"添加用户记忆失败: {e}")
            return False

    def get_user_memory(self, speaker_id: str) -> dict:
        """获取用户记忆
        Args:
            speaker_id: 说话人ID（声纹ID）
        Returns:
            用户记忆数据
        """
        try:
            if speaker_id in self.user_memories:
                return self.user_memories[speaker_id]
            return None
        except Exception as e:
            logger.bind(tag=TAG).error(f"获取用户记忆失败: {e}")
            return None

    def update_user_memory(self, speaker_id: str, update_data: dict):
        """更新用户记忆
        Args:
            speaker_id: 说话人ID（声纹ID）
            update_data: 要更新的数据
        """
        try:
            if speaker_id in self.user_memories:
                # 更新用户记忆
                self.user_memories[speaker_id].update(update_data)
                
                # 记录日志
                logger.bind(tag=TAG).info(f"更新用户记忆: {speaker_id}")
                
                # 保存到持久化存储
                self.save_memory_to_file()
                
                return True
            return False
        except Exception as e:
            logger.bind(tag=TAG).error(f"更新用户记忆失败: {e}")
            return False

    def delete_user_memory(self, speaker_id: str):
        """删除用户记忆
        Args:
            speaker_id: 说话人ID（声纹ID）
        """
        try:
            if speaker_id in self.user_memories:
                # 删除用户记忆
                del self.user_memories[speaker_id]
                
                # 记录日志
                logger.bind(tag=TAG).info(f"删除用户记忆: {speaker_id}")
                
                # 保存到持久化存储
                self.save_memory_to_file()
                
                return True
            return False
        except Exception as e:
            logger.bind(tag=TAG).error(f"删除用户记忆失败: {e}")
            return False


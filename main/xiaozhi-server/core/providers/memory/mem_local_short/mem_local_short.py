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
    start = json_code.find("```json")
    # 从start开始找到下一个```结束
    end = json_code.find("```", start+1)
    #print("start:", start, "end:", end)
    if start == -1 or end == -1:
        try:
            jsonData = json.loads(json_code)
            return json_code
        except Exception as e:
            print("Error:", e)
        return ""
    jsonData = json_code[start+7:end]
    return jsonData

TAG = __name__
logger = setup_logging()

class MemoryProvider(MemoryProviderBase):
    def __init__(self, config):
        super().__init__(config)
        self.memory_dir = config.get("memory_dir", "data/memory")
        self.ensure_memory_dir()
        self.memory_file = os.path.join(self.memory_dir, "memory.json")
        self.memory = self.load_memory()
        self.short_memory = []

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

    def add_memory(self, messages, metadata, speaker_id=None):
        """添加记忆"""
        try:
            # 获取当前时间戳
            timestamp = time.time()
            
            # 准备记忆数据
            memory_data = {
                "timestamp": timestamp,
                "messages": messages,
                "metadata": metadata
            }
            
            if speaker_id:
                # 如果是特定说话人，添加到说话人记忆
                self.add_speaker_memory(speaker_id, memory_data)
                
                # 更新说话人统计信息
                if speaker_id not in self.memory:
                    self.memory[speaker_id] = {
                        "created_at": timestamp,
                        "last_seen": timestamp,
                        "interaction_count": 0,
                        "total_duration": 0
                    }
                else:
                    self.memory[speaker_id]["last_seen"] = timestamp
                    self.memory[speaker_id]["interaction_count"] += 1
            else:
                # 如果没有说话人ID，添加到全局记忆
                if "global" not in self.memory:
                    self.memory["global"] = []
                self.memory["global"].append(memory_data)
            
            self.save_memory(messages)
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"添加记忆失败: {e}")
            return False

    def get_memory(self, speaker_id=None):
        """获取记忆"""
        try:
            if speaker_id:
                # 获取特定说话人的记忆
                return self.get_speaker_memory(speaker_id)
            else:
                # 获取全局记忆
                return self.memory.get("global", [])
        except Exception as e:
            logger.bind(tag=TAG).error(f"获取记忆失败: {e}")
            return []

    def clear_memory(self, speaker_id=None):
        """清除记忆"""
        try:
            if speaker_id:
                # 清除特定说话人的记忆
                self.clear_speaker_memory(speaker_id)
                if speaker_id in self.memory:
                    del self.memory[speaker_id]
            else:
                # 清除所有记忆
                self.memory = {}
                self.speaker_memories = {}
            
            self.save_memory()
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"清除记忆失败: {e}")
            return False

    def get_speaker_stats(self, speaker_id):
        """获取说话人统计信息"""
        return self.memory.get(speaker_id, {})

    def get_all_speakers(self):
        """获取所有说话人ID"""
        return [k for k in self.memory.keys() if k != "global"]

    def init_memory(self, role_id, llm):
        super().init_memory(role_id, llm)
        self.load_memory()
    
    def save_memory_to_file(self):
        all_memory = {}
        if os.path.exists(self.memory_path):
              with open(self.memory_path, 'r', encoding='utf-8') as f:
                  all_memory = yaml.safe_load(f) or {}
        all_memory[self.role_id] = self.short_memory
        with open(self.memory_path, 'w', encoding='utf-8') as f:
            yaml.dump(all_memory, f, allow_unicode=True)
        
    def save_memory(self, msgs=None):
        """异步保存记忆"""
        if self.llm is None:
            logger.bind(tag=TAG).error("LLM is not set for memory provider")
            return None
        
        # 如果 msgs 为 None，清除所有记忆
        if msgs is None:
            self.short_memory = ""
            self.save_memory_to_file()
            logger.bind(tag=TAG).info(f"Clear all memory - Role: {self.role_id}")
            return None
        
        if len(msgs) < 2:
            return None
        
        msgStr = ""
        for msg in msgs:
            if msg.role == "user":
                msgStr += f"User: {msg.content}\n"
            elif msg.role== "assistant":
                msgStr += f"Assistant: {msg.content}\n"
        if len(self.short_memory) > 0:
            msgStr+="历史记忆：\n"
            msgStr+=self.short_memory
        
        #当前时间
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        msgStr += f"当前时间：{time_str}"

        result = self.llm.response_no_stream(short_term_memory_prompt, msgStr)
 
        json_str = extract_json_data(result)
        try:
            json_data = json.loads(json_str) # 检查json格式是否正确
            self.short_memory = json_str
        except Exception as e:
            print("Error:", e)
        
        self.save_memory_to_file()
        logger.bind(tag=TAG).info(f"Save memory successful - Role: {self.role_id}")

        return self.short_memory
    
    async def query_memory(self, query: str)-> str:
        return self.short_memory
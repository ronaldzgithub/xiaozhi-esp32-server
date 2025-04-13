import time
from .base import ProactiveDialogueManagerBase, logger

TAG = __name__

class ProactiveDialogueManager(ProactiveDialogueManagerBase):
    def __init__(self, config):
        super().__init__(config)
        self.interest_keywords = config.get("interest_keywords", {
            "music": ["音乐", "歌曲", "播放", "歌"],
            "news": ["新闻", "时事", "热点"],
            "weather": ["天气", "温度", "下雨"],
            "technology": ["科技", "技术", "创新"],
            "life": ["生活", "日常", "习惯"]
        })
        self.recent_memory_window = config.get("recent_memory_window", 5)  # 最近记忆窗口大小

    async def should_initiate_dialogue(self, current_time, conn):
        """判断是否应该发起主动对话"""
        # 检查是否满足最小交互次数
        if self.interaction_count < self.min_interaction_count:
            return False
            
        # 检查沉默时长
        silence_duration = self.get_silence_duration(current_time)
        if silence_duration < self.silence_threshold:
            return False
            

        # 检查系统是否正在说话
        if not conn.asr_server_receive:
            conn.logger.bind(tag=TAG).debug("系统正在说话，跳过主动对话检查")
            return False
            
        return True

    async def generate_proactive_content(self, llm, msgs, short_memory):
        """生成主动对话内容"""
        # 构建提示词
        prompt = f"""基于以下对话历史和短期记忆，生成一个主动对话问题。
                    对话历史: 是个连续的对话，都是用户说过的话， 越往后面的信息越重要。你要特别注意。 
                    {msgs}

                    短期记忆:
                    {short_memory}

                    请生成一个自然、友好的问题，引导用户继续讨论相关的话题。
                    问题应该简短，并且与用户的兴趣相关. 注意，如果你问过了这方面的问题，如果用户没有回答，不要重复问。或者用户明确说不想说这个话题，不要重复问。
                    可以挑一个和用户说过的话题领域是一个领域， 但是不要直接问已经提及的事情。
                    """
        
        # 构建正确的消息格式
        messages = [
            {"role": "system", "content": prompt}
        ]
        
        try:
            logger.bind(tag=TAG).info(f"Preparing to call LLM response with messages: {messages}")
            
            # 使用async for处理异步生成器
            responses = []
            async for response in llm.response(None, messages):
                if response and len(response) > 0:
                    responses.append(response)
            logger.bind(tag=TAG).info(f"Generated proactive content: {responses}")
            return ''.join(responses) or '我们聊点有趣的事情吧'
        except Exception as e:
            logger.bind(tag=TAG).error(f"生成主动对话内容错误: {e}")
            return '我们聊点有趣的事情吧'
            


    async def update_user_interests(self, dialogue_history):
        """更新用户兴趣"""
        try:
            # 初始化兴趣计数
            for topic in self.interest_keywords.keys():
                if topic not in self.user_interests:
                    self.user_interests[topic] = 0
                    
            # 分析对话历史
            for message in dialogue_history:
                if message.role == "user":
                    content = message.content.lower()
                    # 统计关键词出现次数
                    for topic, keywords in self.interest_keywords.items():
                        for keyword in keywords:
                            if keyword in content:
                                self.user_interests[topic] += 1
                                
            # 更新最后主动对话时间
            self.last_proactive_time = time.time()
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"更新用户兴趣错误: {e}") 
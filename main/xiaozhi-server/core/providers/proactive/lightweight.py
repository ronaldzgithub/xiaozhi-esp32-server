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

    async def should_initiate_dialogue(self, current_time):
        """判断是否应该发起主动对话"""
        # 检查是否满足最小交互次数
        if self.interaction_count < self.min_interaction_count:
            return False
            
        # 检查沉默时长
        silence_duration = self.get_silence_duration(current_time)
        if silence_duration < self.silence_threshold:
            return False
            
        # 检查冷却时间
        if current_time - self.last_proactive_time < self.proactive_cooldown:
            return False
            
        return True

    async def generate_proactive_content(self, dialogue_history, user_interests):
        """生成主动对话内容"""
        try:
            # 根据用户兴趣生成主动对话内容
            if not user_interests:
                return "我注意到你有一段时间没说话了，要不要聊聊天？"
                
            # 找出最感兴趣的话题
            max_interest = max(user_interests.items(), key=lambda x: x[1])
            topic = max_interest[0]
            
            # 根据话题生成内容
            if topic == "music":
                return "我注意到你对音乐很感兴趣，要不要听听歌？"
            elif topic == "news":
                return "最近有一些有趣的新闻，想听听吗？"
            elif topic == "weather":
                return "今天天气不错，要不要聊聊天气？"
            elif topic == "technology":
                return "最近科技发展很快，有什么想法吗？"
            elif topic == "life":
                return "生活中有趣的事情很多，想聊聊吗？"
            else:
                return "我注意到你有一段时间没说话了，要不要聊聊天？"
                
        except Exception as e:
            logger.bind(tag=TAG).error(f"生成主动对话内容错误: {e}")
            return "我注意到你有一段时间没说话了，要不要聊聊天？"

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
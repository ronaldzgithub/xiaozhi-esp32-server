from typing import Dict, Optional
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

class RoleWizard:
    def __init__(self, role_manager):
        self.role_manager = role_manager
        self.current_step = 0
        self.role_data = {}
        self.available_voices = self.role_manager.get_available_voices()

    def start_creation(self) -> str:
        """开始创建角色流程"""
        self.current_step = 0
        self.role_data = {}
        return self.get_next_question()

    def get_next_question(self) -> str:
        """获取下一个问题"""
        questions = [
            "请告诉我这个角色的名字是什么？",
            "这个角色的主要职能是什么？",
            "这个角色的性别是什么？(男/女)",
            "这个角色的年龄大概是多少？(年轻/中年/老年)",
            "这个角色的性格特点是什么？",
            "这个角色的说话风格是什么？(温柔/活泼/严肃等)",
            "这个角色的音色特点是什么？(从以下选项中选择：\n" + 
            "\n".join([f"- {voice['name']} ({voice['features'].get('style', '未知')})" 
                      for voice in self.available_voices]) + ")",
            "这个角色的语言特点是什么？(普通话/方言/英语等)",
            "这个角色的专业领域是什么？",
            "您对这个角色有什么特别的期望或要求？"
        ]
        
        if self.current_step < len(questions):
            return questions[self.current_step]
        return None

    def process_answer(self, answer: str) -> Optional[str]:
        """处理用户回答"""
        if not answer:
            return "请回答我的问题。"

        # 根据当前步骤处理答案
        if self.current_step == 0:  # 角色名字
            self.role_data['name'] = answer
        elif self.current_step == 1:  # 职能
            self.role_data['function'] = answer
        elif self.current_step == 2:  # 性别
            self.role_data['gender'] = answer
        elif self.current_step == 3:  # 年龄
            self.role_data['age'] = answer
        elif self.current_step == 4:  # 性格
            self.role_data['personality'] = answer
        elif self.current_step == 5:  # 说话风格
            self.role_data['speaking_style'] = answer
        elif self.current_step == 6:  # 音色
            # 验证选择的音色是否有效
            selected_voice = None
            for voice in self.available_voices:
                if voice['name'] in answer:
                    selected_voice = voice
                    break
            if not selected_voice:
                return "请从提供的音色选项中选择一个。"
            self.role_data['voice'] = selected_voice['id']
        elif self.current_step == 7:  # 语言特点
            self.role_data['language'] = answer
        elif self.current_step == 8:  # 专业领域
            self.role_data['expertise'] = answer
        elif self.current_step == 9:  # 期望
            self.role_data['expectations'] = answer

        # 移动到下一步
        self.current_step += 1
        next_question = self.get_next_question()
        
        if not next_question:
            # 所有问题都已回答，创建角色
            try:
                role_id = self.role_manager.create_role(self.role_data)
                return f"角色创建成功！角色ID为：{role_id}。您可以使用'切换角色'命令来使用这个新角色。"
            except Exception as e:
                return f"创建角色失败：{str(e)}"
        
        return next_question

    def cancel_creation(self):
        """取消角色创建"""
        self.current_step = 0
        self.role_data = {} 
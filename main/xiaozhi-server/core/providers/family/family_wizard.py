from config.logger import setup_logging
import time

TAG = __name__
logger = setup_logging()

class FamilyMemberWizard:
    def __init__(self, family_manager):
        self.family_manager = family_manager
        self.current_step = 0
        self.member_count = 0
        self.is_setting_up = False

    def start_setup(self):
        """开始设置家庭成员"""
        self.is_setting_up = True
        self.current_step = 0
        self.member_count = 0
        logger.bind(tag=TAG).info("开始设置家庭成员")

    def finish_setup(self):
        """完成设置家庭成员"""
        self.is_setting_up = False
        self.current_step = 0
        logger.bind(tag=TAG).info("完成设置家庭成员")

    def cancel_setup(self):
        """取消设置家庭成员"""
        self.is_setting_up = False
        self.current_step = 0
        logger.bind(tag=TAG).info("取消设置家庭成员")

    def is_in_setup_mode(self):
        """是否处于设置模式"""
        return self.is_setting_up

    def get_next_member_name(self):
        """获取下一个成员的名称"""
        self.member_count += 1
        return f"成员{self.member_count}"

    def get_current_step(self):
        """获取当前步骤"""
        return self.current_step

    def advance_step(self):
        """前进到下一步"""
        self.current_step += 1

    def get_setup_status(self):
        """获取设置状态"""
        return {
            "is_setting_up": self.is_setting_up,
            "current_step": self.current_step,
            "member_count": self.member_count
        } 
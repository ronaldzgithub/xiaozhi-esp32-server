from config.logger import setup_logging
import json
import os
import time

TAG = __name__
logger = setup_logging()

class FamilyManager:
    def __init__(self, config):
        self.config = config
        self.family_dir = config.get("family_dir", "data/family")
        self.ensure_family_dir()
        self.family_file = os.path.join(self.family_dir, "family.json")
        self.family_members = self.load_family_members()
        self.is_adding_member = False
        self.current_member_name = None

    def ensure_family_dir(self):
        """确保家庭成员目录存在"""
        if not os.path.exists(self.family_dir):
            os.makedirs(self.family_dir)

    def load_family_members(self):
        """加载家庭成员信息"""
        try:
            if os.path.exists(self.family_file):
                with open(self.family_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.bind(tag=TAG).error(f"加载家庭成员信息失败: {e}")
            return {}

    def save_family_members(self):
        """保存家庭成员信息"""
        try:
            with open(self.family_file, 'w', encoding='utf-8') as f:
                json.dump(self.family_members, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存家庭成员信息失败: {e}")

    def start_adding_member(self, member_name):
        """开始添加新成员"""
        self.is_adding_member = True
        self.current_member_name = member_name
        logger.bind(tag=TAG).info(f"开始添加新成员: {member_name}")

    def finish_adding_member(self, voiceprint_data):
        """完成添加新成员"""
        if self.current_member_name:
            self.family_members[self.current_member_name] = {
                "voiceprint": voiceprint_data,
                "added_time": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            self.save_family_members()
            logger.bind(tag=TAG).info(f"成功添加新成员: {self.current_member_name}")
        self.is_adding_member = False
        self.current_member_name = None

    def cancel_adding_member(self):
        """取消添加新成员"""
        self.is_adding_member = False
        self.current_member_name = None
        logger.bind(tag=TAG).info("取消添加新成员")

    def get_family_members(self):
        """获取所有家庭成员"""
        return self.family_members

    def is_in_adding_mode(self):
        """是否处于添加成员模式"""
        return self.is_adding_member 
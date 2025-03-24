import os
import json
import time
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

class VoiceprintStorage:
    def __init__(self, storage_dir="data/voiceprints"):
        self.storage_dir = storage_dir
        self.ensure_storage_dir()
        self.speaker_info_file = os.path.join(storage_dir, "speaker_info.json")
        self.speaker_info = self.load_speaker_info()

    def ensure_storage_dir(self):
        """确保存储目录存在"""
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

    def load_speaker_info(self):
        """加载说话人信息"""
        if os.path.exists(self.speaker_info_file):
            try:
                with open(self.speaker_info_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.bind(tag=TAG).error(f"加载说话人信息失败: {e}")
                return {}
        return {}

    def save_speaker_info(self):
        """保存说话人信息"""
        try:
            with open(self.speaker_info_file, 'w', encoding='utf-8') as f:
                json.dump(self.speaker_info, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存说话人信息失败: {e}")

    def get_speaker_voiceprint_file(self, speaker_id):
        """获取说话人声纹特征文件路径"""
        return os.path.join(self.storage_dir, f"{speaker_id}.npy")

    def save_voiceprint(self, speaker_id, voiceprint):
        """保存声纹特征"""
        try:
            file_path = self.get_speaker_voiceprint_file(speaker_id)
            import numpy as np
            np.save(file_path, voiceprint)
            
            # 更新说话人信息
            if speaker_id not in self.speaker_info:
                self.speaker_info[speaker_id] = {
                    "created_at": time.time(),
                    "last_seen": time.time(),
                    "interaction_count": 0,
                    "total_duration": 0
                }
            else:
                self.speaker_info[speaker_id]["last_seen"] = time.time()
            
            self.save_speaker_info()
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存声纹特征失败: {e}")
            return False

    def load_voiceprint(self, speaker_id):
        """加载声纹特征"""
        try:
            file_path = self.get_speaker_voiceprint_file(speaker_id)
            if os.path.exists(file_path):
                import numpy as np
                return np.load(file_path)
            return None
        except Exception as e:
            logger.bind(tag=TAG).error(f"加载声纹特征失败: {e}")
            return None

    def update_speaker_stats(self, speaker_id, duration):
        """更新说话人统计信息"""
        if speaker_id in self.speaker_info:
            self.speaker_info[speaker_id]["interaction_count"] += 1
            self.speaker_info[speaker_id]["total_duration"] += duration
            self.speaker_info[speaker_id]["last_seen"] = time.time()
            self.save_speaker_info()

    def get_speaker_stats(self, speaker_id):
        """获取说话人统计信息"""
        return self.speaker_info.get(speaker_id, {})

    def get_all_speakers(self):
        """获取所有说话人ID"""
        return list(self.speaker_info.keys())

    def delete_speaker(self, speaker_id):
        """删除说话人信息"""
        try:
            # 删除声纹特征文件
            file_path = self.get_speaker_voiceprint_file(speaker_id)
            if os.path.exists(file_path):
                os.remove(file_path)
            
            # 删除说话人信息
            if speaker_id in self.speaker_info:
                del self.speaker_info[speaker_id]
                self.save_speaker_info()
            return True
        except Exception as e:
            logger.bind(tag=TAG).error(f"删除说话人信息失败: {e}")
            return False 
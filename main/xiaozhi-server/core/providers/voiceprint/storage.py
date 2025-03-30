import os
import json
import shutil
import time
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

class VoiceprintStorage:
    def __init__(self, storage_dir):
        self.storage_dir = storage_dir
        self.voiceprints_dir = os.path.join(storage_dir, "voiceprints")
        self.stats_file = os.path.join(storage_dir, "speaker_stats.json")
        self._ensure_dirs()
        self._load_stats()

    def _ensure_dirs(self):
        """确保必要的目录存在"""
        try:
            os.makedirs(self.storage_dir, exist_ok=True)
            os.makedirs(self.voiceprints_dir, exist_ok=True)
        except Exception as e:
            logger.bind(tag=TAG).error(f"创建存储目录失败: {e}")

    def _load_stats(self):
        """加载说话人统计信息"""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f)
            else:
                self.stats = {}
        except Exception as e:
            logger.bind(tag=TAG).error(f"加载统计信息失败: {e}")
            self.stats = {}

    def _save_stats(self):
        """保存说话人统计信息"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存统计信息失败: {e}")

    def _get_speaker_dir(self, speaker_id):
        """获取说话人的存储目录"""
        return os.path.join(self.voiceprints_dir, speaker_id)

    def save_voiceprint(self, speaker_id, audio_file):
        """保存声纹文件"""
        try:
            speaker_dir = self._get_speaker_dir(speaker_id)
            os.makedirs(speaker_dir, exist_ok=True)
            
            # 生成唯一的文件名
            timestamp = int(time.time())
            filename = f"voiceprint_{timestamp}.wav"
            target_path = os.path.join(speaker_dir, filename)
            
            # 复制音频文件
            shutil.copy2(audio_file, target_path)
            
            # 更新统计信息
            if speaker_id not in self.stats:
                self.stats[speaker_id] = {
                    "total_duration": 0,
                    "voiceprint_count": 0,
                    "last_updated": timestamp
                }
            self.stats[speaker_id]["voiceprint_count"] += 1
            self._save_stats()
            
            return target_path
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"保存声纹文件失败: {e}")
            return None

    def load_voiceprint(self, speaker_id):
        """加载说话人的声纹文件"""
        try:
            speaker_dir = self._get_speaker_dir(speaker_id)
            if not os.path.exists(speaker_dir):
                return None
                
            # 获取所有声纹文件
            voiceprint_files = []
            for filename in os.listdir(speaker_dir):
                if filename.endswith('.wav'):
                    voiceprint_files.append(os.path.join(speaker_dir, filename))
            
            return voiceprint_files if voiceprint_files else None
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"加载声纹文件失败: {e}")
            return None

    def get_all_speakers(self):
        """获取所有说话人ID"""
        try:
            return [d for d in os.listdir(self.voiceprints_dir) 
                   if os.path.isdir(os.path.join(self.voiceprints_dir, d))]
        except Exception as e:
            logger.bind(tag=TAG).error(f"获取说话人列表失败: {e}")
            return []

    def get_speaker_stats(self, speaker_id):
        """获取说话人统计信息"""
        return self.stats.get(speaker_id, {
            "total_duration": 0,
            "voiceprint_count": 0,
            "last_updated": 0
        })

    def update_speaker_stats(self, speaker_id, duration):
        """更新说话人统计信息"""
        try:
            if speaker_id not in self.stats:
                self.stats[speaker_id] = {
                    "total_duration": 0,
                    "voiceprint_count": 0,
                    "last_updated": int(time.time())
                }
            
            self.stats[speaker_id]["total_duration"] += duration
            self.stats[speaker_id]["last_updated"] = int(time.time())
            self._save_stats()
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"更新统计信息失败: {e}")

    def delete_speaker(self, speaker_id):
        """删除说话人及其所有声纹文件"""
        try:
            speaker_dir = self._get_speaker_dir(speaker_id)
            if os.path.exists(speaker_dir):
                shutil.rmtree(speaker_dir)
            
            if speaker_id in self.stats:
                del self.stats[speaker_id]
                self._save_stats()
            
            return True
            
        except Exception as e:
            logger.bind(tag=TAG).error(f"删除说话人失败: {e}")
            return False 
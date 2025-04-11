import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger(__name__)

@dataclass
class PerformanceMetrics:
    total_requests: int = 0
    total_time: float = 0.0
    avg_response_time: float = 0.0
    max_response_time: float = 0.0
    min_response_time: float = float('inf')
    error_count: int = 0
    cache_hits: int = 0
    tts_time: float = 0.0
    llm_time: float = 0.0

class PerformanceMonitor:
    def __init__(self, window_size: int = 100):
        self.metrics = PerformanceMetrics()
        self.response_times = deque(maxlen=window_size)
        self.start_time: Optional[float] = None
        self.tts_start_time: Optional[float] = None
        self.llm_start_time: Optional[float] = None
        
    def start_request(self):
        """开始记录请求"""
        self.start_time = time.time()
        self.metrics.total_requests += 1
        
    def start_tts(self):
        """开始记录TTS处理"""
        self.tts_start_time = time.time()
        
    def end_tts(self):
        """结束记录TTS处理"""
        if self.tts_start_time:
            tts_time = time.time() - self.tts_start_time
            self.metrics.tts_time += tts_time
            self.tts_start_time = None
            
    def start_llm(self):
        """开始记录LLM处理"""
        self.llm_start_time = time.time()
        
    def end_llm(self):
        """结束记录LLM处理"""
        if self.llm_start_time:
            llm_time = time.time() - self.llm_start_time
            self.metrics.llm_time += llm_time
            self.llm_start_time = None
            
    def end_request(self, success: bool = True):
        """结束记录请求"""
        if self.start_time:
            response_time = time.time() - self.start_time
            self.response_times.append(response_time)
            self.metrics.total_time += response_time
            
            # 更新统计信息
            self.metrics.avg_response_time = sum(self.response_times) / len(self.response_times)
            self.metrics.max_response_time = max(self.response_times)
            self.metrics.min_response_time = min(self.response_times)
            
            if not success:
                self.metrics.error_count += 1
                
            self.start_time = None
            
    def record_cache_hit(self):
        """记录缓存命中"""
        self.metrics.cache_hits += 1
        
    def get_metrics(self) -> Dict:
        """获取性能指标"""
        return {
            "total_requests": self.metrics.total_requests,
            "avg_response_time": self.metrics.avg_response_time,
            "max_response_time": self.metrics.max_response_time,
            "min_response_time": self.metrics.min_response_time,
            "error_count": self.metrics.error_count,
            "cache_hit_rate": self.metrics.cache_hits / self.metrics.total_requests if self.metrics.total_requests > 0 else 0,
            "tts_time": self.metrics.tts_time,
            "llm_time": self.metrics.llm_time
        }
        
    def log_metrics(self):
        """记录性能指标"""
        metrics = self.get_metrics()
        logger.info("Performance Metrics:")
        for key, value in metrics.items():
            logger.info(f"{key}: {value}")
            
    def reset(self):
        """重置性能指标"""
        self.metrics = PerformanceMetrics()
        self.response_times.clear()
        self.start_time = None
        self.tts_start_time = None
        self.llm_start_time = None 
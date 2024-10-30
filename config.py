# config.py

import os

PERFORMANCE_SETTINGS = {
    'max_threads': os.cpu_count(),
    'memory_limit_percentage': 80,  # 최대 메모리 사용률
    'chunk_size': 1024 * 1024,  # 파일 처리 청크 크기
    'buffer_size': 4096,  # FFmpeg 버퍼 크기
    'enable_gpu': True,  # GPU 가속 사용 여부
    'process_priority': 'above_normal'  # 프로세스 우선순위
}
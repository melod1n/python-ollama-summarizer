import threading
from typing import Dict, List
import tiktoken

encoding = tiktoken.get_encoding("cl100k_base")

task_queue: List[str] = []
task_status: Dict[str, Dict] = {}
queue_lock = threading.Lock()

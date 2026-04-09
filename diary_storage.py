"""
日记存储 - JSON 文件持久化

存储结构:
  data/
    diaries/
      2025-01.json   # 按月份存储
      2025-02.json
    collector_state.json  # 收集器当天状态备份
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("diary_storage")


class DiaryStorage:
    """日记持久化存储"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.diary_dir = os.path.join(data_dir, 'diaries')
        self.state_file = os.path.join(data_dir, 'collector_state.json')
        os.makedirs(self.diary_dir, exist_ok=True)

    def save_diary(self, date: str, diary_entry: dict):
        """保存一篇日记

        Args:
            date: 日期字符串 YYYY-MM-DD
            diary_entry: 日记条目 dict
        """
        # 按月份存储
        month_key = date[:7]  # YYYY-MM
        month_file = os.path.join(self.diary_dir, f'{month_key}.json')

        # 加载已有数据
        month_data = self._load_month(month_file)

        # 写入/覆盖当天日记
        month_data[date] = diary_entry

        # 保存
        self._save_json(month_file, month_data)
        logger.info(f"[Diary] 已保存 {date} 的日记")

    def get_diary(self, date: str) -> Optional[dict]:
        """获取指定日期的日记"""
        month_key = date[:7]
        month_file = os.path.join(self.diary_dir, f'{month_key}.json')
        month_data = self._load_month(month_file)
        return month_data.get(date)

    def get_recent_diaries(self, count: int = 7) -> list[dict]:
        """获取最近 N 天的日记"""
        diaries = []
        today = datetime.now()

        for i in range(count):
            date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            diary = self.get_diary(date)
            if diary:
                diaries.append({'date': date, **diary})

        return diaries

    def get_month_diaries(self, year: int, month: int) -> dict:
        """获取某个月的所有日记"""
        month_key = f'{year:04d}-{month:02d}'
        month_file = os.path.join(self.diary_dir, f'{month_key}.json')
        return self._load_month(month_file)

    def get_diary_dates(self, year: int = None, month: int = None) -> list[str]:
        """获取有日记的日期列表"""
        dates = []
        if year and month:
            month_key = f'{year:04d}-{month:02d}'
            month_file = os.path.join(self.diary_dir, f'{month_key}.json')
            data = self._load_month(month_file)
            dates = sorted(data.keys())
        else:
            # 扫描所有月份文件
            if os.path.exists(self.diary_dir):
                for fname in sorted(os.listdir(self.diary_dir)):
                    if fname.endswith('.json') and len(fname) == 12:  # YYYY-MM.json
                        fpath = os.path.join(self.diary_dir, fname)
                        data = self._load_month(fpath)
                        dates.extend(sorted(data.keys()))
        return dates

    def get_diary_count(self) -> int:
        """获取日记总数"""
        return len(self.get_diary_dates())

    def search_diaries(self, keyword: str, limit: int = 10) -> list[dict]:
        """搜索包含关键词的日记"""
        results = []
        all_dates = self.get_diary_dates()

        # 从最近的开始搜索
        for date in reversed(all_dates):
            diary = self.get_diary(date)
            if diary and keyword in diary.get('content', ''):
                results.append({'date': date, **diary})
                if len(results) >= limit:
                    break

        return results

    # ===== 收集器状态备份 =====

    def save_collector_state(self, events_data: list[dict]):
        """备份收集器当天的事件数据 (防止意外重启丢失)"""
        state = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'saved_at': datetime.now().isoformat(),
            'events': events_data,
        }
        self._save_json(self.state_file, state)

    def load_collector_state(self) -> Optional[dict]:
        """加载收集器状态备份"""
        if not os.path.exists(self.state_file):
            return None
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            # 只返回今天的状态
            if state.get('date') == datetime.now().strftime('%Y-%m-%d'):
                return state
            return None
        except Exception as e:
            logger.error(f"[Diary] 加载收集器状态失败: {e}")
            return None

    def clear_collector_state(self):
        """清除收集器状态备份"""
        if os.path.exists(self.state_file):
            try:
                os.remove(self.state_file)
            except Exception:
                pass

    # ===== 内部方法 =====

    def _load_month(self, filepath: str) -> dict:
        """加载月份文件"""
        if not os.path.exists(filepath):
            return {}
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[Diary] 加载失败 {filepath}: {e}")
            return {}

    def _save_json(self, filepath: str, data):
        """保存 JSON 文件"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Diary] 保存失败 {filepath}: {e}")

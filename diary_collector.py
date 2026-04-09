"""
事件收集器 - 全天候记录机器人经历的事件

收集维度:
  1. 群聊互动事件 (谁说了什么、和谁聊了什么话题)
  2. 情绪变化事件 (心情波动的原因)
  3. 重要对话事件 (有意义的交流、被夸/被骂/被问问题)
  4. 特殊事件 (新人出现、话题转变、有趣的事)
  5. 机器人自身行为 (回复了什么、帮了谁)

每个事件带有时间戳、重要度评分、分类标签，供日记生成器筛选使用。
"""
import time
import re
from datetime import datetime
from typing import Optional


# 事件重要度判定关键词
IMPORTANT_KEYWORDS = [
    # 情感类 - 被夸/被骂/表白/感谢
    (r'谢谢|感谢|爱你|喜欢你|好棒|厉害|可爱|辛苦了', 'praised', 0.8),
    (r'滚|闭嘴|傻|笨|蠢|垃圾|废物|讨厌|烦死', 'scolded', 0.9),
    # 求助类 - 有人来问问题
    (r'怎么|如何|为什么|能不能|可以吗|帮我|请问|求助|教我', 'asked_help', 0.7),
    # 个人信息类 - 有人分享了自己的事
    (r'我(叫|是|名字|今天|昨天|刚才|最近)', 'personal_share', 0.6),
    # 话题类 - 有趣的讨论
    (r'你们(觉得|认为|知道|听说)', 'group_discussion', 0.5),
    # 特殊互动
    (r'@|提到了你|叫你', 'mentioned', 0.7),
    # 日常问候
    (r'早上好|晚安|午安|早安|晚上好', 'greeting', 0.4),
    # 有趣/搞笑
    (r'哈哈哈|笑死|绝了|离谱|草|6{3,}|好家伙', 'funny_moment', 0.5),
]

# 编译正则
IMPORTANT_PATTERNS = [(re.compile(p), tag, score) for p, tag, score in IMPORTANT_KEYWORDS]


class DiaryEvent:
    """单个事件记录"""

    def __init__(
        self,
        timestamp: float,
        event_type: str,
        session_id: str,
        summary: str,
        importance: float = 0.5,
        user_id: str = None,
        user_name: str = None,
        raw_message: str = None,
        bot_reply: str = None,
        mood_at_time: str = None,
        tags: list = None,
    ):
        self.timestamp = timestamp
        self.event_type = event_type  # chat/reply/emotion_change/special
        self.session_id = session_id
        self.summary = summary
        self.importance = importance
        self.user_id = user_id
        self.user_name = user_name
        self.raw_message = raw_message
        self.bot_reply = bot_reply
        self.mood_at_time = mood_at_time
        self.tags = tags or []

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'time_str': datetime.fromtimestamp(self.timestamp).strftime('%H:%M'),
            'event_type': self.event_type,
            'session_id': self.session_id,
            'summary': self.summary,
            'importance': self.importance,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'raw_message': self.raw_message,
            'bot_reply': self.bot_reply,
            'mood_at_time': self.mood_at_time,
            'tags': self.tags,
        }

    @staticmethod
    def from_dict(d: dict) -> 'DiaryEvent':
        return DiaryEvent(
            timestamp=d['timestamp'],
            event_type=d['event_type'],
            session_id=d['session_id'],
            summary=d['summary'],
            importance=d.get('importance', 0.5),
            user_id=d.get('user_id'),
            user_name=d.get('user_name'),
            raw_message=d.get('raw_message'),
            bot_reply=d.get('bot_reply'),
            mood_at_time=d.get('mood_at_time'),
            tags=d.get('tags', []),
        )


class DiaryCollector:
    """全天事件收集器"""

    def __init__(self):
        # 当天事件列表
        self.today_events: list[DiaryEvent] = []
        # 当天日期标记，用于自动清理
        self.current_date: str = datetime.now().strftime('%Y-%m-%d')
        # 会话消息计数 (用于判断活跃度)
        self.session_msg_count: dict[str, int] = {}
        # 会话话题追踪
        self.session_topics: dict[str, list[str]] = {}
        # 互动用户追踪
        self.interacted_users: dict[str, int] = {}  # user_name -> count
        # 情绪变化记录
        self.mood_changes: list[dict] = []
        # 机器人回复计数
        self.bot_reply_count: int = 0

    def check_new_day(self):
        """检查是否跨天，如果是则返回昨天的事件并清空"""
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self.current_date:
            yesterday_events = self.today_events.copy()
            yesterday_date = self.current_date
            # 重置
            self.today_events = []
            self.current_date = today
            self.session_msg_count = {}
            self.session_topics = {}
            self.interacted_users = {}
            self.mood_changes = []
            self.bot_reply_count = 0
            return yesterday_date, yesterday_events
        return None, None

    def record_user_message(
        self,
        session_id: str,
        user_id: str,
        user_name: str,
        message: str,
        current_mood: str = None,
    ):
        """记录用户消息，分析是否为重要事件"""
        now = time.time()

        # 更新计数
        self.session_msg_count[session_id] = self.session_msg_count.get(session_id, 0) + 1
        self.interacted_users[user_name] = self.interacted_users.get(user_name, 0) + 1

        # 分析消息重要度
        importance = 0.2  # 基础重要度
        tags = []
        event_type = 'chat'

        for pattern, tag, score in IMPORTANT_PATTERNS:
            if pattern.search(message):
                importance = max(importance, score)
                tags.append(tag)

        # 长消息可能更重要
        if len(message) > 50:
            importance = min(1.0, importance + 0.1)

        # 只记录有一定重要度的事件 (过滤纯水群消息)
        if importance >= 0.4 or tags:
            summary = self._build_message_summary(user_name, message, tags)
            event = DiaryEvent(
                timestamp=now,
                event_type=event_type,
                session_id=session_id,
                summary=summary,
                importance=importance,
                user_id=user_id,
                user_name=user_name,
                raw_message=message[:200],  # 截断过长消息
                mood_at_time=current_mood,
                tags=tags,
            )
            self.today_events.append(event)

    def record_bot_reply(
        self,
        session_id: str,
        reply_text: str,
        reply_to_user: str = None,
        current_mood: str = None,
    ):
        """记录机器人自己的回复"""
        now = time.time()
        self.bot_reply_count += 1

        # 只记录有实质内容的回复 (不记录纯 "嗯" "好" 之类的)
        if len(reply_text.strip()) <= 3:
            return

        summary = f'我回复了{reply_to_user or "群友"}: "{reply_text[:80]}"'
        event = DiaryEvent(
            timestamp=now,
            event_type='reply',
            session_id=session_id,
            summary=summary,
            importance=0.4,
            user_name=reply_to_user,
            bot_reply=reply_text[:200],
            mood_at_time=current_mood,
            tags=['bot_reply'],
        )
        self.today_events.append(event)

    def record_mood_change(self, old_mood: str, new_mood: str, trigger: str = None):
        """记录情绪变化"""
        if old_mood == new_mood:
            return

        now = time.time()
        self.mood_changes.append({
            'time': now,
            'from': old_mood,
            'to': new_mood,
            'trigger': trigger,
        })

        summary = f'心情从{self._mood_cn(old_mood)}变成了{self._mood_cn(new_mood)}'
        if trigger:
            summary += f'，因为{trigger}'

        event = DiaryEvent(
            timestamp=now,
            event_type='emotion_change',
            session_id='',
            summary=summary,
            importance=0.7,
            mood_at_time=new_mood,
            tags=['mood_change'],
        )
        self.today_events.append(event)

    def record_special_event(self, summary: str, importance: float = 0.8, tags: list = None):
        """记录特殊事件 (可由其他插件调用)"""
        event = DiaryEvent(
            timestamp=time.time(),
            event_type='special',
            session_id='',
            summary=summary,
            importance=importance,
            tags=tags or ['special'],
        )
        self.today_events.append(event)

    def get_today_summary_data(self) -> dict:
        """获取今天的汇总数据，供日记生成器使用"""
        events = self.today_events
        if not events:
            return {
                'date': self.current_date,
                'total_events': 0,
                'events': [],
                'stats': {},
            }

        # 按重要度排序，取最重要的事件
        sorted_events = sorted(events, key=lambda e: e.importance, reverse=True)

        # 统计数据
        total_sessions = len(self.session_msg_count)
        total_messages = sum(self.session_msg_count.values())
        top_users = sorted(
            self.interacted_users.items(), key=lambda x: x[1], reverse=True
        )[:5]

        # 时间线 (按时间排序的重要事件)
        timeline = sorted(
            [e for e in events if e.importance >= 0.4],
            key=lambda e: e.timestamp,
        )

        # 情绪轨迹
        mood_timeline = []
        for mc in self.mood_changes:
            mood_timeline.append({
                'time': datetime.fromtimestamp(mc['time']).strftime('%H:%M'),
                'from': self._mood_cn(mc['from']),
                'to': self._mood_cn(mc['to']),
                'trigger': mc.get('trigger', ''),
            })

        return {
            'date': self.current_date,
            'total_events': len(events),
            'important_events': [e.to_dict() for e in sorted_events[:20]],
            'timeline': [e.to_dict() for e in timeline[:30]],
            'stats': {
                'active_sessions': total_sessions,
                'total_messages_seen': total_messages,
                'bot_replies': self.bot_reply_count,
                'top_interacted_users': [
                    {'name': name, 'count': count} for name, count in top_users
                ],
                'mood_changes': mood_timeline,
            },
        }

    def _build_message_summary(self, user_name: str, message: str, tags: list) -> str:
        """构建消息摘要"""
        msg_short = message[:60] if len(message) > 60 else message
        if 'praised' in tags:
            return f'{user_name}夸了我: "{msg_short}"'
        if 'scolded' in tags:
            return f'{user_name}骂了我: "{msg_short}"'
        if 'asked_help' in tags:
            return f'{user_name}来问我问题: "{msg_short}"'
        if 'personal_share' in tags:
            return f'{user_name}分享了自己的事: "{msg_short}"'
        if 'greeting' in tags:
            return f'{user_name}跟我打招呼: "{msg_short}"'
        if 'funny_moment' in tags:
            return f'群里出现了好笑的事，{user_name}说: "{msg_short}"'
        if 'mentioned' in tags:
            return f'{user_name}提到了我: "{msg_short}"'
        if 'group_discussion' in tags:
            return f'群里在讨论，{user_name}说: "{msg_short}"'
        return f'{user_name}说: "{msg_short}"'

    @staticmethod
    def _mood_cn(mood: str) -> str:
        """心情英文转中文"""
        mood_map = {
            'ecstatic': '狂喜', 'excited': '兴奋', 'content': '满足',
            'happy': '开心', 'neutral': '平静', 'sleepy': '困倦',
            'bored': '无聊', 'anxious': '焦虑', 'angry': '生气',
            'sad': '难过', 'upset': '沮丧',
        }
        return mood_map.get(mood, mood or '平静')

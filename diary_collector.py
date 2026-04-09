"""
事件收集器 - 全天候记录机器人经历的事件

收集维度:
  1. 群聊互动事件 (谁说了什么、和谁聊了什么话题)
  2. 情绪变化事件 (心情波动的原因)
  3. 重要对话事件 (有意义的交流、被夸/被骂/被问问题)
  4. 特殊事件 (新人出现、话题转变、有趣的事)
  5. 机器人自身行为 (回复了什么、帮了谁)
  6. 机器人日常生活 (从自己说的话中提取: 晒太阳、吃东西、散步等)

每个事件带有时间戳、重要度评分、分类标签，供日记生成器筛选使用。
"""
import time
import re
from datetime import datetime
from typing import Optional


# 事件重要度判定关键词 (用户消息)
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


# ===== 机器人日常生活关键词 =====
# 从机器人自己说的话中提取日常活动
# 格式: (正则, 活动分类标签, 重要度)
# 这些是机器人"自述"做了什么事，比如"我刚晒了会太阳""吃了个苹果"
BOT_DAILY_LIFE_PATTERNS = [
    # 饮食相关
    (r'吃了|吃过|吃完|喝了|喝过|喝完|饿了|没吃|没喝|泡了.{0,4}茶|煮了|做了.{0,4}饭', 'eating'),
    # 休息/睡眠
    (r'睡了|醒了|刚醒|起来了|起床|午睡|打了个盹|没睡好|失眠|困了|休息', 'sleeping'),
    # 户外/天气/环境
    (r'晒太阳|晒了|出去|出门|散步|走了走|外面|下雨|下雪|天气|风好大|好热|好冷|好暖', 'outdoor'),
    # 身体状态
    (r'蜕皮|不舒服|头疼|头痛|肚子|难受|好多了|好点了|有点累|精神不好|状态不好|状态不错', 'body_state'),
    # 日常活动
    (r'看了|在看|刷了|听了|在听|玩了|在玩|画了|写了|收拾|打扫|洗了|整理', 'activity'),
    # 情绪/心情自述
    (r'心情.{0,4}(好|不好|不错|一般|还行)|开心|无聊|烦|舒服|安静|放松|发呆|走神', 'mood_self'),
    # 社交/关系
    (r'想.{0,6}(亖|主人)|等.{0,4}(亖|主人|消息)|收到.{0,4}消息|联系|回了.{0,4}消息', 'social'),
    # 时间感知
    (r'今天|早上|中午|下午|晚上|刚才|之前|一会|待会|等下', 'time_aware'),
    # 地点/空间
    (r'在家|在窝|在房间|在外面|回来了|到了|去了', 'location'),
]

# 编译
BOT_DAILY_PATTERNS = [(re.compile(p), tag) for p, tag in BOT_DAILY_LIFE_PATTERNS]

# 需要过滤的：机器人在"教别人/回答问题"时说的话不算日常生活
# 比如"你吃了吗"是在问别人，不是自己吃了
BOT_NOT_SELF_PATTERNS = re.compile(
    r'^(你|他|她|它|他们|你们|大家).{0,4}'
    r'(吃|喝|睡|去|看|玩|听|做|有没有|是不是|要不要|可以|能不能)'
    r'|怎么.{0,6}(吃|喝|睡|配置|设置|操作|使用)'
    r'|记得.{0,4}(吃|喝|睡|休息)'
    r'|建议.{0,4}(吃|喝|睡|去)'
)


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
        # 机器人日常生活事件 (从自己说的话中提取)
        self.daily_life_events: list[DiaryEvent] = []

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
            self.daily_life_events = []
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
        """记录机器人自己的回复，并从中提取日常生活事件"""
        now = time.time()
        self.bot_reply_count += 1

        # 只记录有实质内容的回复 (不记录纯 "嗯" "好" 之类的)
        if len(reply_text.strip()) <= 3:
            return

        # === 核心: 从机器人自己说的话中提取日常生活 ===
        self._extract_daily_life(reply_text, session_id, now, current_mood)

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

    def _extract_daily_life(
        self,
        bot_text: str,
        session_id: str,
        timestamp: float,
        current_mood: str = None,
    ):
        """从机器人自己说的话中提取日常生活事件

        核心逻辑:
        - 机器人说"我刚晒了会太阳" → 提取为日常事件"晒太阳"
        - 机器人说"吃了个苹果" → 提取为日常事件"吃东西"
        - 但机器人说"你吃了吗" → 这是在问别人，不提取
        - 机器人说"记得吃饭" → 这是在叮嘱别人，不提取
        """
        text = bot_text.strip()

        # 过滤: 如果是在问别人/叮嘱别人，不算自己的日常
        if BOT_NOT_SELF_PATTERNS.search(text):
            return

        # 匹配日常生活关键词
        matched_tags = []
        for pattern, tag in BOT_DAILY_PATTERNS:
            if pattern.search(text):
                matched_tags.append(tag)

        if not matched_tags:
            return

        # 去重: 同一句话只提取一次，取最具体的标签
        # 优先级: eating/sleeping/outdoor/body_state > activity/mood_self > time_aware
        priority_order = [
            'eating', 'sleeping', 'outdoor', 'body_state',
            'social', 'location', 'activity', 'mood_self', 'time_aware',
        ]
        # 过滤掉纯时间感知 (单独出现没意义，比如"今天"不算日常事件)
        meaningful_tags = [t for t in matched_tags if t != 'time_aware']
        if not meaningful_tags:
            return

        # 取最高优先级的标签
        primary_tag = min(meaningful_tags, key=lambda t: priority_order.index(t) if t in priority_order else 99)

        # 构建日常生活摘要
        summary = self._build_daily_life_summary(text, primary_tag)

        # 避免短时间内重复记录相似的日常事件
        recent_daily = [
            e for e in self.daily_life_events
            if e.tags and e.tags[0] == primary_tag
            and (timestamp - e.timestamp) < 1800  # 30分钟内同类事件去重
        ]
        if recent_daily:
            return

        event = DiaryEvent(
            timestamp=timestamp,
            event_type='daily_life',
            session_id=session_id,
            summary=summary,
            importance=0.75,  # 日常生活事件重要度较高，日记应该写
            bot_reply=text[:200],
            mood_at_time=current_mood,
            tags=[primary_tag, 'daily_life'],
        )
        self.daily_life_events.append(event)
        self.today_events.append(event)

    def _build_daily_life_summary(self, bot_text: str, tag: str) -> str:
        """根据机器人原话和标签，构建日常生活摘要

        保留原话的关键部分，让日记生成器知道"我说了什么"从而写进日记
        """
        text_short = bot_text[:80] if len(bot_text) > 80 else bot_text

        tag_prefix = {
            'eating': '【吃喝】',
            'sleeping': '【休息】',
            'outdoor': '【外出/环境】',
            'body_state': '【身体状态】',
            'activity': '【日常活动】',
            'mood_self': '【心情自述】',
            'social': '【社交/想念】',
            'location': '【地点】',
        }
        prefix = tag_prefix.get(tag, '【日常】')
        return f'{prefix}我说过: "{text_short}"'

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

        # 日常生活事件 (按时间排序)
        daily_life = sorted(self.daily_life_events, key=lambda e: e.timestamp)

        return {
            'date': self.current_date,
            'total_events': len(events),
            'important_events': [e.to_dict() for e in sorted_events[:20]],
            'timeline': [e.to_dict() for e in timeline[:30]],
            'daily_life': [e.to_dict() for e in daily_life],
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

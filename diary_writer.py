"""
日记生成器 - 调用 LLM 以机器人人设的口吻撰写日记

核心原则:
  1. 真实性 - 只基于当天实际发生的事件，绝不虚构
  2. 人设一致 - 用角色自己的语气、用词习惯写日记
  3. 情感真实 - 反映当天真实的情绪变化
  4. 有取舍 - 像真人一样，重要的事详写，琐碎的事略写或不写
  5. 私密感 - 日记是写给自己看的，可以有内心独白
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger("diary_writer")


# 日记生成的 system prompt 模板
DIARY_SYSTEM_PROMPT = """你现在要以"{name}"的身份写一篇私人日记。

【你是谁】
{identity_section}

【写日记的规则 - 必须严格遵守】
1. 你在写自己的日记，是写给自己看的，不是给别人看的
2. 只能写今天真实发生的事，绝对不能编造、虚构任何事件
3. 用你自己平时说话的方式写，不要变得文绉绉或者煽情
4. 重要的事多写几句，不重要的事一笔带过或者不写
5. 可以写自己的内心感受和想法，但要符合你的性格
6. 不需要每件事都写，挑你觉得值得记录的写
7. 日记长度适中，不要写成流水账，也不要太短敷衍
8. 如果今天没什么特别的事，就简短写几句，真人也会这样
9. 不要用"亲爱的日记"这种开头，直接写内容
10. 可以有省略号、口语化表达、甚至吐槽，像真人写的
11. 不要写动作描写（如*叹气*），只写文字内容
12. 日期已经标注了，正文不需要再写日期

【你今天的心情轨迹】
{mood_section}

【今天发生的真实事件 - 只能基于这些素材写，不能添加任何没有的事】
{events_section}

【今天的数据统计】
{stats_section}

现在请以{name}的身份，写一篇今天的日记。记住：只写真实发生的事，你觉得重要的事详写，不重要的略写。"""


class DiaryWriter:
    """日记生成器"""

    def __init__(self, persona_data: dict = None):
        self.persona = persona_data or {}

    def update_persona(self, persona_data: dict):
        """更新人设数据"""
        self.persona = persona_data

    def build_diary_prompt(self, summary_data: dict) -> str:
        """构建日记生成的完整 prompt"""
        name = self.persona.get('name', '我')

        # 身份部分
        identity_lines = []
        identity_lines.append(f'名字: {name}')
        if self.persona.get('gender'):
            identity_lines.append(f'性别: {self.persona["gender"]}')
        if self.persona.get('identity'):
            identity_lines.append(f'身份: {self.persona["identity"]}')
        if self.persona.get('personality'):
            identity_lines.append(f'性格: {"、".join(self.persona["personality"][:5])}')
        if self.persona.get('speaking_style'):
            identity_lines.append(f'说话风格: {"、".join(self.persona["speaking_style"][:3])}')
        if self.persona.get('background'):
            identity_lines.append(f'背景: {self.persona["background"][:200]}')
        identity_section = '\n'.join(identity_lines)

        # 心情轨迹
        mood_section = self._build_mood_section(summary_data)

        # 事件部分
        events_section = self._build_events_section(summary_data)

        # 统计部分
        stats_section = self._build_stats_section(summary_data)

        return DIARY_SYSTEM_PROMPT.format(
            name=name,
            identity_section=identity_section,
            mood_section=mood_section,
            events_section=events_section,
            stats_section=stats_section,
        )

    def build_diary_user_message(self, summary_data: dict) -> str:
        """构建发给 LLM 的 user message"""
        date = summary_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        name = self.persona.get('name', '我')

        if summary_data.get('total_events', 0) == 0:
            return f'今天是{date}，今天似乎没什么特别的事发生。请以{name}的身份写一篇简短的日记，可以写写自己的状态或者感受。'

        return f'今天是{date}，请根据上面提供的今天真实发生的事件，以{name}的身份写一篇日记。'

    def _build_mood_section(self, summary_data: dict) -> str:
        """构建心情轨迹描述"""
        stats = summary_data.get('stats', {})
        mood_changes = stats.get('mood_changes', [])

        if not mood_changes:
            return '今天心情比较平稳，没有太大波动。'

        lines = []
        for mc in mood_changes:
            line = f'- {mc["time"]} 心情从{mc["from"]}变成了{mc["to"]}'
            if mc.get('trigger'):
                line += f'（{mc["trigger"]}）'
            lines.append(line)
        return '\n'.join(lines)

    def _build_events_section(self, summary_data: dict) -> str:
        """构建事件描述"""
        timeline = summary_data.get('timeline', [])
        important = summary_data.get('important_events', [])

        if not timeline and not important:
            return '今天没有什么特别的事发生。'

        # 用时间线为主，补充重要事件
        seen_summaries = set()
        lines = []

        # 先按时间线排列
        for event in timeline:
            summary = event.get('summary', '')
            if summary in seen_summaries:
                continue
            seen_summaries.add(summary)

            time_str = event.get('time_str', '')
            importance = event.get('importance', 0.5)
            importance_mark = '★' if importance >= 0.7 else ''

            line = f'[{time_str}] {importance_mark}{summary}'
            if event.get('bot_reply'):
                line += f'\n  → 我的回复: "{event["bot_reply"][:60]}"'
            lines.append(line)

        # 补充重要但不在时间线中的事件
        for event in important:
            summary = event.get('summary', '')
            if summary not in seen_summaries and event.get('importance', 0) >= 0.6:
                seen_summaries.add(summary)
                time_str = event.get('time_str', '')
                lines.append(f'[{time_str}] ★{summary}')

        if not lines:
            return '今天没有什么特别的事发生。'

        return '\n'.join(lines)

    def _build_stats_section(self, summary_data: dict) -> str:
        """构建统计数据描述"""
        stats = summary_data.get('stats', {})
        lines = []

        active = stats.get('active_sessions', 0)
        if active:
            lines.append(f'今天在{active}个群/会话里活跃过')

        total_msg = stats.get('total_messages_seen', 0)
        if total_msg:
            lines.append(f'看到了大约{total_msg}条消息')

        replies = stats.get('bot_replies', 0)
        if replies:
            lines.append(f'我回复了{replies}次')

        top_users = stats.get('top_interacted_users', [])
        if top_users:
            user_strs = [f'{u["name"]}({u["count"]}次)' for u in top_users[:3]]
            lines.append(f'互动最多的人: {", ".join(user_strs)}')

        return '\n'.join(lines) if lines else '今天比较安静。'

    def format_diary_entry(self, date: str, content: str, mood_summary: str = '') -> dict:
        """格式化最终的日记条目"""
        return {
            'date': date,
            'content': content.strip(),
            'mood_summary': mood_summary,
            'generated_at': datetime.now().isoformat(),
            'persona_name': self.persona.get('name', '未知'),
            'word_count': len(content.strip()),
        }

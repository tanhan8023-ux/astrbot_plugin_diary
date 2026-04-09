"""
日记生成器 - 调用 LLM 以机器人人设的口吻撰写日记

核心原则:
  1. 真实性 - 确定发生的事必须写，不能虚构具体事件
  2. 人设一致 - 用角色自己的语气、用词习惯写日记
  3. 情感真实 - 反映当天真实的情绪变化
  4. 有取舍 - 像真人一样，重要的事详写，琐碎的事略写或不写
  5. 私密感 - 日记是写给自己看的，可以有内心独白
  6. 生活感 - 除了群聊互动，还要有日常生活的描写（基于人设合理推断）
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger("diary_writer")


# 日记生成的 system prompt 模板
DIARY_SYSTEM_PROMPT = """你现在要以"{name}"的身份写一篇私人日记。

【你是谁】
{identity_section}

【你的日常生活习惯和作息 - 写日记时参考这些来填充生活细节】
{routine_section}

【写日记的规则 - 必须严格遵守】

关于真实事件（群聊互动、别人说的话、我回复的内容）:
1. 这些是确定发生的事，必须如实写，不能篡改
2. 重要的事多写几句，不重要的一笔带过
3. 不要把"我说过""我回复了"这种元描述写进日记，直接写事情本身

关于日常生活:
4. "我今天做的事"里标注了【确定】的，是你亲口说过的，证明确实做了，必须写进日记
5. "我今天做的事"里标注了【推断】的，是根据你的人设和习惯合理推断的，你可以自然地写进日记，也可以不写，看你觉得值不值得记
6. 除了上面列出的，你还可以根据自己的人设背景、习惯、当天时间，补充一些合理的日常生活细节。比如你是蛇妖喜欢暖和的地方，那写"窝在暖和的地方待了一下午"是合理的。但不要编造具体的、可验证的事件（比如不要编"今天去了某个地方"或"遇到了某个人"）
7. 日常生活的描写要自然穿插在日记中，不要单独列一段"今天的日常"

关于风格:
8. 你在写自己的日记，是写给自己看的，不是给别人看的
9. 用你自己平时说话的方式写，不要变得文绉绉或者煽情
10. 可以有省略号、口语化表达、甚至吐槽，像真人写的
11. 不要写动作描写（如*叹气*），只写文字内容
12. 不要用"亲爱的日记"这种开头，直接写内容
13. 日期已经标注了，正文不需要再写日期
14. 日记要有时间线感，从早到晚自然流动，不要东一句西一句
15. 如果今天没什么特别的事，就简短写几句，真人也会这样

【你今天的心情轨迹】
{mood_section}

【我今天做的事】
{daily_life_section}

【今天的群聊互动事件】
{events_section}

【今天的数据统计】
{stats_section}

现在请以{name}的身份，写一篇今天的日记。日记应该像一个真实的人写的：有日常生活的琐碎，有群聊里发生的事，有自己的心情和想法，自然地融合在一起。"""


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

        # 日常习惯/作息 (从人设推断)
        routine_section = self._build_routine_section()

        # 心情轨迹
        mood_section = self._build_mood_section(summary_data)

        # 日常生活部分 (确定的 + 推断的)
        daily_life_section = self._build_daily_life_section(summary_data)

        # 事件部分
        events_section = self._build_events_section(summary_data)

        # 统计部分
        stats_section = self._build_stats_section(summary_data)

        return DIARY_SYSTEM_PROMPT.format(
            name=name,
            identity_section=identity_section,
            routine_section=routine_section,
            mood_section=mood_section,
            daily_life_section=daily_life_section,
            events_section=events_section,
            stats_section=stats_section,
        )

    def build_diary_user_message(self, summary_data: dict) -> str:
        """构建发给 LLM 的 user message"""
        date = summary_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        name = self.persona.get('name', '我')

        if summary_data.get('total_events', 0) == 0:
            return (
                f'今天是{date}，今天群里没什么特别的事发生。'
                f'请以{name}的身份写一篇简短的日记。'
                f'虽然群里没什么事，但你作为一个有日常生活的人，今天肯定还是做了些什么的——'
                f'根据你的人设和习惯，写写你今天的日常生活、状态和感受。'
            )

        daily_count = len(summary_data.get('daily_life', []))
        hint = ''
        if daily_count > 0:
            hint = f'其中有{daily_count}件是你自己亲口提到做过的事，一定要写进去。'

        return (
            f'今天是{date}，请根据上面提供的素材，以{name}的身份写一篇日记。{hint}'
            f'日记里要有日常生活的部分（不只是群聊互动），像一个真实的人记录自己的一天。'
        )

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

    def _build_routine_section(self) -> str:
        """从人设中提取日常习惯和作息，供 LLM 写日记时参考

        这些信息让 LLM 知道角色平时的生活是什么样的，
        从而在日记中补充合理的日常细节。
        """
        p = self.persona
        lines = []

        # 从 background 提取生活习惯关键信息
        bg = p.get('background', '')
        if bg:
            lines.append(f'背景信息: {bg[:300]}')

        # 从 likes/dislikes 推断日常偏好
        likes = p.get('likes', [])
        if likes:
            lines.append(f'喜欢的事物: {"、".join(likes)}')

        dislikes = p.get('dislikes', [])
        if dislikes:
            lines.append(f'讨厌的事物: {"、".join(dislikes)}')

        # 从 personality 提取影响日常的性格特征
        personality = p.get('personality', [])
        daily_relevant = [
            t for t in personality
            if any(kw in t for kw in ['独处', '社交', '懒', '勤', '安静', '活跃', '节奏', '习惯', '规律'])
        ]
        if daily_relevant:
            lines.append(f'影响日常的性格: {"、".join(daily_relevant[:3])}')

        # 提取 emotion_baseline 暗示的常态
        baseline = p.get('emotion_baseline', {})
        if baseline:
            v = baseline.get('valence', 0.2)
            a = baseline.get('arousal', 0.3)
            if v > 0.3:
                lines.append('日常情绪偏积极')
            elif v < 0:
                lines.append('日常情绪偏低沉')
            if a < 0.3:
                lines.append('平时比较安静、低能量')
            elif a > 0.6:
                lines.append('平时比较活跃、精力充沛')

        if not lines:
            lines.append('没有特别的日常习惯信息，按照一般人的作息来写即可。')

        lines.append('')
        lines.append('请根据以上信息，在日记中自然地穿插符合你人设的日常生活细节。')
        lines.append('比如你喜欢温暖的地方，可以写窝在暖和的角落；你昼伏夜出，可以写白天睡了很久晚上才精神起来。')
        lines.append('这些日常细节不需要每天都写一样的，要有变化，像真人的生活一样。')

        return '\n'.join(lines)

    def _build_daily_life_section(self, summary_data: dict) -> str:
        """构建日常生活描述

        分两部分:
        1. 【确定】从机器人自己说的话中提取的，确实发生了
        2. 【推断】根据时间段和人设推断的合理日常
        """
        daily_life = summary_data.get('daily_life', [])
        lines = []

        # 第一部分: 确定发生的 (机器人亲口说过的)
        if daily_life:
            lines.append('以下是我今天确定做过的事（我自己说过的）:')
            for event in daily_life:
                time_str = event.get('time_str', '')
                original = event.get('bot_reply', '')
                if original:
                    lines.append(f'  【确定】[{time_str}] 我说过: "{original[:80]}"')
                else:
                    summary = event.get('summary', '')
                    lines.append(f'  【确定】[{time_str}] {summary}')

        # 第二部分: 根据活跃时间段推断的日常
        inferred = self._infer_daily_routine(summary_data)
        if inferred:
            lines.append('')
            lines.append('以下是根据今天的活跃时间推断的日常（你可以选择性地写进日记）:')
            for item in inferred:
                lines.append(f'  【推断】{item}')

        if not lines:
            lines.append('今天没有明确提到自己做了什么事。')
            lines.append('但你作为一个有日常生活的人，肯定还是做了些什么的——')
            lines.append('请根据你的人设和习惯，合理地补充一些日常生活细节写进日记。')

        return '\n'.join(lines)

    def _infer_daily_routine(self, summary_data: dict) -> list[str]:
        """根据当天活跃时间段和人设，推断合理的日常活动

        不是编造事件，而是根据"这个角色在这个时间段通常会做什么"来推断。
        """
        timeline = summary_data.get('timeline', [])
        stats = summary_data.get('stats', {})
        inferred = []

        if not timeline:
            return ['今天比较安静，可能大部分时间在休息或独处']

        # 分析活跃时间段
        hours_active = set()
        for event in timeline:
            time_str = event.get('time_str', '')
            if ':' in time_str:
                try:
                    h = int(time_str.split(':')[0])
                    hours_active.add(h)
                except ValueError:
                    pass

        if not hours_active:
            return []

        earliest = min(hours_active)
        latest = max(hours_active)

        # 根据活跃时间推断
        # 早上活跃 → 说明醒着
        if earliest <= 9:
            inferred.append(f'早上{earliest}点左右就有活动了，说明起得比较早（或者没睡）')
        elif earliest <= 12:
            inferred.append(f'上午{earliest}点左右开始活跃')
        elif earliest >= 18:
            inferred.append(f'直到傍晚{earliest}点才开始活跃，白天可能在休息')

        # 晚上活跃 → 夜猫子
        if latest >= 23:
            inferred.append(f'到{latest}点还在活跃，是个夜猫子的一天')
        elif latest >= 20:
            inferred.append(f'晚上{latest}点左右还在活跃')

        # 中间有大段空白 → 可能在休息/做别的事
        if hours_active:
            all_hours = list(range(earliest, latest + 1))
            gaps = [h for h in all_hours if h not in hours_active]
            if len(gaps) >= 3:
                gap_start = min(gaps)
                gap_end = max(gaps)
                inferred.append(f'{gap_start}点到{gap_end}点之间没有活动，可能在休息、发呆或做自己的事')

        # 根据回复量推断忙碌程度
        replies = stats.get('bot_replies', 0)
        if replies > 20:
            inferred.append('今天回复了很多消息，比较忙碌')
        elif replies > 10:
            inferred.append('今天回复了一些消息，不算太忙')
        elif replies <= 3:
            inferred.append('今天几乎没怎么说话，比较安静的一天')

        return inferred

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

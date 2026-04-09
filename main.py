"""
AstrBot 人设日记插件 - 主入口

根据机器人的人设、心情和当天真实经历，自动撰写第一人称日记。
日记内容完全基于当天实际发生的事件，不虚构，像真人写日记一样。

功能:
  1. 全天候监听消息，收集重要事件
  2. 每天定时（默认23:30）自动生成日记
  3. 与活人感插件联动，读取人设和情绪数据
  4. /diary 查看今天/指定日期的日记
  5. /diary_list 查看日记列表
  6. /write_diary 手动触发写日记
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta

from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.register import (
    register_command,
    register_on_llm_request,
    register_after_message_sent,
)

from .diary_collector import DiaryCollector
from .diary_writer import DiaryWriter
from .diary_storage import DiaryStorage

logger = logging.getLogger("diary_plugin")


class DiaryPlugin(Star):
    """人设日记插件 - 让你的 bot 像真人一样写日记

    /diary - 查看今天的日记
    /diary <日期> - 查看指定日期的日记 (如 2025-01-15)
    /diary_list - 查看最近的日记列表
    /write_diary - 手动触发写日记
    """

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context, config)

        # 数据目录
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(plugin_dir, 'data')
        os.makedirs(self.data_dir, exist_ok=True)

        # 初始化子系统
        self.collector = DiaryCollector()
        self.storage = DiaryStorage(self.data_dir)
        self.writer = DiaryWriter()

        # 尝试加载活人感插件的人设数据
        self._load_persona()

        # 配置
        self.diary_hour = 23       # 写日记的小时
        self.diary_minute = 30     # 写日记的分钟
        self.auto_diary_enabled = True  # 是否自动写日记

        # 状态
        self._diary_task = None
        self._last_diary_date = None
        self._generating = False

        # 当前情绪追踪 (从活人感插件获取)
        self._current_mood = 'neutral'
        self._last_mood = 'neutral'

        # 恢复收集器状态
        self._restore_collector_state()

        logger.info("[Diary] 日记插件已加载")

    async def initialize(self):
        """插件激活，启动定时任务"""
        logger.info("[Diary] 日记插件已激活")
        # 启动后台定时任务
        self._diary_task = asyncio.create_task(self._diary_scheduler())

    async def terminate(self):
        """插件停用，保存状态"""
        if self._diary_task:
            self._diary_task.cancel()
        # 保存收集器状态
        self._save_collector_state()
        logger.info("[Diary] 日记插件已停用")

    # ==================== LLM 钩子 - 事件收集 ====================

    @register_on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, request):
        """监听所有 LLM 请求，收集用户消息事件"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        session_id = event.unified_msg_origin
        message_text = event.get_message_str()

        # 检查是否跨天
        yesterday_date, yesterday_events = self.collector.check_new_day()
        if yesterday_date and yesterday_events:
            # 跨天了，异步生成昨天的日记
            asyncio.create_task(
                self._generate_diary_for_date(yesterday_date, yesterday_events)
            )

        # 记录用户消息事件
        self.collector.record_user_message(
            session_id=session_id,
            user_id=user_id,
            user_name=user_name,
            message=message_text,
            current_mood=self._current_mood,
        )

        # 尝试从活人感插件获取情绪状态
        self._try_get_mood_from_persona()

    @register_after_message_sent()
    async def after_sent(self, event: AstrMessageEvent):
        """监听机器人发送的消息，记录回复事件"""
        session_id = event.unified_msg_origin
        user_name = event.get_sender_name()

        if hasattr(event, 'get_result') and event.get_result():
            result = event.get_result()
            if hasattr(result, 'chain') and result.chain:
                bot_text = ''.join(
                    seg.text for seg in result.chain
                    if hasattr(seg, 'text') and seg.text
                )
                if bot_text:
                    self.collector.record_bot_reply(
                        session_id=session_id,
                        reply_text=bot_text,
                        reply_to_user=user_name,
                        current_mood=self._current_mood,
                    )

    # ==================== 命令 ====================

    @register_command("diary", alias={"日记", "查看日记"})
    async def cmd_diary(self, event: AstrMessageEvent):
        """查看日记

        用法:
          /diary - 查看今天的日记
          /diary 2025-01-15 - 查看指定日期的日记
          /diary 昨天 - 查看昨天的日记
        """
        msg = event.get_message_str().strip()
        # 解析参数
        parts = msg.split(maxsplit=1)
        date_str = None

        if len(parts) > 1:
            arg = parts[1].strip()
            if arg in ('今天', 'today'):
                date_str = datetime.now().strftime('%Y-%m-%d')
            elif arg in ('昨天', 'yesterday'):
                date_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            elif arg in ('前天',):
                date_str = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
            else:
                date_str = arg
        else:
            date_str = datetime.now().strftime('%Y-%m-%d')

        # 查找日记
        diary = self.storage.get_diary(date_str)
        if diary:
            content = diary.get('content', '(空)')
            persona_name = diary.get('persona_name', '')
            word_count = diary.get('word_count', len(content))
            header = f"--- {persona_name}的日记 {date_str} ---\n\n"
            footer = f"\n\n--- {word_count}字 ---"
            yield event.plain_result(header + content + footer)
        else:
            # 如果是今天且还没写日记
            if date_str == datetime.now().strftime('%Y-%m-%d'):
                yield event.plain_result(
                    f"今天的日记还没写呢。\n"
                    f"今天已收集 {self.collector.get_today_summary_data()['total_events']} 个事件。\n"
                    f"可以用 /write_diary 手动触发写日记。"
                )
            else:
                yield event.plain_result(f"{date_str} 没有日记记录。")

    @register_command("diary_list", alias={"日记列表", "日记本"})
    async def cmd_diary_list(self, event: AstrMessageEvent):
        """查看最近的日记列表"""
        recent = self.storage.get_recent_diaries(count=10)
        if not recent:
            yield event.plain_result("还没有任何日记记录。")
            return

        lines = ["--- 最近的日记 ---\n"]
        for diary in recent:
            date = diary.get('date', '?')
            content = diary.get('content', '')
            # 取第一行作为预览
            preview = content.split('\n')[0][:40] if content else '(空)'
            word_count = diary.get('word_count', 0)
            lines.append(f"{date} | {preview}... ({word_count}字)")

        total = self.storage.get_diary_count()
        lines.append(f"\n共 {total} 篇日记")
        lines.append("用 /diary <日期> 查看完整内容")

        yield event.plain_result('\n'.join(lines))

    @register_command("write_diary", alias={"写日记"})
    async def cmd_write_diary(self, event: AstrMessageEvent):
        """手动触发写日记"""
        if self._generating:
            yield event.plain_result("正在写日记中，请稍等...")
            return

        summary = self.collector.get_today_summary_data()
        if summary['total_events'] == 0:
            yield event.plain_result("今天还没有收集到任何事件，没什么可写的。")
            return

        yield event.plain_result(
            f"开始写今天的日记...\n"
            f"已收集 {summary['total_events']} 个事件，正在生成中。"
        )

        try:
            diary_content = await self._call_llm_for_diary(summary)
            if diary_content:
                today = datetime.now().strftime('%Y-%m-%d')
                entry = self.writer.format_diary_entry(
                    date=today,
                    content=diary_content,
                    mood_summary=self._current_mood,
                )
                self.storage.save_diary(today, entry)
                self._last_diary_date = today

                header = f"--- 今天的日记写好了 ---\n\n"
                footer = f"\n\n--- {entry['word_count']}字 ---"
                yield event.plain_result(header + diary_content + footer)
            else:
                yield event.plain_result("日记生成失败了，可能是 LLM 没有返回内容。")
        except Exception as e:
            logger.error(f"[Diary] 手动写日记失败: {e}")
            yield event.plain_result(f"写日记时出错了: {str(e)[:100]}")

    @register_command("diary_search", alias={"搜索日记"})
    async def cmd_diary_search(self, event: AstrMessageEvent):
        """搜索日记内容"""
        msg = event.get_message_str().strip()
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("用法: /diary_search <关键词>")
            return

        keyword = parts[1].strip()
        results = self.storage.search_diaries(keyword, limit=5)
        if not results:
            yield event.plain_result(f"没有找到包含「{keyword}」的日记。")
            return

        lines = [f"--- 搜索「{keyword}」的结果 ---\n"]
        for diary in results:
            date = diary.get('date', '?')
            content = diary.get('content', '')
            # 找到关键词附近的文本
            idx = content.find(keyword)
            if idx >= 0:
                start = max(0, idx - 20)
                end = min(len(content), idx + len(keyword) + 30)
                snippet = '...' + content[start:end] + '...'
            else:
                snippet = content[:50] + '...'
            lines.append(f"{date}: {snippet}")

        lines.append(f"\n共找到 {len(results)} 篇相关日记")
        yield event.plain_result('\n'.join(lines))

    @register_command("diary_status", alias={"日记状态"})
    async def cmd_diary_status(self, event: AstrMessageEvent):
        """查看日记插件状态"""
        summary = self.collector.get_today_summary_data()
        total_diaries = self.storage.get_diary_count()
        today = datetime.now().strftime('%Y-%m-%d')
        has_today = self.storage.get_diary(today) is not None

        stats = summary.get('stats', {})
        lines = [
            "--- 日记插件状态 ---",
            f"今日事件: {summary['total_events']} 个",
            f"活跃会话: {stats.get('active_sessions', 0)} 个",
            f"看到消息: {stats.get('total_messages_seen', 0)} 条",
            f"我的回复: {stats.get('bot_replies', 0)} 次",
            f"情绪变化: {len(stats.get('mood_changes', []))} 次",
            f"当前心情: {self._mood_cn(self._current_mood)}",
            f"今日日记: {'已写' if has_today else '未写'}",
            f"日记总数: {total_diaries} 篇",
            f"自动写日记: {'开启' if self.auto_diary_enabled else '关闭'}",
            f"写日记时间: 每天 {self.diary_hour:02d}:{self.diary_minute:02d}",
        ]

        top_users = stats.get('top_interacted_users', [])
        if top_users:
            user_strs = [f'{u["name"]}({u["count"]}次)' for u in top_users[:3]]
            lines.append(f"互动最多: {', '.join(user_strs)}")

        yield event.plain_result('\n'.join(lines))

    # ==================== 内部方法 ====================

    async def _diary_scheduler(self):
        """后台定时任务：每天定时写日记"""
        while True:
            try:
                now = datetime.now()
                # 计算下次写日记的时间
                target = now.replace(
                    hour=self.diary_hour,
                    minute=self.diary_minute,
                    second=0,
                    microsecond=0,
                )
                if now >= target:
                    target += timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                logger.info(
                    f"[Diary] 下次写日记时间: {target.strftime('%Y-%m-%d %H:%M')}，"
                    f"等待 {wait_seconds/3600:.1f} 小时"
                )

                await asyncio.sleep(wait_seconds)

                # 到时间了，写日记
                if self.auto_diary_enabled:
                    today = datetime.now().strftime('%Y-%m-%d')
                    if self._last_diary_date != today:
                        await self._auto_generate_diary()

            except asyncio.CancelledError:
                logger.info("[Diary] 定时任务已取消")
                break
            except Exception as e:
                logger.error(f"[Diary] 定时任务异常: {e}")
                await asyncio.sleep(60)  # 出错后等1分钟重试

    async def _auto_generate_diary(self):
        """自动生成今天的日记"""
        today = datetime.now().strftime('%Y-%m-%d')
        logger.info(f"[Diary] 开始自动生成 {today} 的日记")

        summary = self.collector.get_today_summary_data()
        if summary['total_events'] == 0:
            logger.info("[Diary] 今天没有事件，跳过日记生成")
            return

        try:
            diary_content = await self._call_llm_for_diary(summary)
            if diary_content:
                entry = self.writer.format_diary_entry(
                    date=today,
                    content=diary_content,
                    mood_summary=self._current_mood,
                )
                self.storage.save_diary(today, entry)
                self._last_diary_date = today
                logger.info(f"[Diary] 日记已生成: {len(diary_content)} 字")
            else:
                logger.warning("[Diary] LLM 未返回日记内容")
        except Exception as e:
            logger.error(f"[Diary] 自动生成日记失败: {e}")

    async def _generate_diary_for_date(self, date: str, events: list):
        """为指定日期生成日记 (用于跨天时补写昨天的日记)"""
        if self.storage.get_diary(date):
            return  # 已有日记，不重复生成

        logger.info(f"[Diary] 补写 {date} 的日记 ({len(events)} 个事件)")

        # 构建摘要数据
        summary = {
            'date': date,
            'total_events': len(events),
            'important_events': [
                e.to_dict() for e in sorted(events, key=lambda x: x.importance, reverse=True)[:20]
            ],
            'timeline': [
                e.to_dict() for e in sorted(events, key=lambda x: x.timestamp)
                if e.importance >= 0.4
            ][:30],
            'stats': {
                'active_sessions': len(set(e.session_id for e in events)),
                'total_messages_seen': len([e for e in events if e.event_type == 'chat']),
                'bot_replies': len([e for e in events if e.event_type == 'reply']),
                'top_interacted_users': [],
                'mood_changes': [],
            },
        }

        try:
            diary_content = await self._call_llm_for_diary(summary)
            if diary_content:
                entry = self.writer.format_diary_entry(
                    date=date,
                    content=diary_content,
                )
                self.storage.save_diary(date, entry)
                logger.info(f"[Diary] 补写日记完成: {date}")
        except Exception as e:
            logger.error(f"[Diary] 补写日记失败 {date}: {e}")

    async def _call_llm_for_diary(self, summary_data: dict) -> str:
        """调用 LLM 生成日记内容

        通过 AstrBot 的 Context 获取 LLM provider 来生成日记。
        """
        self._generating = True
        try:
            # 构建 prompt
            system_prompt = self.writer.build_diary_prompt(summary_data)
            user_message = self.writer.build_diary_user_message(summary_data)

            # 尝试通过 AstrBot 的 provider 系统调用 LLM
            diary_text = await self._invoke_llm(system_prompt, user_message)
            return diary_text
        finally:
            self._generating = False

    async def _invoke_llm(self, system_prompt: str, user_message: str) -> str:
        """通过 AstrBot 的 provider 系统调用 LLM

        尝试多种方式获取 LLM provider:
        1. context.get_using_provider() - 获取当前使用的 provider
        2. context.provider_manager - 直接访问 provider manager
        """
        try:
            # 方式1: 通过 context 获取 provider
            provider = None

            if hasattr(self.context, 'get_using_provider'):
                provider = self.context.get_using_provider()
            elif hasattr(self.context, 'provider_manager'):
                pm = self.context.provider_manager
                if hasattr(pm, 'get_using_provider'):
                    provider = pm.get_using_provider()
                elif hasattr(pm, 'providers') and pm.providers:
                    provider = pm.providers[0]

            if provider is None:
                # 方式2: 尝试从 context 的属性中找到可用的 provider
                for attr_name in dir(self.context):
                    if 'provider' in attr_name.lower():
                        attr = getattr(self.context, attr_name, None)
                        if attr and callable(getattr(attr, 'text_chat', None)):
                            provider = attr
                            break

            if provider is None:
                logger.error("[Diary] 无法获取 LLM provider")
                return ""

            # 调用 LLM
            if hasattr(provider, 'text_chat'):
                # 标准 AstrBot provider 接口
                response = await provider.text_chat(
                    prompt=user_message,
                    system_prompt=system_prompt,
                )
                if hasattr(response, 'completion_text'):
                    return response.completion_text or ""
                if isinstance(response, str):
                    return response
                if hasattr(response, 'text'):
                    return response.text or ""
                return str(response) if response else ""

            elif hasattr(provider, 'chat'):
                response = await provider.chat(
                    prompt=user_message,
                    system_prompt=system_prompt,
                )
                return str(response) if response else ""

            else:
                logger.error(f"[Diary] Provider 没有可用的聊天方法: {type(provider)}")
                return ""

        except Exception as e:
            logger.error(f"[Diary] 调用 LLM 失败: {e}")
            return ""

    def _load_persona(self):
        """尝试加载活人感插件的人设数据"""
        # 尝试从活人感插件的数据目录加载
        persona_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         '..', 'astrbot_plugin_alive_persona', 'data', 'persona.json'),
            os.path.join(self.data_dir, 'persona.json'),
        ]

        for path in persona_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        persona_data = json.load(f)
                    self.writer.update_persona(persona_data)
                    logger.info(f"[Diary] 已加载人设: {persona_data.get('name', '未知')}")
                    return
                except Exception as e:
                    logger.warning(f"[Diary] 加载人设失败 {abs_path}: {e}")

        logger.info("[Diary] 未找到人设文件，使用默认设置")

    def _try_get_mood_from_persona(self):
        """尝试从活人感插件获取当前情绪"""
        try:
            # 尝试通过 AstrBot 的插件系统获取活人感插件实例
            if hasattr(self.context, 'get_registered_star'):
                alive_plugin = self.context.get_registered_star('astrbot_plugin_alive_persona')
                if alive_plugin and hasattr(alive_plugin, 'emotion'):
                    old_mood = self._current_mood
                    self._current_mood = alive_plugin.emotion.get_mood()
                    # 记录情绪变化
                    if old_mood != self._current_mood:
                        self.collector.record_mood_change(
                            old_mood=old_mood,
                            new_mood=self._current_mood,
                        )
                    return

            # 方式2: 遍历已注册的 star
            if hasattr(self.context, 'stars'):
                for star in self.context.stars:
                    if hasattr(star, 'emotion') and hasattr(star.emotion, 'get_mood'):
                        old_mood = self._current_mood
                        self._current_mood = star.emotion.get_mood()
                        if old_mood != self._current_mood:
                            self.collector.record_mood_change(
                                old_mood=old_mood,
                                new_mood=self._current_mood,
                            )
                        return
        except Exception:
            pass  # 静默失败，不影响主流程

    def _save_collector_state(self):
        """保存收集器状态到磁盘"""
        try:
            events_data = [e.to_dict() for e in self.collector.today_events]
            self.storage.save_collector_state(events_data)
        except Exception as e:
            logger.error(f"[Diary] 保存收集器状态失败: {e}")

    def _restore_collector_state(self):
        """从磁盘恢复收集器状态"""
        try:
            state = self.storage.load_collector_state()
            if state and state.get('events'):
                from .diary_collector import DiaryEvent
                for event_dict in state['events']:
                    event = DiaryEvent.from_dict(event_dict)
                    self.collector.today_events.append(event)
                logger.info(
                    f"[Diary] 已恢复 {len(state['events'])} 个事件"
                )
        except Exception as e:
            logger.warning(f"[Diary] 恢复收集器状态失败: {e}")

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

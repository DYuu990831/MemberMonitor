import os
import json
import time
import threading
from plugins import *
from common.log import logger
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage

@register(
    name="MemberMonitor",
    desc="监控群成员变化",
    version="1.0",
    author="assistant"
)
class MemberMonitor(Plugin):
    def __init__(self):
        super().__init__()
        try:
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            # 加载配置
            self.config = super().load_config()
            if not self.config:
                self.config = {
                    "check_interval": 30,  # 检查间隔（秒）
                    "exit_prompt": "请你随机使用一种风格说一句{nickname}退出群聊的提示语。"
                }
                self.save_config(self.config)
            
            # 初始化成员记录
            self.members_record = {}
            self.running = False
            self.monitor_thread = None
            self.first_check = True
            
            logger.info("[MemberMonitor] 插件已初始化")
            
        except Exception as e:
            logger.error(f"[MemberMonitor] 初始化失败: {e}")
            raise e

    def start_monitor(self):
        def run_monitor():
            while self.running:
                try:
                    self.check_members()

                    time.sleep(self.config["check_interval"])
                except Exception as e:
                    logger.error(f"[MemberMonitor] 监控异常: {e}")
                    time.sleep(10)  # 发生错误时等待10秒再重试

        self.monitor_thread = threading.Thread(target=run_monitor, daemon=True)
        self.monitor_thread.start()

    def get_group_members(self, group_id):
        """获取群成员列表"""
        try:
            from lib import itchat
            group = itchat.search_chatrooms(userName=group_id)
            if group:
                members = itchat.update_chatroom(group_id, detailedMember=True)
                member_list = members.get('MemberList', [])
                
                return member_list
            return []
        except Exception as e:
            logger.error(f"[MemberMonitor] 获取群成员失败: {e}")
            return []

    def check_members(self):
        """检查群成员变化"""
        try:
            from lib import itchat
            # 获取所有群聊
            groups = itchat.get_chatrooms()
            
            for group in groups:
                group_id = group['UserName']
                current_members = {
                    member['UserName']: member['NickName'] 
                    for member in self.get_group_members(group_id)
                }
                
                # 如果群成员列表为空，休息两分钟
                if not current_members:
                    logger.warning(f"[MemberMonitor] 群 {group_id} 成员列表为空，休息两分钟")
                    time.sleep(120)
                    continue
                
                # 如果是首次检查，仅记录
                if group_id not in self.members_record:
                    self.members_record[group_id] = current_members
                    continue
                
                # 检查退群成员
                previous_members = self.members_record[group_id]
                exit_members = set(previous_members.keys()) - set(current_members.keys())
                
                # 处理退群事件
                for member_id in exit_members:
                    nickname = previous_members[member_id]
                    self.handle_member_exit(group_id, nickname)
                
                # 更新记录
                self.members_record[group_id] = current_members
                
        except Exception as e:
            logger.error(f"[MemberMonitor] 检查成员变化失败: {e}")

    def handle_member_exit(self, group_id, nickname):
        """处理退群事件"""
        try:
            # 创建定时发送任务
            def delayed_notice():
                try:
                    from lib import itchat
                    # 构建退群提示消息
                    prompt = f"@{nickname} 退群了"
                    # 发送消息到群
                    itchat.send(prompt, group_id)
                    logger.info(f"[MemberMonitor] 已发送退群提示: {prompt}")
                except Exception as e:
                    logger.error(f"[MemberMonitor] 发送退群提示失败: {e}")
            
            # 启动定时任务线程
            delay_seconds = 1  # 可以配置延迟时间
            timer_thread = threading.Timer(delay_seconds, delayed_notice)
            timer_thread.daemon = True  # 设置为守护线程
            timer_thread.start()
            
            logger.info(f"[MemberMonitor] 已安排退群提示任务: {nickname}")
            
        except Exception as e:
            logger.error(f"[MemberMonitor] 处理退群事件失败: {e}")

    def destroy(self):
        """插件销毁时的清理工作"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)  # 等待监控线程结束，最多等待2秒
        logger.info("[MemberMonitor] 插件已停止")

    def get_help_text(self, **kwargs):
        help_text = "监控群成员变化插件使用说明：\n"
        help_text += "1. #monitor start - 启动群成员监控\n"
        help_text += "2. #monitor stop - 停止群成员监控\n"
        help_text += "3. #monitor status - 查看监控状态"
        return help_text

    def on_handle_context(self, e_context: EventContext):
        if e_context['context'].type != ContextType.TEXT:
            return

        content = e_context['context'].content.strip()

        reply = Reply()
        reply.type = ReplyType.TEXT
        
        cmd_handlers = {
            '开启群监控': self._start_monitor_handler,
            '关闭群监控': self._stop_monitor_handler,
            '查看监控状态': self._status_monitor_handler,
        }
        
        cmd = content.split()
        if len(cmd) < 1:
            e_context.action = EventAction.CONTINUE
        elif cmd[0] in cmd_handlers:
            cmd_handlers[cmd[0]](e_context, reply)
        else:
            e_context.action = EventAction.CONTINUE

    def _start_monitor_handler(self, e_context, reply):
        if not self.running:
            self.running = True
            self.start_monitor()
            reply.content = "群成员监控已启动"
        else:
            reply.content = "群成员监控已在运行中"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS

    def _stop_monitor_handler(self, e_context, reply):
        if self.running:
            self.running = False
            reply.content = "群成员监控已停止"
        else:
            reply.content = "群成员监控未在运行"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS

    def _status_monitor_handler(self, e_context, reply):
        status = "运行中" if self.running else "已停止"
        reply.content = f"群成员监控状态：{status}"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS

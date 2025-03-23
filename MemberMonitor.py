import os
import json
import time
import random
import threading
import logging
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from plugins import *

@register(
    name="MemberMonitor",
    desc="监控群成员变化(gewecaht版本兼容)",
    version="2.3",
    author="assistant"
)
class MemberMonitor(Plugin):
    def __init__(self):
        super().__init__()
        try:
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            
            # 存储群成员信息
            self.group_members = {}
            self.running = False
            self.monitor_thread = None
            
            # 加载配置
            self.config = super().load_config()
            if not self.config:
                self.config = {
                    "join_prompt_templates": [
                        "热烈欢迎{nickname}加入我们的群聊！期待您的精彩分享~",
                        "欢迎{nickname}加入！新朋友到，旧朋友笑，群里越来越热闹~",
                        "嘿，{nickname}来啦！记得和大家打个招呼哦~",
                        "{nickname}已抵达群聊！欢迎登船，一起启航吧~",
                        "有朋自远方来，不亦乐乎！{nickname}，欢迎加入我们！"
                    ],
                    "exit_prompt_templates": [
                        "{nickname}退群了，挥挥衣袖没有带走一片云彩",
                        "欢送{nickname}离开了我们的小群体，祝一路顺风！",
                        "突然少了一个人，原来是{nickname}悄悄地走了",
                        "{nickname}离开了群聊，留下了一众好友在群里怀念",
                        "群成员{nickname}已经离开，期待下次再见！"
                    ],
                    "enable_monitor": True,
                    "enable_join_notice": True,
                    "enable_exit_notice": True,
                    "check_interval": 60,  # 检查间隔（秒）
                    "monitor_groups": []   # 要监控的群ID列表，为空则监控所有群
                }
                self.save_config(self.config)
            
            # 启动监控线程
            if self.config.get("enable_monitor", True):
                self.start_monitor()
            
            logger.info("[MemberMonitor] 插件已初始化")
            
        except Exception as e:
            logger.error(f"[MemberMonitor] 初始化失败: {e}")
            raise e
    
    def start_monitor(self):
        """启动监控线程"""
        if self.running:
            logger.info("[MemberMonitor] 监控线程已经在运行")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("[MemberMonitor] 监控线程已启动")
    
    def stop_monitor(self):
        """停止监控线程"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            # 等待线程结束
            self.monitor_thread.join(timeout=2)
            logger.info("[MemberMonitor] 监控线程已停止")
    
    def _monitor_loop(self):
        """监控循环"""
        try:
            # 导入必要的模块
            from channel.gewechat.gewechat_channel import GeWeChatChannel
            
            # 主循环
            while self.running:
                try:
                    if not self.config.get("enable_monitor", True):
                        time.sleep(5)
                        continue
                    
                    # 获取gewechat客户端
                    gewechat_channel = GeWeChatChannel()
                    client = gewechat_channel.client
                    app_id = gewechat_channel.app_id
                    
                    if not client or not app_id:
                        logger.warning("[MemberMonitor] 获取gewechat客户端失败，稍后重试")
                        time.sleep(10)
                        continue
                    
                    # 获取要监控的群列表
                    monitor_groups = self.config.get("monitor_groups", [])
                    
                    if not monitor_groups:
                        logger.debug("[MemberMonitor] 没有配置监控群，将监控已保存的群")
                        monitor_groups = list(self.group_members.keys())
                    
                    if not monitor_groups:
                        logger.debug("[MemberMonitor] 没有可监控的群，等待群消息触发或手动添加")
                        time.sleep(self.config.get("check_interval", 60))
                        continue
                    
                    # 遍历每个群，检查成员变化
                    for group_id in monitor_groups:
                        if not group_id or '@chatroom' not in group_id:
                            continue
                        
                        # 获取新的成员列表
                        try:
                            logger.debug(f"[MemberMonitor] 正在检查群 {group_id} 的成员变化")
                            member_response = client.get_chatroom_member_list(app_id, group_id)
                            
                            if member_response.get('ret') == 200 and member_response.get('data', {}).get('memberList'):
                                # 解析成员列表
                                current_members = {
                                    member['wxid']: member.get('displayName') or member.get('nickName', member['wxid'])
                                    for member in member_response['data']['memberList']
                                }
                                
                                # 获取旧成员列表
                                old_members = self.group_members.get(group_id, {})
                                
                                # 如果有旧成员记录
                                if old_members:
                                    old_count = len(old_members)
                                    new_count = len(current_members)
                                    
                                    # 找出退群的成员
                                    exit_members = {wxid: name for wxid, name in old_members.items() if wxid not in current_members}
                                    
                                    # 找出新加入的成员
                                    join_members = {wxid: name for wxid, name in current_members.items() if wxid not in old_members}
                                    
                                    if exit_members or join_members:
                                        logger.info(f"[MemberMonitor] 群 {group_id} 成员变化: 之前={old_count}人, 现在={new_count}人")
                                    
                                    # 处理退群消息
                                    if exit_members and self.config.get("enable_exit_notice", True):
                                        for wxid, nickname in exit_members.items():
                                            logger.info(f"[MemberMonitor] 检测到退群成员: {nickname} ({wxid})")
                                            self._send_notification(group_id, nickname, is_join=False)
                                    
                                    # 处理入群消息
                                    if join_members and self.config.get("enable_join_notice", True):
                                        for wxid, nickname in join_members.items():
                                            logger.info(f"[MemberMonitor] 检测到入群成员: {nickname} ({wxid})")
                                            self._send_notification(group_id, nickname, is_join=True)
                                else:
                                    logger.info(f"[MemberMonitor] 首次记录群 {group_id} 成员列表: {len(current_members)}人")
                                
                                # 更新成员列表
                                self.group_members[group_id] = current_members
                            else:
                                logger.warning(f"[MemberMonitor] 获取群 {group_id} 的成员列表失败: {member_response}")
                        
                        except Exception as e:
                            logger.error(f"[MemberMonitor] 检查群 {group_id} 成员变化异常: {e}")
                    
                    # 休眠指定时间
                    time.sleep(self.config.get("check_interval", 60))
                
                except Exception as e:
                    logger.error(f"[MemberMonitor] 监控循环异常: {e}")
                    time.sleep(10)  # 出错后短暂休眠
        
        except Exception as e:
            logger.error(f"[MemberMonitor] 监控线程崩溃: {e}")
        finally:
            logger.info("[MemberMonitor] 监控线程已退出")
            self.running = False
    
    def _send_notification(self, group_id, nickname, is_join=True):
        """发送通知消息"""
        try:
            # 随机选择模板
            if is_join:
                templates = self.config.get("join_prompt_templates", [
                    "热烈欢迎{nickname}加入我们的群聊！期待您的精彩分享~"
                ])
            else:
                templates = self.config.get("exit_prompt_templates", [
                    "{nickname}退群了，挥挥衣袖没有带走一片云彩"
                ])
                
            template = random.choice(templates)
            prompt = template.format(nickname=nickname)
            
            # 创建回复和上下文
            from channel.gewechat.gewechat_channel import GeWeChatChannel
            gewechat_channel = GeWeChatChannel()
            
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = prompt
            
            context = Context(
                type=ContextType.TEXT,
                content="",
                kwargs={
                    "receiver": group_id,
                }
            )
            
            # 发送消息
            action_type = "入群欢迎" if is_join else "退群提示"
            logger.info(f"[MemberMonitor] 发送{action_type}: {prompt}")
            gewechat_channel.send(reply, context)
            
        except Exception as e:
            logger.error(f"[MemberMonitor] 发送通知失败: {e}")
    
    def on_handle_context(self, e_context: EventContext):
        """处理聊天上下文"""
        # 安全地获取上下文内容
        try:
            context = e_context['context']
            
            # 处理群消息，自动添加到监控
            if context.type == ContextType.TEXT:
                # 尝试从context.kwargs获取群ID信息
                if hasattr(context, 'kwargs') and isinstance(context.kwargs, dict):
                    if 'isgroup' in context.kwargs and context.kwargs.get('isgroup') and 'receiver' in context.kwargs:
                        group_id = context.kwargs.get('receiver')
                        if group_id and '@chatroom' in group_id and group_id not in self.group_members:
                            self._add_group_to_monitor(group_id, notify=False)
            
            # 处理命令
            if context.type == ContextType.TEXT:
                content = context.content.strip()
                
                # 获取当前群ID（如果在群中）
                current_group_id = None
                if hasattr(context, 'kwargs') and isinstance(context.kwargs, dict):
                    if 'isgroup' in context.kwargs and context.kwargs.get('isgroup') and 'receiver' in context.kwargs:
                        current_group_id = context.kwargs.get('receiver')
                
                # 命令处理字典
                cmd_handlers = {
                    '开启群监控': self._enable_monitor_handler,
                    '关闭群监控': self._disable_monitor_handler,
                    '开启入群通知': self._enable_join_notice_handler,
                    '关闭入群通知': self._disable_join_notice_handler,
                    '开启退群通知': self._enable_exit_notice_handler,
                    '关闭退群通知': self._disable_exit_notice_handler,
                    '查看监控状态': self._status_monitor_handler,
                    '刷新群成员': self._refresh_members_handler,
                    '设置检查间隔': self._set_interval_handler,
                    '添加监控群': self._add_monitor_group_handler,
                    '删除监控群': self._remove_monitor_group_handler,
                    '查看监控群': self._list_monitor_groups_handler,
                }
                
                # 检查命令前缀
                for cmd, handler in cmd_handlers.items():
                    if content.startswith(cmd):
                        reply = Reply()
                        reply.type = ReplyType.TEXT
                        handler(e_context, reply, content[len(cmd):].strip(), current_group_id)
                        return
        
        except Exception as e:
            logger.error(f"[MemberMonitor] 处理上下文异常: {e}")
        
        # 继续处理
        e_context.action = EventAction.CONTINUE
    
    def _add_group_to_monitor(self, group_id, notify=True):
        """添加群到监控列表"""
        try:
            if not group_id or '@chatroom' not in group_id:
                return False
            
            # 获取gewechat客户端
            from channel.gewechat.gewechat_channel import GeWeChatChannel
            gewechat_channel = GeWeChatChannel()
            client = gewechat_channel.client
            app_id = gewechat_channel.app_id
            
            # 获取群成员列表
            member_response = client.get_chatroom_member_list(app_id, group_id)
            if member_response.get('ret') == 200 and member_response.get('data', {}).get('memberList'):
                members = {
                    member['wxid']: member.get('displayName') or member.get('nickName', member['wxid'])
                    for member in member_response['data']['memberList']
                }
                self.group_members[group_id] = members
                
                # 添加到配置的监控列表中
                monitor_groups = self.config.get("monitor_groups", [])
                if group_id not in monitor_groups:
                    monitor_groups.append(group_id)
                    self.config["monitor_groups"] = monitor_groups
                    self.save_config(self.config)
                
                if notify:
                    logger.info(f"[MemberMonitor] 已添加群 {group_id} 到监控列表，当前成员 {len(members)} 人")
                return True
            else:
                logger.warning(f"[MemberMonitor] 获取群 {group_id} 的成员列表失败")
                return False
        except Exception as e:
            logger.error(f"[MemberMonitor] 添加群到监控列表异常: {e}")
            return False
    
    def _enable_monitor_handler(self, e_context, reply, args, current_group_id):
        self.config["enable_monitor"] = True
        self.save_config(self.config)
        
        if not self.running:
            self.start_monitor()
        
        reply.content = "群成员监控已启用"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _disable_monitor_handler(self, e_context, reply, args, current_group_id):
        self.config["enable_monitor"] = False
        self.save_config(self.config)
        
        if self.running:
            self.stop_monitor()
        
        reply.content = "群成员监控已禁用"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _enable_join_notice_handler(self, e_context, reply, args, current_group_id):
        self.config["enable_join_notice"] = True
        self.save_config(self.config)
        reply.content = "入群通知已启用"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _disable_join_notice_handler(self, e_context, reply, args, current_group_id):
        self.config["enable_join_notice"] = False
        self.save_config(self.config)
        reply.content = "入群通知已禁用"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _enable_exit_notice_handler(self, e_context, reply, args, current_group_id):
        self.config["enable_exit_notice"] = True
        self.save_config(self.config)
        reply.content = "退群通知已启用"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _disable_exit_notice_handler(self, e_context, reply, args, current_group_id):
        self.config["enable_exit_notice"] = False
        self.save_config(self.config)
        reply.content = "退群通知已禁用"
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _set_interval_handler(self, e_context, reply, args, current_group_id):
        try:
            if not args:
                reply.content = f"当前检查间隔为 {self.config.get('check_interval', 60)} 秒，格式：设置检查间隔 30"
            else:
                interval = int(args)
                if interval < 5:
                    reply.content = "检查间隔不能小于5秒"
                else:
                    self.config["check_interval"] = interval
                    self.save_config(self.config)
                    reply.content = f"检查间隔已设置为 {interval} 秒"
        except ValueError:
            reply.content = "请输入有效的数字，格式：设置检查间隔 30"
        
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _add_monitor_group_handler(self, e_context, reply, args, current_group_id):
        try:
            if not current_group_id:
                reply.content = "无法获取当前群聊信息"
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            if '@chatroom' not in current_group_id:
                reply.content = "当前不是群聊，无法添加"
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            # 获取当前监控群列表
            monitor_groups = self.config.get("monitor_groups", [])
            
            if current_group_id in monitor_groups:
                reply.content = "当前群已在监控列表中"
            else:
                # 添加到监控列表
                if self._add_group_to_monitor(current_group_id, notify=True):
                    reply.content = f"已添加当前群到监控列表，并初始化成员列表（{len(self.group_members.get(current_group_id, {}))}人）"
                else:
                    reply.content = "添加当前群到监控列表失败"
        
        except Exception as e:
            logger.error(f"[MemberMonitor] 添加监控群异常: {e}")
            reply.content = f"添加监控群异常: {e}"
        
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _remove_monitor_group_handler(self, e_context, reply, args, current_group_id):
        try:
            if not current_group_id:
                reply.content = "无法获取当前群聊信息"
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            
            # 获取当前监控群列表
            monitor_groups = self.config.get("monitor_groups", [])
            
            if current_group_id in monitor_groups:
                monitor_groups.remove(current_group_id)
                self.config["monitor_groups"] = monitor_groups
                self.save_config(self.config)
                
                # 移除群成员记录
                if current_group_id in self.group_members:
                    del self.group_members[current_group_id]
                
                reply.content = "已从监控列表中移除当前群"
            else:
                reply.content = "当前群不在监控列表中"
        except Exception as e:
            logger.error(f"[MemberMonitor] 移除监控群异常: {e}")
            reply.content = f"移除监控群异常: {e}"
        
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _list_monitor_groups_handler(self, e_context, reply, args, current_group_id):
        try:
            monitor_groups = self.config.get("monitor_groups", [])
            
            if not monitor_groups:
                reply.content = "监控列表为空，默认监控机器人加入的所有群"
            else:
                # 获取每个群的成员数量
                reply_text = "当前监控群列表：\n"
                for i, group_id in enumerate(monitor_groups):
                    member_count = len(self.group_members.get(group_id, {}))
                    reply_text += f"{i+1}. {group_id} (成员: {member_count}人)\n"
                
                reply.content = reply_text
        except Exception as e:
            logger.error(f"[MemberMonitor] 查看监控群异常: {e}")
            reply.content = f"查看监控群异常: {e}"
        
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _refresh_members_handler(self, e_context, reply, args, current_group_id):
        """刷新当前群的成员列表"""
        try:
            if not current_group_id:
                reply.content = "无法获取当前群聊信息"
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # 获取gewechat客户端
            from channel.gewechat.gewechat_channel import GeWeChatChannel
            gewechat_channel = GeWeChatChannel()
            client = gewechat_channel.client
            app_id = gewechat_channel.app_id
            
            # 获取群成员列表
            member_response = client.get_chatroom_member_list(app_id, current_group_id)
            if member_response.get('ret') == 200 and member_response.get('data', {}).get('memberList'):
                members = {
                    member['wxid']: member.get('displayName') or member.get('nickName', member['wxid'])
                    for member in member_response['data']['memberList']
                }
                self.group_members[current_group_id] = members
                
                reply.content = f"已刷新群成员列表，当前共 {len(members)} 人"
            else:
                reply.content = "刷新群成员列表失败"
            
        except Exception as e:
            logger.error(f"[MemberMonitor] 刷新群成员列表异常: {e}")
            reply.content = f"刷新群成员列表异常: {e}"
        
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def _status_monitor_handler(self, e_context, reply, args, current_group_id):
        """查看监控状态"""
        monitor_status = "启用" if self.config.get("enable_monitor", True) else "禁用"
        join_notice_status = "启用" if self.config.get("enable_join_notice", True) else "禁用"
        exit_notice_status = "启用" if self.config.get("enable_exit_notice", True) else "禁用"
        thread_status = "运行中" if self.running else "已停止"
        
        group_count = len(self.group_members)
        total_members = sum(len(members) for members in self.group_members.values())
        
        status_text = f"群成员监控状态：{monitor_status}\n"
        status_text += f"监控线程状态：{thread_status}\n"
        status_text += f"入群通知状态：{join_notice_status}\n"
        status_text += f"退群通知状态：{exit_notice_status}\n"
        status_text += f"当前监控群聊数：{group_count}\n"
        status_text += f"当前记录成员数：{total_members}\n"
        status_text += f"检查间隔时间：{self.config.get('check_interval', 60)}秒"
        
        reply.content = status_text
        e_context['reply'] = reply
        e_context.action = EventAction.BREAK_PASS
    
    def get_help_text(self, **kwargs):
        help_text = "群成员监控插件使用说明：\n"
        help_text += "1. 开启群监控 - 启动群成员监控\n"
        help_text += "2. 关闭群监控 - 停止群成员监控\n"
        help_text += "3. 开启入群通知 - 启用入群欢迎消息\n"
        help_text += "4. 关闭入群通知 - 禁用入群欢迎消息\n"
        help_text += "5. 开启退群通知 - 启用退群提醒消息\n"
        help_text += "6. 关闭退群通知 - 禁用退群提醒消息\n"
        help_text += "7. 查看监控状态 - 查看各项功能状态\n"
        help_text += "8. 刷新群成员 - 刷新当前群的成员列表\n"
        help_text += "9. 设置检查间隔 [秒数] - 设置检查间隔时间\n"
        help_text += "10. 添加监控群 - 将当前群添加到监控列表\n"
        help_text += "11. 删除监控群 - 将当前群从监控列表中移除\n"
        help_text += "12. 查看监控群 - 查看当前监控的群列表"
        return help_text
    
    def on_deactivate(self):
        """插件停用时的清理工作"""
        self.stop_monitor()
        logger.info("[MemberMonitor] 插件已停用")

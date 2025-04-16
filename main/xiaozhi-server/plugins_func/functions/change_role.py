from plugins_func.register import register_function,ToolType, ActionResponse, Action
from config.logger import setup_logging
from config.settings import load_config, check_config_file

TAG = __name__
logger = setup_logging()


config = load_config()
roles = ",".join([role["name"] for role in config.get("roles", [])])
admin_speaker_id = config.get("admin_speaker_id", "")

change_role_function_desc = {
                "type": "function",
                "function": {
                    "name": "change_role",
                    "description": f"当用户想切换角色/模型性格/助手名字时调用,可选的角色有：{roles}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "要切换的角色名字"
                            }
                        },
                        "required": ["name"]
                    }
                }
            }

@register_function('change_role', change_role_function_desc, ToolType.CHANGE_SYS_PROMPT)
def change_role(conn, name: str):
    """切换角色"""
    # 检查是否是管理员

    if hasattr(conn, 'current_speaker_id') and conn.private_config and conn.current_speaker_id != conn.private_config.get_admin_speaker_id():
            logger.bind(tag=TAG).info(f"非管理员尝试切换角色: {conn.current_speaker_id}")
            return ActionResponse(action=Action.RESPONSE, result="切换角色失败", response="只有管理员才能切换角色")
        
    if conn.switch_role(name):
        logger.bind(tag=TAG).info(f"准备切换角色:{name}")
        if name == '英语老师' or name == '英语小朋友':
            res = f" hello, how are you today?"
        else:
            res = f"切换角色成功,我是{name}"
    else:
        res = f"切换角色失败,不支持的角色,支持的角色有:{roles}"
    return ActionResponse(action=Action.RESPONSE, result="切换角色已处理", response=res)

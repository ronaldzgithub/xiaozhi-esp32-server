from plugins_func.register import register_function,ToolType, ActionResponse, Action
from config.logger import setup_logging
from config.settings import load_config, check_config_file

TAG = __name__
logger = setup_logging()


config = load_config()
roles = ",".join([role["name"] for role in config.get("roles", [])])

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
    """if name not in prompts:
        return ActionResponse(action=Action.RESPONSE, result="切换角色失败", response="不支持的角色")"""
    conn.switch_role(name)
    
    logger.bind(tag=TAG).info(f"准备切换角色:{name}")
    if name == '英语老师':
        res = f" hello, i am your english teacher"
    else:
        res = f"切换角色成功,我是{name}"
    return ActionResponse(action=Action.RESPONSE, result="切换角色已处理", response=res)

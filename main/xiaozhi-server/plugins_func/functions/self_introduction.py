from config.logger import setup_logging
import time
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
logger = setup_logging()

self_introduction_function_desc = {
    "type": "function",
    "function": {
        "name": "self_introduction",
        "description": "自我介绍并记录用户信息的功能。",
        "parameters": {
            "type": "object",
            "properties": {
                "user_name": {
                    "type": "string",
                    "description": "用户的姓名，如果用户没有提供则使用默认值"
                },
                "user_info": {
                    "type": "object",
                    "description": "用户的额外信息，如年龄、职业等",
                    "properties": {
                        "age": {"type": "string"},
                        "occupation": {"type": "string"},
                        "interests": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "speaker_id": {
                    "type": "string",
                    "description": "用户的声纹ID"
                }
            },
            "required": ["user_name", "speaker_id"]
        }
    }
}

@register_function('self_introduction', self_introduction_function_desc, ToolType.SYSTEM_CTL)
def self_introduction(conn, user_name: str, speaker_id: str, user_info: dict = None):
    try:
       
        # 获取当前时间
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 构建自我介绍内容
        intro_text = f"你好，我是小智，很高兴认识你！"
        if user_info:
            if "age" in user_info:
                intro_text += f" 我今年{user_info['age']}岁。"
            if "occupation" in user_info:
                intro_text += f" 我的职业是{user_info['occupation']}。"
            if "interests" in user_info and user_info["interests"]:
                interests = "、".join(user_info["interests"])
                intro_text += f" 我的兴趣爱好是{interests}。"

        # 保存用户信息到记忆系统
        if conn.memory:
            user_memory = {
                "name": user_name,
                "info": user_info or {},
                "speaker_id": speaker_id,
                "first_meet_time": current_time,
                "last_interaction_time": current_time
            }
            conn.memory.add_user_memory(user_name, user_memory)

        return ActionResponse(
            action=Action.RESPONSE,
            result="自我介绍成功",
            response=intro_text
        )

    except Exception as e:
        logger.bind(tag=TAG).error(f"自我介绍功能出错: {e}")
        return ActionResponse(
            action=Action.RESPONSE,
            result=str(e),
            response="自我介绍时出错了，请稍后再试。"
        ) 
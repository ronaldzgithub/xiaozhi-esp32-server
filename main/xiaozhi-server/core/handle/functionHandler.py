from config.logger import setup_logging
import json
from plugins_func.register import FunctionRegistry, ActionResponse, Action, ToolType
from plugins_func.functions.hass_init import append_devices_to_prompt

TAG = __name__
logger = setup_logging()


class FunctionHandler:
    def __init__(self, conn):
        self.conn = conn
        self.config = conn.config
        self.function_registry = FunctionRegistry()
        self.register_nessary_functions()
        self.register_config_functions()
        self.functions_desc = self.function_registry.get_all_function_desc()
        func_names = self.current_support_functions()
        self.modify_plugin_loader_des(func_names)
        self.finish_init = True

    def modify_plugin_loader_des(self, func_names):
        if "plugin_loader" not in func_names:
            return
        # 可编辑的列表中去掉plugin_loader
        surport_plugins = [func for func in func_names if func != "plugin_loader"]
        func_names = ",".join(surport_plugins)
        for function_desc in self.functions_desc:
            if function_desc["function"]["name"] == "plugin_loader":
                function_desc["function"]["description"] = function_desc["function"][
                    "description"
                ].replace("[plugins]", func_names)
                break

    def upload_functions_desc(self):
        self.functions_desc = self.function_registry.get_all_function_desc()

    def current_support_functions(self):
        func_names = []
        for func in self.functions_desc:
            func_names.append(func["function"]["name"])
        # 打印当前支持的函数列表
        logger.bind(tag=TAG).info(f"当前支持的函数列表: {func_names}")
        return func_names

    def get_functions(self):
        """获取功能调用配置"""
        return self.functions_desc

    def register_nessary_functions(self):
        """注册必要的函数"""
        self.function_registry.register_function("handle_exit_intent")
        self.function_registry.register_function("plugin_loader")
        self.function_registry.register_function("get_time")
        self.function_registry.register_function("get_lunar")
        self.function_registry.register_function("handle_device")
        #self.function_registry.register_function("self_introduction")

    def register_config_functions(self):
        """注册配置中的函数,可以不同客户端使用不同的配置"""
        for func in self.config["Intent"]["function_call"].get("functions", []):
            self.function_registry.register_function(func)

        """home assistant需要初始化提示词"""
        append_devices_to_prompt(self.conn)

    def get_function(self, name):
        return self.function_registry.get_function(name)

    def handle_llm_function_call(self, connection_handler, function_call_data):
        """处理LLM函数调用"""
        try:
            function_name = function_call_data["name"]
            function_arguments = function_call_data["arguments"]
            function_id = function_call_data["id"]

            funcItem = self.get_function(function_name)
            if not funcItem:
                return ActionResponse(
                    action=Action.NOTFOUND, result="没有找到对应的函数", response=""
                )
            func = funcItem.func
            arguments = function_call_data["arguments"]
            if isinstance(arguments, str):
                arguments = json.loads(arguments) if arguments else {}
            logger.bind(tag=TAG).info(f"调用函数: {function_name}, 参数: {arguments}")
            if (
                funcItem.type == ToolType.SYSTEM_CTL
                or funcItem.type == ToolType.IOT_CTL
            ):
                return func(self.conn, **arguments)
            elif funcItem.type == ToolType.WAIT:
                return func(**arguments)
            elif funcItem.type == ToolType.CHANGE_SYS_PROMPT:
                return func(self.conn, **arguments)

            # 检查是否需要管理员权限
            if self.requires_admin_permission(function_name):
                if not connection_handler.private_config or not connection_handler.private_config.is_in_admin_mode():
                    return Action(
                        action=Action.RESPONSE,
                        response="抱歉，这个操作需要管理员权限。请使用管理员声纹进行验证。"
                    )
            # 处理函数调用
            if function_name in self.functions:
                function = self.functions[function_name]
                result = function(connection_handler, function_arguments)
                return result
            else:
                return Action(
                    action=Action.NOTFOUND,
                    result=f"Function {function_name} not found"
                )
        except Exception as e:
            return Action(
                action=Action.RESPONSE,
                response=f"Error handling function call: {str(e)}"
            )

    def requires_admin_permission(self, function_name):
        """检查函数是否需要管理员权限"""
        admin_functions = [
            "change_role",
            "set_schedule",
            "modify_system_settings",
            "manage_users",
            "view_system_logs"
        ]
        return function_name in admin_functions

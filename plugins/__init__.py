from .weather    import WeatherPlugin
from .messaging  import MessagingPlugin
from .voice_profiles import (
    set_profile, unpin, current, current_name, get_say_args,
    greeting, filler, try_parse_profile_switch, auto_select
)
from .error_recovery import (
    internet_monitor_loop, is_online, retry,
    mic_failure, mic_ok, graceful_fallback, on_internet_restore
)
from .base import AstraPlugin

PLUGIN_REGISTRY = [
    WeatherPlugin(),
    MessagingPlugin(),
]

def dispatch(intent: dict, speak_fn, **kwargs) -> bool:
    for plugin in PLUGIN_REGISTRY:
        if intent.get("intent") in plugin.intents:
            try:
                handled = plugin.handle(intent, speak_fn, **kwargs)
                if handled:
                    return True
            except Exception as e:
                print(f"[Plugin:{plugin.name}] error: {e}")
    return False

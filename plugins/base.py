class AstraPlugin:
    name: str = "base"
    intents: list[str] = []

    def handle(self, intent: dict, speak_fn, **kwargs) -> bool:
        raise NotImplementedError

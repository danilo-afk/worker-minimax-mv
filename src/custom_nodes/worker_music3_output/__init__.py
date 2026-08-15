class WorkerMusic3Metadata:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "caption": ("STRING", {"forceInput": True}),
                "lyrics": ("STRING", {"forceInput": True}),
                "debug": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "emit"
    CATEGORY = "Kiara/Output"
    OUTPUT_NODE = True

    def emit(self, caption, lyrics, debug):
        return {
            "ui": {
                "music3_metadata": [
                    {
                        "caption": caption,
                        "lyrics": lyrics,
                        "debug": debug,
                    }
                ]
            }
        }


NODE_CLASS_MAPPINGS = {"WorkerMusic3Metadata": WorkerMusic3Metadata}
NODE_DISPLAY_NAME_MAPPINGS = {"WorkerMusic3Metadata": "Worker Music 3 Metadata"}

import os

os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["MAAS_CONVERSATION_STORE"] = "memory"
os.environ["MAAS_INSTANCE_DIR"] = "examples/fictional-profile"

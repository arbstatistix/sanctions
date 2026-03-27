import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.environ.get("MOONSHOT_API_KEY"),
    base_url=os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
)

tools = [{
    "type": "builtin_function",
    "function": {"name": "$web_search"},
}]

messages = [
    {"role": "user", "content": "search for Apple stock price"}
]

print("Calling API...")
completion = client.chat.completions.create(
    model="kimi-latest", # or whatever model is in .env
    messages=messages,
    tools=tools,
)

msg = completion.choices[0].message
print("Message type:", type(msg))
print("Message dump:", msg.model_dump())
print("model_extra:", getattr(msg, "model_extra", None))
print("reasoning_content attribute:", getattr(msg, "reasoning_content", None))

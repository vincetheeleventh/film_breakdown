import os
from dotenv import load_dotenv
import openai

load_dotenv()

api_key = os.environ.get("MOONSHOT_API_KEY", os.environ.get("KIMI_API_KEY"))

try:
    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.moonshot.ai/v1"
    )
    
    response = client.chat.completions.create(
        model="moonshot-v1-8k",
        messages=[{"role": "user", "content": "Hello!"}],
        temperature=0.3
    )
    print("Success! Reply:", response.choices[0].message.content)
except Exception as e:
    print("Error:", e)

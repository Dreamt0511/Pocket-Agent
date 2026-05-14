import requests
import json
import sys

def chat_stream(prompt, host="127.0.0.1", port=8080):
    url = f"http://{host}:{port}/v1/chat/completions"
    
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": 500
    }
    
    response = requests.post(url, json=payload, stream=True)
    
    for line in response.iter_lines():
        if not line:
            continue
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data = line[6:]
            if data == '[DONE]':
                break
            try:
                chunk = json.loads(data)
                content = chunk['choices'][0]['delta'].get('content')
                if content:
                    print(content, end='', flush=True)
            except:
                pass
    print()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = ' '.join(sys.argv[1:])
    else:
        prompt = input("你: ")
    
    chat_stream(prompt)

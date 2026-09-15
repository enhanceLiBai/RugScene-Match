"""打印 DeepSeek 场景识别的原始响应，不执行项目标签解析。"""
from __future__ import annotations

import base64
import json
import sys
from io import BytesIO
from pathlib import Path

import httpx
from dotenv import dotenv_values
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.scene import OPTIONS


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：python scripts/debug_scene_response.py 图片路径")
        return 2
    root = Path(__file__).resolve().parents[1]
    config = dotenv_values(root / ".env")
    image = Image.open(sys.argv[1]).convert("RGB")
    image.thumbnail((1280, 1280))
    output = BytesIO()
    image.save(output, format="JPEG", quality=85)
    prompt = (
        "识别空间类型、沙发和地板。沙发颜色以主体面料为准，排除抱枕、毯子。"
        "地板颜色和材质只依据裸露的实际地面，必须排除地毯；地毯完全遮挡地面时不得猜测。"
        "考虑暖光和阴影，尽量识别物体本色。沙发/地板先填状态：present=画面确认存在，"
        "not_present=确认没有，unknown=可能存在但看不清；present时填写颜色/材质，否则颜色材质填无法判断。"
        "不确定时填无法判断。只返回JSON，键及允许值：" + json.dumps(OPTIONS, ensure_ascii=False)
    )
    payload = {"model": config["DEEPSEEK_MODEL"], "temperature": 0, "max_tokens": 2048,
               "thinking": {"type": "disabled"},
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()}},
               ]}]}
    response = httpx.post(config["DEEPSEEK_BASE_URL"] + "/chat/completions",
                          headers={"Authorization": "Bearer " + config["DEEPSEEK_API_KEY"]},
                          json=payload, timeout=90)
    print("HTTP:", response.status_code)
    data = response.json()
    print("model:", data.get("model"))
    choice = (data.get("choices") or [{}])[0]
    print("finish_reason:", choice.get("finish_reason"))
    message = choice.get("message") or {}
    print("content:\n", message.get("content"))
    print("reasoning_content:\n", message.get("reasoning_content"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

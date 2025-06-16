# test_gemma_generation.py
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import os

# .env 파일 로드 (MODEL_PATH가 .env에 정의되어 있다면 필요)
from dotenv import load_dotenv
load_dotenv()

# .env 파일에서 MODEL_PATH를 가져오거나 기본값 사용
MODEL_NAME = os.getenv('MODEL_PATH', 'D:/gemma/gemma-2b-it') 

print(f"Loading Gemma model from {MODEL_NAME} for a simple test...")

try:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME) # 양자화나 device_map 없이 단순 로드
    model.eval() # 평가 모드로 설정
    print("Gemma model loaded successfully for test!")

    # 간단한 테스트 프롬프트
    prompt = "Hello, what is your name?"
    input_ids = tokenizer(prompt, return_tensors="pt").to(model.device)

    print(f"\nTest prompt: {prompt}")

    # 응답 생성 (결정론적 생성을 위해 do_sample=False)
    outputs = model.generate(
        **input_ids,
        max_new_tokens=50, # 50개 토큰까지 생성
        do_sample=False,
    )
    
    # 생성된 텍스트 디코딩
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    print(f"\n--- Generated Text ---")
    print(generated_text)
    print(f"--- End Generated Text ---")

except Exception as e:
    print(f"\nAn error occurred during Gemma model test: {e}")
    print("Please ensure the model path is correct and necessary libraries are installed.")

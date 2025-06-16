# app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import os
import re 
import json 
import json5 # json5 임포트 추가!
from werkzeug.security import check_password_hash 
from functools import wraps 
from dotenv import load_dotenv 

# .env 파일 로드 (가장 먼저 실행되어야 함)
load_dotenv()

# 데이터베이스 관리 모듈 임포트
import database_manager 

# Hugging Face 모델 로딩을 위한 라이브러리 임포트
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import torch

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY') 


# --- Gemma 모델 로딩 설정 ---
MODEL_NAME = os.getenv('MODEL_PATH') 

nf4_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=torch.bfloat16
)

tokenizer = None
model = None

try:
    print(f"로컬 경로 '{MODEL_NAME}'에서 Gemma 모델 로딩 중입니다. 잠시만 기다려 주세요...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME, 
        # quantization_config=nf4_config, # 양자화 설정 임시 비활성화
        # device_map="auto" # 장치 매핑 임시 비활성화
    )
    model.eval()
    print("Gemma 모델 로딩 완료!")
except Exception as e:
    print(f"Gemma 모델 로딩 중 오류 발생: {e}")
    print("모델 로딩에 실패했습니다. 로컬 경로와 파일 상태를 확인해주세요.")
    tokenizer = None
    model = None

# --- 대화 상태 관리 (매우 중요!) ---
current_conversation_state = {} 

# --- 로그인 필수 데코레이터 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            flash('로그인이 필요합니다.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- 역할 기반 접근 제어 데코레이터 ---
def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'username' not in session:
                flash('로그인이 필요합니다.', 'danger')
                return redirect(url_for('login'))
            if session.get('role') not in allowed_roles:
                flash('이 페이지에 접근할 권한이 없습니다.', 'danger')
                return redirect(url_for('dashboard')) 
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# --- 사용자 입력 전처리 함수 ---
def preprocess_user_input(user_input):
    # '5대', '2박스', '3개', '4ea', '10box' 등 숫자+단위 패턴을 '숫자'로 변환
    # 예: '노트북 5대 입고' -> '노트북 5 입고'
    pattern = r"(\d+)\s*(개|대|박스|box|ea|EA|Box|BOX)"
    return re.sub(pattern, r"\1", user_input)

# --- AI 응답 생성 함수 (Gemma 활용 및 WMS 연동) ---
def generate_ai_response(user_input):
    user_input = preprocess_user_input(user_input)

    global current_conversation_state 

    if tokenizer is None or model is None:
        return "죄송합니다. AI 모델이 로딩되지 않았습니다. 관리자에게 문의해주세요."

    # --- 대화 상태에 따른 처리 (입고 대기 중인 경우) ---
    if 'action' in current_conversation_state and current_conversation_state['action'] == 'awaiting_location':
        location_code_match = re.search(r'\b([A-Z]-\d{2}-\d{2})\b', user_input, re.IGNORECASE)
        if location_code_match:
            location_code = location_code_match.group(1).upper()
            location_info = database_manager.get_location_id(location_code) 
            
            if location_info:
                location_id, actual_location_code = location_info[0], location_info[1]
                product_id = current_conversation_state['product_id']
                quantity = current_conversation_state['quantity']

                # 현재 사용자의 역할(session['role'])을 기반으로 입고 권한 확인
                current_user_role = session.get('role')
                if current_user_role not in ['admin', 'inbound_manager', 'all_manager']:
                    current_conversation_state = {} 
                    return "죄송합니다. 이 명령을 실행할 권한이 없습니다. 귀하의 역할은 입고 관리자가 아닙니다."

                if database_manager.record_inbound(product_id, quantity, location_id):
                    current_conversation_state = {} 
                    product_name_for_response = database_manager.get_product_id_by_id(product_id)[1]
                    return f"'{product_name_for_response}' {quantity}개를 '{actual_location_code}' 로케이션에 성공적으로 입고 처리했습니다. 재고가 업데이트되었습니다."
                else:
                    product_name_for_response = database_manager.get_product_id_by_id(product_id)[1]
                    return f"'{product_name_for_response}' {quantity}개 입고 중 오류가 발생했습니다. 다시 시도해주세요."
            else:
                return f"죄송합니다. '{location_code}'이라는 로케이션을 찾을 수 없습니다. 정확한 로케이션 코드를 알려주시겠어요? (예: A-01-01)"
        else:
            return "로케이션 코드를 명확히 알려주세요. (예: A-01-01)"

    # --- Gemma 모델에게 의도/개체명 추출 지시 ---
    SYSTEM_PROMPT = """
    오직 다음 JSON 형식으로만 응답하세요. 다른 설명, 마크다운(```), 별표(*), 숫자, 글머리 기호(-), 참고, 주의 사항 등 어떠한 비-JSON 텍스트도 절대 포함하지 마세요.

    가능한 액션(action) 목록:
    - "query_stock": 현재 재고 조회
    - "query_location_items": 특정 로케이션 품목 조회
    - "inbound": 제품 입고
    - "outbound": 제품 출고
    - "query_inbound_history": 입고 기록 조회
    - "query_outbound_history": 출고 기록 조회
    - "unknown": 이해할 수 없는 요청

    개체명(entities)은 다음과 같습니다:
    - product_name (string, 제품명)
    - quantity (integer, 수량)
    - location_code (string, 로케이션 코드)
    - all_stock (boolean, 전체 재고)
    - limit (integer, 개수 제한)

    예시:
    사용자: 노트북 5 입고
    응답: {"action": "inbound", "entities": {"product_name": "노트북 컴퓨터", "quantity": 5}}
    사용자: 입고 현황 알려줘
    응답: {"action": "query_inbound_history", "entities": {"limit": 5}}
    사용자: 안녕하세요
    응답: {"action": "unknown", "entities": {}}
    """

    # Gemma 모델을 사용하여 사용자 입력 분석
    full_prompt = f"""사용자: {user_input}

응답은 다음 JSON 형이어야 합니다:
{{
    "action": "query_inbound_history",
    "entities": {{
        "limit": 5
    }}
}}

가능한 action 값:
- query_stock: 현재 재고 조회
- query_location_items: 특정 로케이션 품목 조회
- inbound: 제품 입고
- outbound: 제품 출고
- query_inbound_history: 입고 기록 조회
- query_outbound_history: 출고 기록 조회
- unknown: 이해할 수 없는 요청

예시:
- 입고 현황/내역 -> query_inbound_history
- 출고 현황/내역 -> query_outbound_history
- 재고 조회 -> query_stock
- 로케이션 조회 -> query_location_items

응답:"""
    
    print(f"모델에 전달되는 full_prompt: {full_prompt}")
    
    input_ids = tokenizer(full_prompt, return_tensors="pt").to(model.device)
    
    outputs = model.generate(
        **input_ids,
        max_new_tokens=50,
        do_sample=False,  # 결정론적 출력
        temperature=1.0,
        top_p=1.0,
        num_return_sequences=1,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
        repetition_penalty=1.2  # 반복 방지
    )
    
    print(f"모델 출력 shape: {outputs.shape}")
    print(f"모델 출력 토큰: {outputs[0]}")
    
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    print(f"디코딩된 전체 텍스트: {generated_text}")
    
    # 모델 생성 텍스트에서 실제 JSON 응답만 추출
    json_match = re.search(r'응답\s*:\s*(\{[\s\S]*?\})', generated_text)
    if json_match:
        ai_json_response_raw = json_match.group(1).strip()
        print(f"Gemma 모델의 JSON 원시 응답 (정규식 추출): {ai_json_response_raw}")
    else:
        ai_json_response_raw = generated_text.replace(full_prompt, "").strip()
        print(f"Gemma 모델의 JSON 원시 응답 (replace): {ai_json_response_raw}")

    # 중괄호 자동 닫기 적용
    ai_json_response_raw = auto_close_braces(ai_json_response_raw)
    print(f"중괄호 자동 닫기 적용 후: {ai_json_response_raw}")

    # 마크다운 코드 블록을 포함할 수 있으므로 먼저 제거합니다.
    cleaned_generated_text = ai_json_response_raw.strip()
    cleaned_generated_text = re.sub(r'^```(?:json)?\s*', '', cleaned_generated_text)
    cleaned_generated_text = re.sub(r'\s*```$', '', cleaned_generated_text)

    print(f"Gemma 모델의 클리닝된 생성 텍스트 (마크다운 제거): {cleaned_generated_text}") # 디버깅 추가

    # 이제 이 클리닝된 텍스트에서 JSON 객체만 찾습니다.
    start_idx = cleaned_generated_text.find('{')
    end_idx = cleaned_generated_text.rfind('}')

    ai_json_response_raw = "" # JSON 최종 후보
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        ai_json_response_raw = cleaned_generated_text[start_idx : end_idx + 1]

    print(f"Gemma 모델의 JSON 원시 응답 (최종 후보): {ai_json_response_raw}") # 디버깅을 위해 출력

    # JSON 파싱 시도 (2단계 파싱 구조)
    parsed_intent = {"action": "unknown", "entities": {}}
    
    try:
        # 1단계 파싱 시도: 원시 응답을 직접 json5로 로드 (대부분의 경우 성공 기대)
        parsed_intent = json5.loads(ai_json_response_raw)
        action = parsed_intent.get('action')
        entities = parsed_intent.get('entities', {})
        print(f"1단계 파싱 성공: 액션: {action}, 개체명: {entities}") # 디버깅
        action, entities = postprocess_intent(action, entities, user_input)
        print(f"[후처리 최종] action: {action}, entities: {entities}")
        return _process_parsed_intent(action, entities)
    except (json.JSONDecodeError, ValueError) as e1:
        print(f"1단계 파싱 실패: {e1}. 2단계 클리닝 시도.")
        json_candidate = ""
        try:
            # 원시 응답에서 첫 번째 '{'와 마지막 '}' 사이의 문자열을 추출
            start_idx = ai_json_response_raw.find('{')
            end_idx = ai_json_response_raw.rfind('}')

            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_candidate = ai_json_response_raw[start_idx : end_idx + 1]

            print(f"2단계 클리닝 후 JSON 후보: '{json_candidate}'") # 디버깅 추가

            # 마크다운 코드 블록 제거 (선택적, 위에 { } 추출이 더 중요)
            json_candidate = re.sub(r'^```(?:json)?\s*', '', json_candidate)
            json_candidate = re.sub(r'\s*```$', '', json_candidate)

            parsed_intent = json5.loads(json_candidate) # json5를 사용하여 파싱
            action = parsed_intent.get('action')
            entities = parsed_intent.get('entities', {})
            print(f"2단계 파싱 성공 (클리닝): 액션: {action}, 개체명: {entities}") # 디버깅
            action, entities = postprocess_intent(action, entities, user_input)
            print(f"[후처리 최종] action: {action}, entities: {entities}")
            return _process_parsed_intent(action, entities)
        except (json.JSONDecodeError, ValueError) as e2: # 2단계 파싱 실패 (Json5DecodeError 제거)
            print(f"2단계 파싱도 실패: {e2}. 최종 unknown 처리. 원시 응답: {ai_json_response_raw}")
            print(f"시도된 JSON 후보: '{json_candidate}'") # 디버깅 추가
            action = "unknown"
            entities = {}
        except Exception as e3:
            print(f"응답 처리 중 예기치 않은 예외 오류: {e3}")
            action = "unknown"
            entities = {}
    # 모든 파싱 시도 실패 시 최종 unknown 처리 (이 부분이 실행될 일은 거의 없어야 함)
    return _process_parsed_intent(parsed_intent.get('action', 'unknown'), parsed_intent.get('entities', {}))

# --- 파싱된 의도와 개체명을 바탕으로 WMS 기능 실행 (헬퍼 함수로 분리) ---
def _process_parsed_intent(action, entities):
    # 역할 기반 명령 권한 확인
    current_user_role = session.get('role')
    
    role_permissions = {
        'admin': ['query_stock', 'query_location_items', 'inbound', 'outbound', 'query_inbound_history', 'query_outbound_history', 'unknown'], # 새로운 액션 추가
        'inbound_manager': ['inbound', 'query_stock', 'query_location_items', 'query_inbound_history', 'unknown'], # 새로운 액션 추가
        'outbound_manager': ['outbound', 'query_stock', 'query_location_items', 'query_outbound_history', 'unknown'], # 새로운 액션 추가
        'inventory_manager': ['query_stock', 'query_location_items', 'query_inbound_history', 'query_outbound_history', 'unknown'], # 새로운 액션 추가
        'all_manager': ['inbound', 'outbound', 'query_stock', 'query_location_items', 'query_inbound_history', 'query_outbound_history', 'unknown'], # 새로운 액션 추가
        'default': ['unknown'] 
    }

    allowed_actions = role_permissions.get(current_user_role, role_permissions['default'])

    if action not in allowed_actions and action != "unknown": 
        print(f"권한 없음: 사용자 역할 '{current_user_role}'은/는 액션 '{action}'을 수행할 수 없습니다.")
        return "죄송합니다. 이 명령을 실행할 권한이 없습니다. 귀하의 역할에 맞는 명령을 사용해주세요."

    if action == "query_stock":
        if entities.get('all_stock'):
            stock_info = database_manager.get_current_stock(product_name=None, all_stock=True)
            if not stock_info:
                return "현재 재고 정보가 없습니다. 입고된 제품이 없거나 데이터베이스에 문제가 있을 수 있습니다."
            response_messages = ["현재 모든 제품의 재고 현황입니다:"]
            for item in stock_info:
                p_name, total_qty, locations = item[0], item[1], item[2]
                location_text = f"({locations})" if locations else "(위치 미지정)"
                response_messages.append(f"- {p_name}: {total_qty}개 {location_text}")
            return "\n".join(response_messages) 
        elif entities.get('product_name'):
            product_name = entities['product_name']
            stock_info = database_manager.get_current_stock(product_name=product_name, all_stock=False)
            if not stock_info:
                return f"'{product_name}'의 재고 정보가 없습니다. 제품명이 정확한지 확인해 주세요."
            response_messages = [f"'{product_name}'의 현재 재고는 다음과 같습니다:"]
            for item in stock_info:
                p_name, total_qty, locations = item[0], item[1], item[2]
                location_text = f"({locations})" if locations else "(위치 미지정)"
                response_messages.append(f"- {p_name}: {total_qty}개 {location_text}")
            return "\n".join(response_messages) 
        else:
            return "어떤 재고 정보를 조회하시겠습니까? 제품명을 알려주시거나 '전체 재고'라고 말씀해주세요."
    
    elif action == "query_location_items":
        location_code = entities.get('location_code')
        if location_code:
            products_in_loc = database_manager.get_products_in_location(location_code)
            if products_in_loc:
                response_messages = [f"'{location_code}' 로케이션에는 다음 제품들이 있습니다:"]
                for product_name, quantity in products_in_loc:
                    response_messages.append(f"- {product_name}: {quantity}개")
                return "\n".join(response_messages)
            else:
                location_info = database_manager.get_location_id(location_code)
                if location_info:
                    return f"'{location_code}' 로케이션에는 현재 아무 제품도 보관되어 있지 않습니다."
                else:
                    return f"죄송합니다. '{location_code}'이라는 로케이션을 찾을 수 없습니다. 정확한 로케이션 코드를 알려주시겠어요?"
        else:
            return "어떤 로케이션의 제품을 조회하시겠습니까? 로케이션 코드를 알려주세요. (예: A-01-01)"

    elif action == "inbound":
        product_name = entities.get('product_name')
        quantity = entities.get('quantity')
        location_code = entities.get('location_code') 

        if product_name and quantity is not None:
            # DB 결과값 체크 및 예외 처리
            product_info = database_manager.get_product_id(product_name)
            if not product_info:
                return f"'{product_name}'이라는 제품을 찾을 수 없습니다. 제품명을 다시 확인해 주세요."
            product_id, actual_product_name = product_info[0], product_info[1]

            if location_code: 
                location_info = database_manager.get_location_id(location_code)
                if not location_info:
                    return f"'{location_code}'이라는 로케이션을 찾을 수 없습니다. 정확한 로케이션 코드를 입력해 주세요. (예: A-01-01)"
                location_id, actual_location_code = location_info[0], location_info[1]
                if database_manager.record_inbound(product_id, quantity, location_id):
                    return f"'{actual_product_name}' {quantity}개를 '{actual_location_code}' 로케이션에 성공적으로 입고 처리했습니다. 재고가 업데이트되었습니다."
                else:
                    return f"'{actual_product_name}' {quantity}개 입고 중 오류가 발생했습니다. 다시 시도해주세요."
            else:
                current_conversation_state['action'] = 'awaiting_location'
                current_conversation_state['product_id'] = product_id
                current_conversation_state['quantity'] = quantity
                current_conversation_state['product_name'] = actual_product_name
                return f"알겠습니다. '{actual_product_name}' {quantity}개를 입고 처리하겠습니다. 어느 로케이션에 보관하시겠습니까? (예: A-01-01)"
        else:
            return "어떤 제품을 몇 개 입고하시겠습니까? (예: 노트북 5개)"

    elif action == "outbound":
        product_name = entities.get('product_name')
        quantity = entities.get('quantity')

        if product_name and quantity is not None:
            product_info = database_manager.get_product_id(product_name)
            if product_info:
                product_id, actual_product_name = product_info[0], product_info[1]
                result = database_manager.record_outbound(product_id, quantity)
                if isinstance(result, dict) and result.get("status") is True: 
                    picking_message = f"'{actual_product_name}' {quantity}개를 성공적으로 출고 처리했습니다. 재고가 업데이트되었습니다.\n\n피킹 지시사항:\n"
                    for instruction in result.get("picking_instructions", []):
                        picking_message += f"- {instruction}\n"
                    return picking_message
                elif result == "재고 부족":
                    stock_details = database_manager.get_current_stock(actual_product_name)
                    detail_msg = []
                    if stock_details:
                        for item in stock_details:
                            p_name, total_qty, locations = item[0], item[1], item[2]
                            location_text = f"({locations})" if locations else "(위치 미지정)"
                            detail_msg.append(f"현재 {p_name}은 총 {total_qty}개 있으며, 다음 위치에 있습니다: {locations}.")
                    
                    conn_temp = database_manager.get_db_connection()
                    total_current_stock_val = 0
                    if conn_temp:
                        cursor_temp = conn_temp.cursor()
                        cursor_temp.execute("SELECT SUM(quantity) FROM stock WHERE product_id = %s;", (product_id,))
                        total_stock_result = cursor_temp.fetchone()
                        total_current_stock_val = total_stock_result[0] if total_stock_result and total_stock_result[0] is not None else 0
                        cursor_temp.close()
                        conn_temp.close()

                    return f"죄송합니다. '{actual_product_name}'의 재고가 부족합니다. 요청하신 수량은 {quantity}개이며, 현재 재고는 {total_current_stock_val}개입니다. {(' '.join(detail_msg)) if detail_msg else '재고 위치를 확인해주세요.'}" 
                else: 
                    return f"'{actual_product_name}' {quantity}개 출고 중 오류가 발생했습니다. 다시 시도해주세요." 
            else:
                return f"죄송합니다. '{product_name}'이라는 제품을 찾을 수 없습니다. 정확한 제품명을 알려주시거나, 먼저 제품 등록을 요청해주세요." 
        else:
            return "어떤 제품을 몇 개 출고하시겠습니까? (예: 노트북 2개)"
    
    elif action == "query_inbound_history": # 새로운 액션 처리
        limit = entities.get('limit', 5) # 기본 5개
        recent_inbounds = database_manager.get_recent_inbounds(limit=limit)
        if recent_inbounds:
            response_messages = [f"최신 입고 기록 {len(recent_inbounds)}건입니다:"]
            for item in recent_inbounds:
                p_name, qty, date, supplier = item[0], item[1], item[2].strftime('%Y-%m-%d %H:%M'), item[3]
                response_messages.append(f"- {p_name} {qty}개 ({date}, 공급처: {supplier})")
            return "\n".join(response_messages)
        else:
            return "최신 입고 기록이 없습니다."

    elif action == "query_outbound_history": # 새로운 액션 처리
        limit = entities.get('limit', 5) # 기본 5개
        recent_outbounds = database_manager.get_recent_outbounds(limit=limit)
        if recent_outbounds:
            response_messages = [f"최신 출고 기록 {len(recent_outbounds)}건입니다:"]
            for item in recent_outbounds:
                p_name, qty, date, customer = item[0], item[1], item[2].strftime('%Y-%m-%d %H:%M'), item[3]
                response_messages.append(f"- {p_name} {qty}개 ({date}, 고객: {customer})")
            return "\n".join(response_messages)
        else:
            return "최신 출고 기록이 없습니다."

    elif action == "unknown":
        return "죄송합니다. 요청하신 내용을 정확히 이해하지 못했습니다. 입고, 출고, 재고 조회 또는 로케이션별 제품 조회와 같은 WMS 관련 명령으로 다시 말씀해 주시겠어요?"

    else: 
        return "죄송합니다. 요청하신 작업을 처리할 수 없습니다. 다른 명령을 내려주시겠어요?"


# --- 웹 페이지 라우팅 (URL 설정) ---
@app.route('/')
def login():
    return render_template('login.html')

@app.route('/dashboard')
@login_required 
def dashboard():
    recent_inbounds = database_manager.get_recent_inbounds() 
    recent_outbounds = database_manager.get_recent_outbounds() 
    current_stocks = database_manager.get_current_stock(product_name=None) 

    return render_template('dashboard.html', 
                           recent_inbounds=recent_inbounds, 
                           recent_outbounds=recent_outbounds,
                           current_stocks=current_stocks)

@app.route('/chat_ai')
@login_required 
def chat_ai_page():
    return render_template('chat_ai.html')

# --- 역할별 관리 페이지 (placeholder) ---

@app.route('/admin_page')
@login_required
@role_required(['admin'])
def admin_page():
    return render_template('admin_page.html')

@app.route('/inbound_page')
@login_required
@role_required(['admin', 'inbound_manager', 'all_manager'])
def inbound_page():
    products = database_manager.get_all_products() 
    locations = database_manager.get_all_locations() 
    return render_template('inbound_page.html', products=products, locations=locations)

@app.route('/inbound_process', methods=['POST'])
@login_required
@role_required(['admin', 'inbound_manager', 'all_manager'])
def inbound_process():
    if request.is_json:
        data = request.get_json()
        product_id = data.get('product_id')
        quantity = data.get('quantity')
        location_id = data.get('location_id')
    else:
        product_id = request.form.get('product_id', type=int)
        quantity = request.form.get('quantity', type=int)
        location_id = request.form.get('location_id', type=int)

    if not all([product_id, quantity, location_id]):
        return jsonify(status='error', message='모든 필드를 입력해주세요.'), 400

    product_info = database_manager.get_product_id_by_id(product_id) 
    if not product_info:
        return jsonify(status='error', message='유효하지 않은 제품입니다.'), 400
    actual_product_name = product_info[1]

    location_info = database_manager.get_location_id_by_id(location_id) 
    if not location_info:
        return jsonify(status='error', message='유효하지 않은 로케이션입니다.'), 400
    actual_location_code = location_info[1] 

    if database_manager.record_inbound(product_id, quantity, location_id):
        return jsonify(status='success', message=f"'{actual_product_name}' {quantity}개를 '{actual_location_code}' 로케이션에 성공적으로 입고 처리했습니다.")
    else:
        return jsonify(status='error', message='입고 처리 중 데이터베이스 오류가 발생했습니다. 로그를 확인해주세요.'), 500


@app.route('/outbound_page')
@login_required
@role_required(['admin', 'outbound_manager', 'all_manager'])
def outbound_page():
    products = database_manager.get_all_products() 
    return render_template('outbound_page.html', products=products)

@app.route('/outbound_process', methods=['POST'])
@login_required
@role_required(['admin', 'outbound_manager', 'all_manager'])
def outbound_process():
    if request.is_json:
        data = request.get_json()
        product_id = data.get('product_id')
        quantity = data.get('quantity')
    else:
        product_id = request.form.get('product_id', type=int)
        quantity = request.form.get('quantity', type=int)

    if not all([product_id, quantity]):
        return jsonify(status='error', message='모든 필드를 입력해주세요.'), 400

    product_info = database_manager.get_product_id_by_id(product_id) 
    if not product_info:
        return jsonify(status='error', message='유효하지 않은 제품입니다.'), 400
    actual_product_name = product_info[1]

    result = database_manager.record_outbound(product_id, quantity)
    if isinstance(result, dict) and result.get("status") is True:
        picking_message = f"'{actual_product_name}' {quantity}개를 성공적으로 출고 처리했습니다. 재고가 업데이트되었습니다."
        if result.get("picking_instructions"):
            instructions = result.get("picking_instructions")
            if not isinstance(instructions, list):
                instructions = []
            picking_message += "\n\n피킹 지시사항:\n" + "\n".join(str(i) for i in instructions)
        return jsonify(status='success', message=picking_message, picking_instructions=result.get("picking_instructions"))
    elif result == "재고 부족":
        stock_details = database_manager.get_current_stock(actual_product_name)
        detail_msg_list = []
        if stock_details:
            for item in stock_details:
                p_name, total_qty, locations = item[0], item[1], item[2]
                location_text = f"({locations})" if locations else "(위치 미지정)"
                detail_msg_list.append(f"현재 {p_name}은 총 {total_qty}개 있으며, 다음 위치에 있습니다: {locations}.")
        
        conn_temp = database_manager.get_db_connection()
        total_current_stock_val = 0
        if conn_temp:
            cursor_temp = conn_temp.cursor()
            cursor_temp.execute("SELECT SUM(quantity) FROM stock WHERE product_id = %s;", (product_id,))
            total_stock_result = cursor_temp.fetchone()
            total_current_stock_val = total_stock_result[0] if total_stock_result and total_stock_result[0] is not None else 0
            cursor_temp.close()
            conn_temp.close()

        error_message = f"죄송합니다. '{actual_product_name}'의 재고가 부족합니다. 요청하신 수량은 {quantity}개이며, 현재 재고는 {total_current_stock_val}개입니다. {(' '.join(detail_msg_list)) if detail_msg_list else '재고 위치를 확인해주세요.'}"
        return jsonify(status='error', message=error_message), 400
    else: # 기타 오류
        return jsonify(status='error', message=f'출고 처리 중 오류가 발생했습니다: {result}'), 500


@app.route('/inventory_page')
@login_required
@role_required(['admin', 'inventory_manager', 'all_manager'])
def inventory_page():
    current_stocks = database_manager.get_current_stock(product_name=None) 
    return render_template('inventory_page.html', current_stocks=current_stocks)

@app.route('/get_stock_data')
@login_required
@role_required(['admin', 'inventory_manager', 'all_manager'])
def get_stock_data():
    product_name_filter = request.args.get('product_name', '')
    stocks = database_manager.get_current_stock(product_name_filter)
    return jsonify(stocks=stocks)


# 사용자 로그인 처리
@app.route('/login', methods=['POST'])
def login_post():
    username = request.form['username']
    password = request.form['password']

    user = database_manager.get_user_by_username(username) 

    if user and check_password_hash(user[2], password): 
        session['username'] = user[1] 
        session['role'] = user[3] 
        flash('로그인 성공!', 'success') 
        return redirect(url_for('dashboard')) 
    else:
        flash('유효하지 않은 사용자 ID 또는 비밀번호입니다.', 'danger') 
        return render_template('login.html') 

# 로그아웃 처리
@app.route('/logout')
def logout():
    session.pop('username', None) 
    session.pop('role', None) 
    flash('로그아웃되었습니다.', 'info') 
    return redirect(url_for('login')) 


@app.route('/chat', methods=['POST'])
@login_required 
def chat():
    user_message = request.json.get('message')
    print(f"사용자 메시지 수신: {user_message}")

    ai_response = generate_ai_response(user_message)
    print(f"AI 응답 전송: {ai_response}")

    return jsonify({'response': ai_response})


# --- 자동 중괄호 닫기 함수 추가 ---
def auto_close_braces(json_str):
    open_count = json_str.count('{')
    close_count = json_str.count('}')
    if open_count > close_count:
        json_str += '}' * (open_count - close_count)
    return json_str

def postprocess_intent(action, entities, user_input):
    norm_input = re.sub(r"\s+", "", user_input)
    # '전체 재고' 또는 '전체 재고 현황' 등 전체 재고 질의는 무조건 query_stock + all_stock=True
    if re.search(r"전체\s*재고(\s*현황)?", user_input) or norm_input.startswith("전체재고"):
        action = "query_stock"
        entities = {"all_stock": True}  # 기존 entities를 덮어쓰기
        print("후처리: '전체 재고' 질의로 인식되어 query_stock + all_stock=True로 강제 분기")
        return action, entities  # 전체 재고 조회는 다른 후처리 무시하고 바로 반환
    
    # '출고' 키워드가 있고 action이 outbound가 아니면 무조건 outbound로 강제 변환
    if (
        re.search(r"출고", user_input)
        and action != "outbound"
    ):
        action = "outbound"
        print("후처리: '출고' 키워드가 있으나 action이 outbound가 아니어서 outbound로 강제 변환")
    
    # '입고' 키워드가 있고 action이 inbound가 아니면 무조건 inbound로 강제 변환
    if (
        re.search(r"입고", user_input)
        and action != "inbound"
    ):
        action = "inbound"
        print("후처리: '입고' 키워드가 있으나 action이 inbound가 아니어서 inbound로 강제 변환")
    
    # 출고 현황/내역/목록/리스트/이력 → query_outbound_history (띄어쓰기/붙여쓰기 무관)
    if (
        re.search(r"출고.*(현황|내역|목록|리스트|이력)", user_input)
        or re.search(r"(현황|내역|목록|리스트|이력).*출고", user_input)
        or re.search(r"출고(현황|내역|목록|리스트|이력)", norm_input)
        or re.search(r"(현황|내역|목록|리스트|이력)출고", norm_input)
    ):
        action = "query_outbound_history"
        entities = {k: v for k, v in entities.items() if k != "all_stock"}
        print(f"후처리: '출고' + '현황/내역/목록/리스트/이력' 조합(띄어쓰기/붙여쓰기 무관) → query_outbound_history로 강제 변환")
    
    # 재고 현황/내역/목록/리스트/이력/조회 → query_stock (띄어쓰기/붙여쓰기 무관)
    if (
        re.search(r"재고.*(현황|내역|목록|리스트|이력|조회)", user_input)
        or re.search(r"(현황|내역|목록|리스트|이력|조회).*재고", user_input)
        or re.search(r"재고(현황|내역|목록|리스트|이력|조회)", norm_input)
        or re.search(r"(현황|내역|목록|리스트|이력|조회)재고", norm_input)
    ):
        action = "query_stock"
        # 제품명이 명시되지 않은 재고 질의(예: '재고 현황', '전체 재고 현황', '전체 재고')는 product_name 제거, all_stock=True
        if (entities.get("product_name") and entities["product_name"].strip() in ["재고", "재고현황", "현황", "재고 조회", "재고현황조회", "", "전체", "전체재고", "전체 재고", "전체 재고 현황"]):
            print("후처리: 제품명이 없는 재고 질의(또는 전체 재고 질의)로 인식되어 product_name 제거 및 all_stock=True 설정")
            entities = {"all_stock": True}  # 기존 entities를 덮어쓰기
        else:
            entities = {k: v for k, v in entities.items() if k != "all_stock"}
        print(f"후처리: '재고' 관련 질의(띄어쓰기/붙여쓰기 무관) → query_stock으로 강제 변환")
    
    # '입고 현황/내역/이력/목록/리스트' → query_inbound_history
    if (
        re.search(r"입고.*(현황|내역|목록|리스트|이력)", user_input)
        or re.search(r"(현황|내역|목록|리스트|이력).*입고", user_input)
        or re.search(r"입고(현황|내역|목록|리스트|이력)", norm_input)
        or re.search(r"(현황|내역|목록|리스트|이력)입고", norm_input)
    ):
        action = "query_inbound_history"
        print("후처리: '입고' + '현황/내역/목록/리스트/이력' 조합 → query_inbound_history로 강제 변환")
    
    # action이 inbound일 때 product_name, quantity 자동 추출 보완 (정규식 개선)
    if action == "inbound":
        match = re.search(r"(.+?)\s*(\d+)\s*(개|대|박스|box|ea|EA|Box|BOX)?\s*(입고|출고)?", user_input)
        if match:
            name = match.group(1).strip()
            qty = int(match.group(2))
            if not entities.get("product_name"):
                entities["product_name"] = name
            if not entities.get("quantity"):
                entities["quantity"] = qty
            print(f"후처리: 입력에서 product_name/quantity 자동 추출 및 보완: {name}, {qty}")
    
    # action이 outbound일 때 product_name, quantity 자동 추출 보완
    if action == "outbound":
        match = re.search(r"(.+?)\s*(\d+)\s*(개|대|박스|box|ea|EA|Box|BOX)?\s*(출고)?", user_input)
        if match:
            name = match.group(1).strip()
            qty = int(match.group(2))
            if not entities.get("product_name"):
                entities["product_name"] = name
            if not entities.get("quantity"):
                entities["quantity"] = qty
            print(f"후처리: 입력에서 product_name/quantity 자동 추출 및 보완(출고): {name}, {qty}")
    
    # 로케이션 재고/현황/조회 등 → query_location_items + location_code 자동 추출
    location_match = re.search(r"([A-Za-z]\d{2}-\d{2}|[A-Za-z]-\d{2}-\d{2})", user_input)
    if (
        (re.search(r"로케이션|location", user_input, re.IGNORECASE) or location_match)
        and (re.search(r"재고|현황|조회|품목|아이템|item", user_input))
    ):
        if location_match:
            location_code = location_match.group(1)
            action = "query_location_items"
            entities = {"location_code": location_code}  # 기존 entities를 덮어쓰기
            print(f"후처리: 로케이션 질의 → query_location_items + location_code={location_code}로 강제 변환")
    
    # action이 query_stock일 때 product_name 자동 추출 보완
    if action == "query_stock":
        match = re.search(r"([가-힣A-Za-z0-9_\- ]+?)\s*(재고|재고현황|재고 조회|현황|조회)", user_input)
        if match:
            name = match.group(1).strip()
            if not entities.get("product_name") and name not in ["재고", "재고현황", "현황", "재고 조회", "재고현황조회", "", "전체", "전체재고", "전체 재고", "전체 재고 현황"]:
                entities["product_name"] = name
            print(f"후처리: 입력에서 product_name 자동 추출 및 보완(재고): {name}")
    
    return action, entities

# --- 앱 실행 ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
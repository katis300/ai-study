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
        quantization_config=nf4_config,
        device_map="auto"
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


# --- AI 응답 생성 함수 (Gemma 활용 및 WMS 연동) ---
def generate_ai_response(user_input):
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
    당신은 창고 관리 시스템(WMS)의 AI 비서입니다. 사용자의 질문을 분석하여 요청하는 '액션(action)'과 '개체명(entities)'을 JSON 형식으로 추출해야 합니다. JSON 형식으로만 응답하며, 다른 설명은 추가하지 마세요.

    가능한 액션(action) 목록:
    - "query_stock": 재고를 조회하는 요청 (예: 재고 현황, 현재 재고, 전체 재고)
    - "query_location_items": 특정 로케이션에 있는 품목을 조회하는 요청 (예: A-01-01에 뭐가 있어?, B-02-01 제품 알려줘)
    - "inbound": 제품을 입고하는 요청 (예: 노트북 5개 입고해 줘, 펜 100개 넣어줘)
    - "outbound": 제품을 출고하는 요청 (예: 노트북 2개 출고해 줘, 무선 마우스 1개 판매, HDMI 케이블 100개 출하)
    - "unknown": 위 액션에 해당하지 않는 일반적인 질문 또는 이해할 수 없는 요청

    개체명(entities)은 다음과 같습니다:
    - product_name (string, 제품명): 조회/입고/출고할 제품 이름 (예: "노트북 컴퓨터", "무선 마우스")
    - quantity (integer, 수량): 입고/출고할 제품의 수량 (숫자)
    - location_code (string, 로케이션 코드): 로케이션의 고유 코드 (예: "A-01-01", "B-02-01")
    - all_stock (boolean, 전체 재고): 전체 재고를 요청하는 경우 (true)

    응답은 반드시 하나의 JSON 객체여야 합니다.

    예시:
    사용자: 노트북 5개 입고해 줘
    응답: {"action": "inbound", "entities": {"product_name": "노트북 컴퓨터", "quantity": 5}}

    사용자: 무선 마우스 재고는?
    응답: {"action": "query_stock", "entities": {"product_name": "무선 마우스"}}

    사용자: 전체 재고 보여줘
    응답: {"action": "query_stock", "entities": {"all_stock": true}}

    사용자: A-01-01에 뭐가 있어?
    응답: {"action": "query_location_items", "entities": {"location_code": "A-01-01"}}

    사용자: B-02-01에 있는 제품 알려줘
    응답: {"action": "query_location_items", "entities": {"location_code": "B-02-01"}}

    사용자: C-03-05에 제품이 뭐야?
    응답: {"action": "query_location_items", "entities": {"location_code": "C-03-05"}}

    사용자: 노트북 2개 출고해 줘
    응답: {"action": "outbound", "entities": {"product_name": "노트북 컴퓨터", "quantity": 2}}

    사용자: 무선 마우스 1개 판매
    응답: {"action": "outbound", "entities": {"product_name": "무선 마우스", "quantity": 1}}

    사용자: HDMI 케이블 100개 출하
    응답: {"action": "outbound", "entities": {"product_name": "HDMI 케이블", "quantity": 100}}

    사용자: 안녕하세요
    응답: {"action": "unknown", "entities": {}}

    사용자: 재고 없는 제품 찾아줘
    응답: {"action": "query_stock", "entities": {"quantity": 0}}

    # 추가/수정된 예시: 의도 파악 정확도 향상 및 JSON 반환 안정화
    사용자: 입고 현황
    응답: {"action": "query_stock", "entities": {"all_stock": true}} 

    사용자: 출고 현황
    응답: {"action": "query_stock", "entities": {"all_stock": true}}

    사용자: 노트북 10대 입고 해줘
    응답: {"action": "inbound", "entities": {"product_name": "노트북 컴퓨터", "quantity": 10}}

    사용자: 노트북 10대 출고 해줘
    응답: {"action": "outbound", "entities": {"product_name": "노트북 컴퓨터", "quantity": 10}}
    
    사용자: 이거 뭐야?
    응답: {"action": "unknown", "entities": {}}

    사용자: {user_input}
    응답:
    """

    # Gemma 모델을 사용하여 사용자 입력 분석
    full_prompt = SYSTEM_PROMPT.replace("{user_input}", user_input)
    input_ids = tokenizer(full_prompt, return_tensors="pt").to(model.device)
    outputs = model.generate(**input_ids, max_new_tokens=200, do_sample=True, top_p=0.9, temperature=0.7)
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    # 프롬프트 부분을 제거하고 순수 AI 응답만 추출
    ai_json_response_raw = generated_text.replace(full_prompt, "").strip()
    print(f"Gemma 모델의 JSON 원시 응답: {ai_json_response_raw}") # 디버깅을 위해 출력

    # JSON 파싱 시도 (json5 라이브러리 활용)
    parsed_intent = {"action": "unknown", "entities": {}} # 초기값 설정
    try:
        # 1차: 원시 응답을 바로 파싱 시도
        try:
            parsed_intent = json5.loads(ai_json_response_raw)
            action = parsed_intent.get('action')
            entities = parsed_intent.get('entities', {})
            print(f"파싱된 액션: {action}, 개체명: {entities}") # 디버깅
        except Exception as e1:
            # 2차: 클리닝 및 정규식 추출 후 파싱 시도
            clean_json_str = ai_json_response_raw.strip().replace('```json', '').replace('```', '').strip()
            clean_json_str = re.sub(r'[^\w\s\uAC00-\uD7A3\{\}\[\]:,."_\-]', '', clean_json_str)
            json_match = re.search(r'\{.*?\}', clean_json_str, re.DOTALL)
            if json_match:
                json_string = json_match.group(0)
                parsed_intent = json5.loads(json_string)
                action = parsed_intent.get('action')
                entities = parsed_intent.get('entities', {})
                print(f"파싱된 액션(클리닝): {action}, 개체명: {entities}") # 디버깅
            else:
                print(f"JSON 객체를 찾을 수 없습니다. 원시 응답: {ai_json_response_raw}")
                action = "unknown"
                entities = {}
    except (json.JSONDecodeError, ValueError) as e: # ValueError도 포함
        print(f"JSON 파싱 오류: {e}. 원시 응답: {ai_json_response_raw}")
        action = "unknown"
        entities = {}
    except Exception as e:
        print(f"응답 처리 중 예기치 않은 오류: {e}")
        action = "unknown"
        entities = {}

    # --- 파싱된 의도와 개체명을 바탕으로 WMS 기능 실행 ---

    # 역할 기반 명령 권한 확인
    current_user_role = session.get('role')
    
    role_permissions = {
        'admin': ['query_stock', 'query_location_items', 'inbound', 'outbound', 'unknown'],
        'inbound_manager': ['inbound', 'query_stock', 'query_location_items', 'unknown'],
        'outbound_manager': ['outbound', 'query_stock', 'query_location_items', 'unknown'],
        'inventory_manager': ['query_stock', 'query_location_items', 'unknown'],
        'all_manager': ['inbound', 'outbound', 'query_stock', 'query_location_items', 'unknown'],
        'default': ['unknown'] 
    }

    allowed_actions = role_permissions.get(current_user_role, role_permissions['default'])

    if action not in allowed_actions and action != "unknown": 
        print(f"권한 없음: 사용자 역할 '{current_user_role}'은/는 액션 '{action}'을 수행할 수 없습니다.")
        return "죄송합니다. 이 명령을 실행할 권한이 없습니다. 귀하의 역할에 맞는 명령을 사용해주세요."

    if action == "query_stock":
        if entities.get('all_stock'):
            stock_info = database_manager.get_current_stock(product_name=None)
            if stock_info:
                response_messages = ["현재 모든 제품의 재고 현황입니다:"]
                for item in stock_info:
                    p_name, total_qty, locations = item[0], item[1], item[2]
                    location_text = f"({locations})" if locations else "(위치 미지정)"
                    response_messages.append(f"- {p_name}: {total_qty}개 {location_text}")
                return "\n".join(response_messages) 
            else:
                return "현재 재고 정보가 없습니다. 입고된 제품이 없거나 데이터베이스에 문제가 있을 수 있습니다."
        elif entities.get('product_name'):
            product_name = entities['product_name']
            stock_info = database_manager.get_current_stock(product_name=product_name)
            if stock_info:
                response_messages = [f"'{product_name}'의 현재 재고는 다음과 같습니다:"]
                for item in stock_info:
                    p_name, total_qty, locations = item[0], item[1], item[2]
                    location_text = f"({locations})" if locations else "(위치 미지정)"
                    response_messages.append(f"- {p_name}: {total_qty}개 {location_text}")
                return "\n".join(response_messages) 
            else:
                return f"죄송합니다. '{product_name}'에 대한 재고 정보를 찾을 수 없습니다. 제품명을 다시 확인해주세요."
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
        location_code = entities.get('location_code') # 입고 시 로케이션도 함께 받도록 확장

        if product_name and quantity is not None:
            product_info = database_manager.get_product_id(product_name)
            if product_info:
                product_id, actual_product_name = product_info[0], product_info[1]

                if location_code: # 로케이션 코드가 JSON에 포함된 경우 바로 처리
                    location_info = database_manager.get_location_id(location_code)
                    if location_info:
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
                        return f"죄송합니다. '{location_code}'이라는 로케이션을 찾을 수 없습니다. '{actual_product_name}' {quantity}개를 입고 처리하겠습니다. 어느 로케이션에 보관하시겠습니까? (예: A-01-01)"
                else: # 로케이션 코드가 JSON에 없는 경우, 사용자에게 물어봄 (기존 다단계 대화)
                    current_conversation_state['action'] = 'awaiting_location'
                    current_conversation_state['product_id'] = product_id
                    current_conversation_state['quantity'] = quantity
                    current_conversation_state['product_name'] = actual_product_name
                    return f"알겠습니다. '{actual_product_name}' {quantity}개를 입고 처리하겠습니다. 어느 로케이션에 보관하시겠습니까? (예: A-01-01)"
            else:
                return f"죄송합니다. '{product_name}'이라는 제품을 찾을 수 없습니다. 정확한 제품명을 알려주시거나, 먼저 제품 등록을 요청해주세요."
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


# --- 앱 실행 ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
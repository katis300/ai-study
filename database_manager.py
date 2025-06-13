# database_manager.py

import psycopg2
from psycopg2 import Error
from werkzeug.security import generate_password_hash 
from dotenv import load_dotenv 
import os 

# .env 파일 로드 (모듈 로드 시 가장 먼저 실행)
load_dotenv()

# --- 데이터베이스 연결 정보 (환경 변수에서 로드) ---
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT')

# --- 데이터베이스 연결 함수 ---
def get_db_connection():
    try:
        conn = psycopg2.connect(
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Error as e:
        print(f"데이터베이스 연결 오류: {e}")
        return None

# --- 사용자 정보 조회 함수 ---
def get_user_by_username(username):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, password_hash, role FROM users WHERE username = %s;", (username,))
        user = cursor.fetchone()
        return user 
    except Error as e:
        print(f"사용자 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close() 

# --- WMS 데이터베이스 연동 함수들 ---

def get_product_id(product_name):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        cursor = conn.cursor()
        cursor.execute("SELECT product_id, product_name FROM products WHERE LOWER(product_name) LIKE LOWER(%s);", (f'%{product_name}%',))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"제품 ID 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_location_id(location_code):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None

        cursor = conn.cursor()
        cursor.execute("SELECT location_id, location_code FROM locations WHERE LOWER(location_code) = LOWER(%s);", (location_code,))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"로케이션 ID 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def record_inbound(product_id, quantity, location_id, supplier="AI_WMS", received_by="AI_System"):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return False

        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO inbound (product_id, quantity, supplier, received_by) VALUES (%s, %s, %s, %s);",
            (product_id, quantity, supplier, received_by)
        )
        
        cursor.execute(
            "SELECT stock_id, quantity FROM stock WHERE product_id = %s AND location_id = %s;", 
            (product_id, location_id)
        )
        existing_stock = cursor.fetchone()

        if existing_stock:
            cursor.execute(
                "UPDATE stock SET quantity = quantity + %s WHERE stock_id = %s;",
                (quantity, existing_stock[0])
            )
            cursor.execute(
                "UPDATE locations SET current_weight_kg = current_weight_kg + (SELECT unit_price FROM products WHERE product_id = %s) * %s WHERE location_id = %s;",
                (product_id, quantity, location_id)
            )
        else:
            cursor.execute(
                "INSERT INTO stock (product_id, location_id, quantity, batch_number) VALUES (%s, %s, %s, NULL);", 
                (product_id, location_id, quantity)
            )
            cursor.execute(
                "UPDATE locations SET current_weight_kg = current_weight_kg + (SELECT unit_price FROM products WHERE product_id = %s) * %s WHERE location_id = %s;",
                (product_id, quantity, location_id)
            )
        
        conn.commit()
        return True
    except Error as e:
        conn.rollback()
        print(f"입고 처리 오류: {e}")
        return False
    finally:
        if conn: cursor.close(); conn.close()

def record_outbound(product_id, quantity, customer="AI_WMS", shipped_by="AI_System"):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return "DB 연결 오류"

        cursor = conn.cursor()
        cursor.execute("SELECT SUM(quantity) FROM stock WHERE product_id = %s;", (product_id,))
        total_current_stock_result = cursor.fetchone()
        total_current_stock = total_current_stock_result[0] if total_current_stock_result and total_current_stock_result[0] is not None else 0

        if total_current_stock < quantity:
            return "재고 부족"

        cursor.execute(
            "INSERT INTO outbound (product_id, quantity, customer, shipped_by) VALUES (%s, %s, %s, %s);",
            (product_id, quantity, customer, shipped_by)
        )
        
        picking_instructions = []
        remaining_to_deduct = quantity

        cursor.execute("""
            SELECT s.stock_id, s.quantity, l.location_id, l.location_code, p.product_name
            FROM stock s
            JOIN locations l ON s.location_id = l.location_id
            JOIN products p ON s.product_id = p.product_id
            WHERE s.product_id = %s AND s.quantity > 0
            ORDER BY l.location_code ASC, s.last_updated ASC;
        """, (product_id,))
        available_stocks = cursor.fetchall()
        
        for stock_item in available_stocks:
            stock_id, current_qty, location_db_id, location_code, product_name = stock_item 
            if remaining_to_deduct <= 0:
                break
            
            deduct_qty = min(current_qty, remaining_to_deduct)
            
            cursor.execute(
                "UPDATE stock SET quantity = quantity - %s WHERE stock_id = %s;",
                (deduct_qty, stock_id)
            )
            cursor.execute(
                "UPDATE locations SET current_weight_kg = current_weight_kg - (SELECT unit_price FROM products WHERE product_id = %s) * %s WHERE location_id = %s;",
                (product_id, deduct_qty, location_db_id) 
            )
            
            picking_instructions.append(f"'{location_code}' 로케이션에서 '{product_name}' {deduct_qty}개를 피킹하세요.")
            remaining_to_deduct -= deduct_qty

        conn.commit()

        if remaining_to_deduct > 0:
            return "출고 처리 완료. 하지만 요청 수량만큼 재고를 찾지 못했습니다. 데이터 확인이 필요합니다."

        return {
            "status": True,
            "message": f"'{product_name}' {quantity}개를 성공적으로 출고 처리했습니다. 재고가 업데이트되었습니다.",
            "picking_instructions": picking_instructions
        }
    except Error as e:
        conn.rollback()
        print(f"출고 처리 오류: {e}")
        return f"출고 처리 중 오류가 발생했습니다: {e}"
    finally:
        if conn: cursor.close(); conn.close()

def get_current_stock(product_name=None):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return []

        cursor = conn.cursor()
        if product_name:
            product_info = get_product_id(product_name)
            if not product_info:
                return [] 
            product_id, actual_product_name = product_info[0], product_info[1]
            cursor.execute("""
                SELECT p.product_name, SUM(s.quantity) AS total_quantity, STRING_AGG(l.location_code, ', ' ORDER BY l.location_code) AS locations
                FROM stock s
                JOIN products p ON s.product_id = p.product_id
                LEFT JOIN locations l ON s.location_id = l.location_id
                WHERE p.product_id = %s
                GROUP BY p.product_name;
            """, (product_id,))
            results = cursor.fetchall()
        else:
            cursor.execute("""
                SELECT p.product_name, SUM(s.quantity) AS total_quantity, STRING_AGG(DISTINCT l.location_code, ', ' ORDER BY l.location_code) AS locations
                FROM stock s
                JOIN products p ON s.product_id = p.product_id
                LEFT JOIN locations l ON s.location_id = l.location_id
                GROUP BY p.product_name
                ORDER BY p.product_name;
            """)
            results = cursor.fetchall()
        return results
    except Error as e:
        print(f"재고 조회 오류: {e}")
        return []
    finally:
        if conn: cursor.close(); conn.close()

def get_products_in_location(location_code):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return []
        cursor = conn.cursor()
        
        location_info = get_location_id(location_code)
        if not location_info:
            return [] 

        location_id, actual_location_code = location_info[0], location_info[1]

        cursor.execute("""
            SELECT p.product_name, s.quantity
            FROM stock s
            JOIN products p ON s.product_id = p.product_id
            WHERE s.location_id = %s AND s.quantity > 0
            ORDER BY p.product_name;
        """, (location_id,))
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"로케이션별 제품 조회 오류: {e}")
        return []
    finally:
        if conn: cursor.close(); conn.close()

def get_product_id_by_id(product_id):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        cursor.execute("SELECT product_id, product_name FROM products WHERE product_id = %s;", (product_id,))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"제품 ID로 제품 정보 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_location_id_by_id(location_id): 
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return None
        cursor = conn.cursor()
        cursor.execute("SELECT location_id, location_code FROM locations WHERE location_id = %s;", (location_id,))
        result = cursor.fetchone()
        return result
    except Error as e:
        print(f"로케이션 ID로 로케이션 정보 조회 오류: {e}")
        return None
    finally:
        if conn: cursor.close(); conn.close()

def get_all_products(): 
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("SELECT product_id, product_name FROM products ORDER BY product_name;")
        products = cursor.fetchall()
        return products
    except Error as e:
        print(f"제품 목록 조회 오류: {e}")
        return []
    finally:
        if conn: cursor.close(); conn.close()

def get_all_locations(): 
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("SELECT location_id, location_code FROM locations ORDER BY location_code;")
        locations = cursor.fetchall()
        return locations
    except Error as e:
        print(f"로케이션 목록 조회 오류: {e}")
        return []
    finally:
        if conn: cursor.close(); conn.close()

# --- 최신 입고 기록 조회 함수 (새로 추가) ---
def get_recent_inbounds(limit=5):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.product_name, i.quantity, i.inbound_date, i.supplier
            FROM inbound i
            JOIN products p ON i.product_id = p.product_id
            ORDER BY i.inbound_date DESC
            LIMIT %s;
        """, (limit,))
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"최신 입고 기록 조회 오류: {e}")
        return []
    finally:
        if conn: cursor.close(); conn.close()

# --- 최신 출고 기록 조회 함수 (새로 추가) ---
def get_recent_outbounds(limit=5):
    conn = None
    try:
        conn = get_db_connection()
        if not conn: return []
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.product_name, o.quantity, o.outbound_date, o.customer
            FROM outbound o
            JOIN products p ON o.product_id = p.product_id
            ORDER BY o.outbound_date DESC
            LIMIT %s;
        """, (limit,))
        results = cursor.fetchall()
        return results
    except Error as e:
        print(f"최신 출고 기록 조회 오류: {e}")
        return []
    finally:
        if conn: cursor.close(); conn.close()